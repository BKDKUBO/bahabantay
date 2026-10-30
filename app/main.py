import json, os, time, uuid
from datetime import datetime, timezone
from pathlib import Path
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from . import db, depth
from .agent import Tools, detect_lang
from .aggregate import summarize
from .providers import get_providers

ROOT = Path(__file__).resolve().parent.parent
UPLOADS = Path(os.getenv("BAHABANTAY_UPLOADS", ROOT / "data" / "uploads"))
MAX_BYTES = 8 * 1024 * 1024


class Answer(BaseModel):
    reference: str          # person | door | car_tire | jeepney | curb
    submerged_pct: float    # how much of the object is under water, 0..100


def create_app(db_path=None, provider=None) -> FastAPI:
    app = FastAPI(title="BahaBantay", version="0.2.0")
    conn = db.connect(db_path)
    vision, reporter, agent = get_providers(provider)
    UPLOADS.mkdir(parents=True, exist_ok=True)

    def all_reports():
        return [db.row(r) for r in conn.execute("SELECT * FROM reports ORDER BY reported_at, id")]

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
        return {"ok": True, "provider": vision.name}

    @app.post("/api/reports", status_code=201)
    async def create_report(photo: UploadFile = File(...), lat: float = Form(...), lng: float = Form(...),
                            barangay: str = Form(...), street: str = Form(...), note: str = Form(""),
                            lang: str = Form("")):
        if not (-90 <= lat <= 90 and -180 <= lng <= 180):
            raise HTTPException(422, "invalid coordinates")
        data = await photo.read()
        if not data or len(data) > MAX_BYTES:
            raise HTTPException(413 if data else 422, "photo missing or too large")
        try:
            est = depth.run(data, vision)
        except NotImplementedError as e:
            raise HTTPException(501, str(e))
        name = f"{int(time.time())}-{uuid.uuid4().hex[:8]}.jpg"
        (UPLOADS / name).write_bytes(data)
        rec = {**est, "id": -1, "reported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "lat": lat, "lng": lng,
               "barangay": barangay.strip(), "street": street.strip(), "note": note,
               "lang": lang if lang in ("fil", "en") else detect_lang(note), "image_path": f"/uploads/{name}", "provider": vision.name}
        res = triage(rec)
        rec.update(people_at_risk=res["people_at_risk"], duplicate_of=res["duplicate_of"], question=res["followup"],
                   status="needs_info" if res["followup"] else ("duplicate" if res["duplicate_of"] else "ok"))
        rec.pop("id")
        out = get(db.insert(conn, rec)); out["agent_trace"] = res["trace"]; return out

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
        return [r for r in all_reports() if (not barangay or r["barangay"] == barangay) and (not status or r["status"] == status)]

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
