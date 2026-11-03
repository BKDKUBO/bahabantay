import json, os, time, uuid
from datetime import datetime, timezone
from pathlib import Path
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from . import assess, cells, db, depth, geo
from .agent import Tools, detect_lang
from .aggregate import summarize
from .providers import get_providers

ROOT = Path(__file__).resolve().parent.parent
UPLOADS = Path(os.getenv("BAHABANTAY_UPLOADS", ROOT / "data" / "uploads"))
MAX_BYTES = 8 * 1024 * 1024


class Answer(BaseModel):
    reference: str          # person | door | car_tire | jeepney | curb
    submerged_pct: float    # how much of the object is under water, 0..100


class Vote(BaseModel):
    vote: str               # still | clear | unsure | gone ("No longer flooded")


class Review(BaseModel):
    action: str             # confirm | reject | request_info | escalate
    note: str = ""


class Publish(BaseModel):
    water_level: str | None = None   # reporter's correction on the "AI understood" card
    rising: str | None = None
    trend: str | None = None
    car_passable: str | None = None
    reported_depth_cm: int | None = None
    street: str | None = None


class HelpRequest(BaseModel):
    barangay: str
    street: str
    note: str = ""
    lat: float | None = None
    lng: float | None = None
    client_id: str = ""


class Question(BaseModel):
    barangay: str
    question: str
    lang: str = ""          # "fil" | "en"; detected from the question when empty


def create_app(db_path=None, provider=None) -> FastAPI:
    app = FastAPI(title="BahaBantay", version="0.3.0")
    conn = db.connect(db_path)
    vision, reporter, agent = get_providers(provider)
    UPLOADS.mkdir(parents=True, exist_ok=True)

    DEMO_CLOCK = os.getenv("BAHABANTAY_DEMO_CLOCK", "1") == "1"

    def demo_clock():
        """Keep the synthetic sample reports 'live' on a long-running instance: once the seed is
        >30 min old, shift every sample report forward by the elapsed time (relative ages are kept)."""
        if not DEMO_CLOCK: return
        r = conn.execute("SELECT v FROM meta WHERE k='seeded_at'").fetchone()
        if not r: return
        seeded = datetime.fromisoformat(r["v"]); delta = now() - seeded
        if delta.total_seconds() < 1800: return
        for x in conn.execute("SELECT id, reported_at FROM reports WHERE simulated=1"):
            t = datetime.fromisoformat(x["reported_at"]) + delta
            conn.execute("UPDATE reports SET reported_at=? WHERE id=?", (t.isoformat(timespec="seconds"), x["id"]))
        conn.execute("UPDATE meta SET v=? WHERE k='seeded_at'", (now().isoformat(timespec="seconds"),)); conn.commit()

    def all_reports():
        demo_clock()
        return [db.row(r) for r in conn.execute("SELECT * FROM reports WHERE status!='draft' ORDER BY reported_at, id")]

    def now():
        return datetime.now(timezone.utc)

    def side(table):
        out: dict[int, list] = {}
        for r in conn.execute(f"SELECT * FROM {table} ORDER BY at, id"):
            out.setdefault(r["incident_id"], []).append(dict(r))
        return out

    def build_incidents(view="public", barangay=None, include_inactive=False):
        votes, reviews, out = side("votes"), side("reviews"), []
        for root, rs in assess.group(all_reports()).items():
            head, latest = rs[0], rs[-1]
            if barangay and head["barangay"] != barangay: continue
            vrows, rv = votes.get(root, []), reviews.get(root, [])
            vc = {k: sum(v["vote"] == k for v in vrows) for k in ("still", "clear", "unsure", "gone")}
            a = assess.assess_incident(rs, vc, rv, now())
            if not a["active"] and not include_inactive: continue
            photo = next((r["image_path"] for r in reversed(rs) if r.get("image_path")), None)
            inc = {"id": root, "barangay": head["barangay"], "street": head["street"], "kind": "help" if head["kind"] == "help" else "flood",
                   "lat": latest["lat"], "lng": latest["lng"], "reports": len(rs), "votes": vc, "sample": all(r["simulated"] for r in rs),
                   "providers": sorted({r.get("provider") or "?" for r in rs}), "photo": photo,
                   "first_at": head["reported_at"], "latest_at": latest["reported_at"],
                   "approximate": any(r.get("loc_source") == "barangay" for r in rs),
                   "review": rv[-1]["action"] if rv else None, "covered": covered(head["barangay"]), **a}
            inc["share_text"] = assess.share_text(inc)
            if view == "responder":
                inc["evidence"] = assess.evidence(rs, vrows, rv)
                inc["members"] = [{k: r.get(k) for k in ("id", "reported_at", "note", "image_path", "depth_cm", "band", "confidence",
                                   "reference", "water_level", "rising", "trend", "car_passable", "reported_depth_cm", "provider", "kind", "lat", "lng", "status", "question", "simulated")}
                                  | {"assessment": r.get("assessment")} for r in rs]
            else:  # public: approximate location only, no free-text notes from help requests
                inc["lat"], inc["lng"] = round(inc["lat"], 3), round(inc["lng"], 3)
                if inc["kind"] == "help": inc["photo"] = None
            out.append(inc)
        out.sort(key=lambda i: (-i["priority_score"], i["updated_min_ago"]))
        return out

    def report_fields(trend, rising, car, cm):
        """Validate the extra report fields; trend and the legacy rising flag are kept consistent."""
        trend = (trend or "").strip() or None; rising = (rising or "").strip() or None; car = (car or "").strip() or None
        if trend is not None and trend not in assess.TRENDS: raise HTTPException(422, f"trend must be one of {list(assess.TRENDS)}")
        if rising is not None and rising not in ("yes", "no", "unsure"): rising = None
        if car is not None and car not in assess.PASSABLE: raise HTTPException(422, "car_passable must be yes, no or unsure")
        if trend: rising = assess.TREND_TO_RISING[trend]
        elif rising: trend = assess.RISING_TO_TREND.get(rising)
        val = None
        if cm not in (None, ""):
            try: val = int(float(cm))
            except (TypeError, ValueError): raise HTTPException(422, "reported_depth_cm must be a number")
            if not 0 <= val <= 300: raise HTTPException(422, "reported_depth_cm must be 0-300")
        return trend, rising, car, val

    def client_key(cid):
        """Anonymous per-browser id, hashed so the stored value can't be linked back to the raw id."""
        import hashlib
        cid = (cid or "").strip()[:64]
        return hashlib.sha256(("bb:" + cid).encode()).hexdigest()[:16] if cid else None

    def covered(label):
        r = geo.resolve(label); return bool(r and r["covered"])

    def place(label, lat=None, lng=None):
        """Canonical barangay label + PSGC code; falls back to the PSGC centroid (approximate) when no point given."""
        r = geo.resolve(label)
        if not r: return label.strip(), None, lat, lng, None
        if (lat is None or lng is None) and r["lat"] is not None: return r["label"], r["code"], r["lat"], r["lng"], "barangay"
        return r["label"], r["code"], lat, lng, None

    @app.get("/api/cells")
    def cell_map(barangay: str | None = None, view: str = "public"):
        if view not in ("public", "responder"): raise HTTPException(422, "view must be public or responder")
        reps = all_reports(); groups = assess.group(reps); votes = side("votes"); reviews = side("reviews")
        vbr = {root: {k: sum(v["vote"] == k for v in vs) for k in ("still", "clear", "unsure", "gone")} for root, vs in votes.items()}
        confirmed = {r["id"] for root, rs in groups.items() if (reviews.get(root) or [{}])[-1].get("action") == "confirm" for r in rs}
        rejected = {r["id"] for root, rs in groups.items() if (reviews.get(root) or [{}])[-1].get("action") == "reject" for r in rs}
        reps = [r for r in reps if r["id"] not in rejected]
        out = cells.build(reps, now(), vbr, confirmed, responder=(view == "responder"))
        if barangay: out = [c for c in out if barangay in c["barangays"]]
        return {"cell_m": cells.CELL_M, "half_life_min": cells.HALF_LIFE_MIN, "expire_h": cells.EXPIRE_H, "cells": out}

    @app.get("/api/barangays/search")
    def barangay_search(q: str = "", limit: int = 8):
        if len(q.strip()) < 2: return []
        return geo.search(q, max(1, min(limit, 20)))

    @app.get("/api/barangays/find")
    def barangay_find(q: str = "", limit: int = 20):
        """Search with total count, for the autocomplete UI ('20 of 143 matches')."""
        if len(q.strip()) < 2: return {"q": q, "total": 0, "items": []}
        total, items = geo.search_full(q, max(1, min(limit, 20)))
        return {"q": q, "total": total, "items": items}

    @app.get("/api/barangays/nearest")
    def barangay_nearest(lat: float, lng: float):
        if not (-90 <= lat <= 90 and -180 <= lng <= 180): raise HTTPException(422, "invalid coordinates")
        return geo.nearest(lat, lng, 3)

    @app.get("/api/barangays/resolve")
    def barangay_resolve(label: str):
        r = geo.resolve(label)
        if not r: raise HTTPException(404, "unknown barangay")
        return geo.public(r)

    def finalize(rid):
        rec = get(rid)
        res = triage(rec)
        dup = res["duplicate_of"] or assess.cluster_root(rec, all_reports())
        risk = res["people_at_risk"] or bool((rec.get("assessment") or {}).get("people_at_risk"))
        status = "needs_info" if res["followup"] else ("duplicate" if dup else "ok")
        conn.execute("UPDATE reports SET people_at_risk=?, duplicate_of=?, question=?, status=? WHERE id=?",
                     (int(risk), dup, res["followup"], status, rid)); conn.commit()
        out = get(rid); out["agent_trace"] = res["trace"]
        root = next((k for k, rs in assess.group(all_reports()).items() if any(r["id"] == rid for r in rs)), rid)
        out["incident"] = next((i for i in build_incidents("public", include_inactive=True) if i["id"] == root), None)
        return out

    def get(rid):
        r = conn.execute("SELECT * FROM reports WHERE id=?", (rid,)).fetchone()
        if not r: raise HTTPException(404, "report not found")
        return db.row(r)

    def triage(rec):
        try:
            res = agent.run(rec, Tools(all_reports()))
        except NotImplementedError as e:
            raise HTTPException(501, str(e))
        return res

    @app.get("/api/health")
    def health():
        from .providers import meta as m
        live = vision.name == "meta"
        return {"ok": True, "provider": vision.name,
                "models": {"vision": m.SAM_MODEL, "text": m.MUSE_MODEL} if live else None,
                "key_present": bool(m._api_key()) if live else False,
                "fallback_enabled": m._fallback_enabled() if live else None,
                "fallbacks": dict(m.FALLBACKS) if live else None}

    @app.post("/api/reports", status_code=201)
    async def create_report(photo: UploadFile = File(...), lat: float = Form(...), lng: float = Form(...),
                            barangay: str = Form(...), street: str = Form(...), note: str = Form(""),
                            lang: str = Form(""), water_level: str = Form(""), rising: str = Form(""),
                            loc_source: str = Form("map"), draft: bool = Form(False),
                            client_id: str = Form(""), trend: str = Form(""), car_passable: str = Form(""),
                            reported_depth_cm: str = Form("")):
        trend, rising, car_passable, rep_cm = report_fields(trend, rising, car_passable, reported_depth_cm)
        if not (-90 <= lat <= 90 and -180 <= lng <= 180):
            raise HTTPException(422, "invalid coordinates")
        if not barangay.strip() or not street.strip():
            raise HTTPException(422, "barangay and street are required")
        data = await photo.read()
        if not data or len(data) > MAX_BYTES:
            raise HTTPException(413 if data else 422, "photo missing or too large")
        t0 = time.time()
        try:
            seg = vision.segment(data, depth.PROMPTS)
        except NotImplementedError as e:
            raise HTTPException(501, str(e))
        est = depth.estimate(seg)
        est["masks"] = [{"label": m.label, "bbox": m.bbox, "score": round(m.score, 2)} for m in seg.masks]
        t_vis = time.time()
        ext = reporter.extract(note, est)
        name = f"{int(time.time())}-{uuid.uuid4().hex[:8]}.jpg"
        (UPLOADS / name).write_bytes(data)
        bname, code, _, _, _ = place(barangay)
        rec = {**est, "reported_at": now().isoformat(timespec="seconds"), "lat": lat, "lng": lng,
               "barangay": bname, "psgc_code": code, "client_id": client_key(client_id), "street": street.strip(), "note": note,
               "lang": lang if lang in ("fil", "en") else detect_lang(note), "image_path": f"/uploads/{name}",
               "provider": seg.source or vision.name, "water_level": water_level if water_level in assess.LEVELS else None,
               "rising": rising, "trend": trend, "car_passable": car_passable, "reported_depth_cm": rep_cm, "kind": "flood",
               "loc_source": loc_source if loc_source in ("gps", "map", "barangay") else "map",
               "assessment": ext, "status": "draft"}
        rid = db.insert(conn, rec)
        timing = {"vision_ms": int((t_vis - t0) * 1000), "text_ms": int((time.time() - t_vis) * 1000)}
        if draft:
            out = get(rid)
            out["understood"] = understood(out); out["timing"] = timing; return out
        out = finalize(rid); out["timing"] = timing; return out

    def understood(r):
        lvl, src = assess.report_level(r)
        a = r.get("assessment") or {}
        return {"street": r["street"], "barangay": r["barangay"], "covered": covered(r["barangay"]), "approximate": r.get("loc_source") == "barangay",
                "level": lvl, "level_source": src, "photo_level": assess.BAND_TO_LEVEL.get(r["band"]) if r["band"] != "cant_tell" else None,
                "reporter_level": r.get("water_level"), "rising": r.get("rising") or a.get("rising"),
                "trend": r.get("trend"), "car_passable": r.get("car_passable"), "reported_depth_cm": r.get("reported_depth_cm"),
                "hazards": [assess.HAZARD_LABEL[h] for h in a.get("hazards", [])], "people_at_risk": bool(a.get("people_at_risk")),
                "summary": a.get("summary_en"), "vision_provider": r.get("provider"), "text_provider": a.get("source"),
                "confidence": r.get("confidence")}

    @app.post("/api/reports/{rid}/publish")
    def publish(rid: int, p: Publish):
        r = conn.execute("SELECT * FROM reports WHERE id=?", (rid,)).fetchone()
        if not r: raise HTTPException(404, "report not found")
        if r["status"] != "draft": raise HTTPException(409, "already published")
        if p.water_level is not None and p.water_level not in assess.LEVELS: raise HTTPException(422, "bad water_level")
        if p.water_level: conn.execute("UPDATE reports SET water_level=? WHERE id=?", (p.water_level, rid))
        if p.trend or p.rising or p.car_passable or p.reported_depth_cm is not None:
            t, ri, car, cm = report_fields(p.trend or "", p.rising or "", p.car_passable or "", p.reported_depth_cm)
            if t or ri: conn.execute("UPDATE reports SET trend=?, rising=? WHERE id=?", (t, ri, rid))
            if car: conn.execute("UPDATE reports SET car_passable=? WHERE id=?", (car, rid))
            if cm is not None: conn.execute("UPDATE reports SET reported_depth_cm=? WHERE id=?", (cm, rid))
        if p.street and p.street.strip(): conn.execute("UPDATE reports SET street=? WHERE id=?", (p.street.strip(), rid))
        conn.execute("UPDATE reports SET status='ok', reported_at=? WHERE id=?", (now().isoformat(timespec="seconds"), rid)); conn.commit()
        return finalize(rid)

    @app.post("/api/help", status_code=201)
    def help_request(h: HelpRequest):
        if not h.barangay.strip() or not h.street.strip(): raise HTTPException(422, "barangay and street are required")
        if len(h.note) > 500: raise HTTPException(422, "note too long")
        bname, code, lat, lng, approx = place(h.barangay, h.lat, h.lng)
        known = [r for r in all_reports() if r["barangay"] == bname]
        src = approx or "gps"
        if lat is None or lng is None:  # never invent a point: use barangay centroid and mark approximate
            if not known: raise HTTPException(422, "location needed for a new barangay")
            lat = sum(r["lat"] for r in known) / len(known); lng = sum(r["lng"] for r in known) / len(known); src = "barangay"
        ext = reporter.extract(h.note, {})
        rec = {"reported_at": now().isoformat(timespec="seconds"), "lat": lat, "lng": lng, "barangay": bname, "psgc_code": code, "client_id": client_key(h.client_id),
               "street": h.street.strip(), "note": h.note, "lang": detect_lang(h.note), "depth_cm": None, "band": "cant_tell",
               "confidence": None, "people_at_risk": True, "kind": "help", "status": "help", "provider": "resident",
               "loc_source": src, "assessment": {**ext, "people_at_risk": True}}
        rid = db.insert(conn, rec)
        return {"id": rid, "incident": next(i for i in build_incidents("responder") if i["id"] == rid)}

    @app.get("/api/incidents")
    def incidents(view: str = "public", barangay: str | None = None):
        if view not in ("public", "responder"): raise HTTPException(422, "view must be public or responder")
        return build_incidents(view, barangay)

    def incident_or_404(iid):
        if iid not in assess.group(all_reports()):
            raise HTTPException(404, "incident not found")

    @app.post("/api/incidents/{iid}/vote")
    def vote(iid: int, v: Vote):
        incident_or_404(iid)
        if v.vote not in ("still", "clear", "unsure", "gone"): raise HTTPException(422, "vote must be still, clear, unsure or gone")
        conn.execute("INSERT INTO votes(incident_id,vote,at) VALUES(?,?,?)", (iid, v.vote, now().isoformat(timespec="seconds"))); conn.commit()
        return next(i for i in build_incidents("public", include_inactive=True) if i["id"] == iid)

    @app.post("/api/incidents/{iid}/review")
    def review(iid: int, rv: Review):
        incident_or_404(iid)
        if rv.action not in ("confirm", "reject", "request_info", "escalate"): raise HTTPException(422, "bad action")
        cur = next(i for i in build_incidents("responder", include_inactive=True) if i["id"] == iid)
        if rv.action == "escalate" and cur["confidence"] is None:   # safety rule 3
            raise HTTPException(409, "cannot escalate without a confidence value; request more info first")
        conn.execute("INSERT INTO reviews(incident_id,action,note,at) VALUES(?,?,?,?)",
                     (iid, rv.action, rv.note[:300], now().isoformat(timespec="seconds"))); conn.commit()
        return next(i for i in build_incidents("responder", include_inactive=True) if i["id"] == iid)

    @app.get("/api/area/{barangay}")
    def area(barangay: str):
        return {"barangay": barangay, **assess.area_status(build_incidents("public", barangay))}

    @app.get("/api/advisory/{barangay}")
    def advisory(barangay: str):
        facts = assess.advisory_facts(barangay, build_incidents("public", barangay))
        return {"barangay": barangay, "facts": facts, **reporter.advisory(facts)}

    @app.post("/api/reports/{rid}/answer")
    def answer(rid: int, a: Answer):
        r = get(rid)
        if r["status"] != "needs_info":
            raise HTTPException(409, "report does not need info")
        try:
            est = depth.from_answer(a.reference, a.submerged_pct)
        except ValueError:
            raise HTTPException(422, f"reference must be one of {list(depth.REF_HEIGHT_CM)} and 0<=submerged_pct<=100")
        conn.execute("UPDATE reports SET depth_cm=?,band=?,confidence=?,reference=?,reason=?,status='ok',question=NULL WHERE id=?",
                     (est["depth_cm"], est["band"], est["confidence"], est["reference"], est["reason"], rid))
        conn.commit(); return get(rid)

    @app.get("/api/reports")
    def list_reports(barangay: str | None = None, status: str | None = None):
        return [{k: v for k, v in r.items() if k != "client_id"} for r in all_reports()
                if (not barangay or r["barangay"] == barangay) and (not status or r["status"] == status)]

    @app.get("/api/reports/{rid}/nearby")
    def nearby(rid: int, radius_m: float = 100):
        return Tools(all_reports()).get_nearby_reports(get(rid), radius_m)

    @app.get("/api/barangays")
    def barangays():
        return sorted({r["barangay"] for r in all_reports()})

    @app.get("/api/summary/{barangay}")
    def summary(barangay: str):
        return summarize(all_reports(), barangay)

    @app.get("/api/sitrep/{barangay}")
    def sitrep(barangay: str):
        s = summarize(all_reports(), barangay)
        if not s["streets"]:
            raise HTTPException(404, "no reports for barangay")
        try:
            return {"barangay": barangay, "provider": reporter.name,
                    "en": reporter.situation_report(s, "en"), "fil": reporter.situation_report(s, "fil"), "summary": s}
        except NotImplementedError as e:
            raise HTTPException(501, str(e))

    @app.post("/api/ask")
    def ask(q: Question):
        text = q.question.strip()
        if not text or len(text) > 300:
            raise HTTPException(422, "question must be 1-300 characters")
        s = summarize(all_reports(), q.barangay)
        lang = q.lang if q.lang in ("fil", "en") else detect_lang(text)
        return {"barangay": q.barangay, "question": text, "lang": lang, **reporter.answer(s, text, lang)}

    app.mount("/uploads", StaticFiles(directory=UPLOADS), name="uploads")
    app.mount("/samples", StaticFiles(directory=ROOT / "sample_data" / "images"), name="samples")

    @app.get("/")
    def index():
        return FileResponse(ROOT / "static" / "index.html")

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon():
        return FileResponse(ROOT / "static" / "favicon.svg", media_type="image/svg+xml")
    app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
    app.state.conn = conn
    return app


app = create_app()
