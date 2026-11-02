"""Incident assessment: text extraction, clustering, status ladder, priority and fixed safety rules.

Model output (Muse Spark extraction) is an input here, never the final word. Every label a
resident or responder sees is produced by the deterministic rules in this file:
  1. Never "Safe to pass" from a single photo/report: needs >=2 independent reports or community "clear" votes.
  2. Never invent an exact location: location text comes only from what the reporter typed; public views are rounded.
  3. Never escalate without a confidence value.
  4. Area "Danger" needs corroboration (community/responder) or people at risk.
  5. AI grouping alone never counts as verified.
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from .agent import meters, ts

LEVELS = ["none", "ankle", "knee", "waist", "higher"]
BAND_TO_LEVEL = {"none": "none", "ankle": "ankle", "knee": "knee", "waist": "waist", "chest": "higher"}
LEVEL_CM = {"none": 0, "ankle": 10, "knee": 40, "waist": 90, "higher": 130}
HAZARDS = {
    "stranded_person": ("stranded", "trapped", "naiipit", "na-trap", "hindi makalabas", "di makalabas", "saklolo",
                        "rescue", "nalulunod", "nasa bubong", "on the roof", "sa bubong"),
    "vulnerable_person": ("matanda", "elderly", "senior", "lola", "lolo", "bata", "child", "kids", "baby", "sanggol",
                          "buntis", "pregnant", "pwd", "wheelchair", "maysakit", "may sakit", "bedridden"),
    "live_wire": ("live wire", "kuryente", "nakuryente", "electric", "kable", "spark", "poste", "sparking"),
    "strong_current": ("strong current", "malakas ang agos", "rumaragasa", "agos", "current"),
    "vehicles_stuck": ("stalled", "stuck", "tirik", "hindi makadaan", "di makadaan", "can't pass", "cannot pass", "no vehicles"),
    "rising_fast": ("tumataas", "rising", "lumalalim", "pataas", "going up", "tumaas"),
}
HAZARD_LABEL = {"stranded_person": "Stranded person", "vulnerable_person": "Vulnerable person (elderly/child/PWD)",
                "live_wire": "Live wires / electricity", "strong_current": "Strong current",
                "vehicles_stuck": "Vehicles stuck", "rising_fast": "Water rising"}
HELP_WORDS = ("tulong", "help", "saklolo", "rescue")
LEVEL_WORDS = [("higher", ("dibdib", "chest", "leeg", "neck", "bubong", "roof", "lagpas tao", "lampas tao")),
               ("waist", ("baywang", "bewang", "waist", "balakang")),
               ("knee", ("tuhod", "knee")),
               ("ankle", ("bukung", "sakong", "ankle", "talampakan", "gutter")),
               ("none", ("tuyo", "dry", "walang baha", "no flood", "humupa na", "clear na"))]
NEGATIONS = ("hindi na", "no longer", "wala nang", "wala ng")
ACTIONS = ["Safe to pass", "Use caution", "Avoid this area", "Needs confirmation", "Help may be needed"]
SEVERITY_RANK = {"unknown": 0, "low": 1, "moderate": 2, "high": 3, "critical": 4}
ACTIVE_H = 12
DUP_RADIUS_M, DUP_WINDOW_MIN = 60, 45
INCIDENT_GAP_MIN = 90
MIN_CONF = 0.55


def norm_street(s: str) -> str:
    s = (s or "").lower().replace(".", " ").replace(",", " ")
    for a, b in ((" street", " st"), (" avenue", " ave"), (" road", " rd")):
        s = s.replace(a, b)
    return " ".join(s.split())


# ---------- text extraction (mock / fallback; Muse Spark output goes through clean_extraction)
def extract_text(note: str | None) -> dict:
    n = f" {(note or '').lower()} "
    hz = [k for k, words in HAZARDS.items() if any(w in n for w in words)]
    if "rising_fast" in hz and any(x in n for x in NEGATIONS):
        hz.remove("rising_fast")
    level = next((lv for lv, words in LEVEL_WORDS if any(w in n for w in words)), None)
    rising = "yes" if "rising_fast" in hz else ("no" if any(w in n for w in ("bumababa", "going down", "humuhupa", "receding", "same level", "hindi gumagalaw")) else None)
    people = bool({"stranded_person", "vulnerable_person"} & set(hz)) or any(w in n for w in HELP_WORDS)
    return {"hazards": hz, "people_at_risk": people, "water_level": level, "rising": rising,
            "summary_en": None, "confidence": 0.6 if (hz or level) else 0.3}


def clean_extraction(j: dict) -> dict:
    """Clamp a model's JSON to the allowed schema. Unknown hazards/levels are dropped, not guessed."""
    hz = [h for h in (j.get("hazards") or []) if h in HAZARDS]
    lvl = j.get("water_level") if j.get("water_level") in LEVELS else None
    rising = j.get("rising") if j.get("rising") in ("yes", "no") else None
    try:
        conf = max(0.0, min(1.0, float(j.get("confidence"))))
    except (TypeError, ValueError):
        conf = None
    s = j.get("summary_en"); s = str(s)[:140] if s else None
    return {"hazards": list(dict.fromkeys(hz)), "people_at_risk": bool(j.get("people_at_risk")), "water_level": lvl,
            "rising": rising, "summary_en": s, "confidence": conf}


# ---------- per-report level
def report_level(r: dict) -> tuple[str | None, str | None]:
    """(level, source). Photo estimate wins when confident; else reporter's tap; else note text."""
    if r.get("band") and r["band"] != "cant_tell" and (r.get("confidence") or 0) >= MIN_CONF:
        return BAND_TO_LEVEL.get(r["band"]), "ai_detected"
    if r.get("water_level") in LEVELS:
        return r["water_level"], "user_reported"
    lv = (r.get("assessment") or {}).get("water_level")
    return (lv, "user_reported") if lv in LEVELS else (None, None)


def severity(level: str | None, hazards: list[str], people: bool) -> str:
    rank = LEVELS.index(level) if level in LEVELS else None
    hz = set(hazards)
    if people and (rank is None or rank >= 2):
        return "critical"
    if "live_wire" in hz and (rank or 0) >= 1 or "strong_current" in hz and (rank or 0) >= 2:
        return "critical"
    if rank is None:
        return "moderate" if hz - {"rising_fast"} else "unknown"
    if rank >= 3:
        return "high"
    if rank == 2 or hz:
        return "moderate"
    return "low"


# ---------- clustering
def cluster_root(report: dict, others: list[dict]) -> int | None:
    """Earliest active report in the same barangay, same street (or within DUP_RADIUS_M), within DUP_WINDOW_MIN."""
    if report.get("kind") == "help":
        return None
    c = [o for o in others if o["id"] != report.get("id") and not o.get("duplicate_of") and o.get("kind", "flood") != "help"
         and o["barangay"] == report["barangay"]
         and (norm_street(o["street"]) == norm_street(report["street"]) or meters(o, report) <= DUP_RADIUS_M)
         and abs((ts(o) - ts(report)).total_seconds()) <= DUP_WINDOW_MIN * 60]
    return min(c, key=ts)["id"] if c else None


def group(reports: list[dict]) -> dict[int, list[dict]]:
    """incident id (earliest member) -> reports, time-ordered.

    Exact duplicates follow duplicate_of. Other reports join an open incident on the same barangay +
    street (or within DUP_RADIUS_M) when they arrive within INCIDENT_GAP_MIN of its latest report,
    so a rising time series on one street is one incident whose confidence grows.
    """
    by_id = {r["id"]: r for r in reports}
    home: dict[int, int] = {}
    out: dict[int, list[dict]] = {}
    for r in sorted(reports, key=lambda r: (ts(r), r["id"])):
        d = r.get("duplicate_of")
        if d in home:
            iid = home[d]
        else:
            iid = None
            if r.get("kind") != "help":
                for k, rs in out.items():
                    h, last = rs[0], rs[-1]
                    if h.get("kind") == "help" or h["barangay"] != r["barangay"]: continue
                    if not (norm_street(h["street"]) == norm_street(r["street"]) or meters(last, r) <= DUP_RADIUS_M): continue
                    if (ts(r) - ts(last)).total_seconds() <= INCIDENT_GAP_MIN * 60:
                        iid = k; break
            if iid is None:
                iid = r["id"]
        home[r["id"]] = iid
        out.setdefault(iid, []).append(r)
    return out


# ---------- incident assessment (deterministic, runs after any model output)
def ladder(n_reports: int, votes: dict, reviews: list[dict]) -> str:
    last = reviews[-1]["action"] if reviews else None
    if last == "confirm":
        return "responder_verified"
    if votes.get("still", 0) >= 2 or votes.get("clear", 0) >= 2:
        return "community_corroborated"
    if n_reports >= 2:
        return "ai_grouped"
    return "user_reported"


def assess_incident(rs: list[dict], votes: dict, reviews: list[dict], now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    rs = sorted(rs, key=ts); latest = rs[-1]
    help_req = any(r.get("kind") == "help" for r in rs)
    hz: list[str] = []
    people = False
    for r in rs:
        a = r.get("assessment") or {}
        hz += a.get("hazards", []); people = people or bool(r.get("people_at_risk")) or bool(a.get("people_at_risk"))
    hz = list(dict.fromkeys(hz))
    lv_pairs = [report_level(r) for r in rs]
    lvl, lvl_src = lv_pairs[-1]
    if lvl is None:
        lvl, lvl_src = next(((l, s) for l, s in reversed(lv_pairs) if l), (None, None))
    rising = any(r.get("rising") == "yes" or (r.get("assessment") or {}).get("rising") == "yes" for r in rs) or "rising_fast" in hz
    sev = "critical" if help_req else severity(lvl, hz, people)
    lad = ladder(len(rs), votes, reviews)
    last_action = reviews[-1]["action"] if reviews else None
    # confidence
    photo_conf = [r["confidence"] for r in rs if r.get("band") not in (None, "cant_tell") and r.get("confidence")]
    if photo_conf:
        conf = max(photo_conf)
    elif lvl is not None:
        conf = 0.6   # reporter tapped a level / described it; photo gave no usable estimate
    elif help_req:
        conf = 0.5
    else:
        conf = None
    if conf is not None:
        conf += 0.1 * min(3, len(rs) - 1) + 0.05 * votes.get("still", 0) - 0.1 * votes.get("clear", 0)
        if lad == "responder_verified": conf = max(conf, 0.95)
        conf = round(max(0.05, min(0.95 if lad != "responder_verified" else 0.99, conf)), 2)
    # action label (resident-facing)
    clear, still = votes.get("clear", 0), votes.get("still", 0)
    if last_action == "reject":
        action = "Needs confirmation"
    elif help_req or people:
        action = "Help may be needed"
    elif {"live_wire", "strong_current"} & set(hz):   # electrical/current hazard: avoid even before depth is confirmed
        action = "Avoid this area"
    elif conf is None or conf < MIN_CONF or lvl is None:
        action = "Needs confirmation"
    elif clear >= 2 and clear > still:
        action = "Safe to pass" if lvl in ("none", "ankle") or lad == "responder_verified" else "Needs confirmation"
    elif LEVELS.index(lvl) >= 2 or {"live_wire", "strong_current", "stranded_person"} & set(hz):
        action = "Avoid this area"
    elif lvl == "ankle":
        action = "Use caution"
    else:  # "none": Rule 1, never Safe from a single report
        action = "Safe to pass" if (len(rs) >= 2 or clear >= 2) else "Needs confirmation"
    # priority tier for responders
    reasons = []
    if help_req: reasons.append("help request from resident")
    if people: reasons.append("people may be at risk")
    for h in hz:
        if h in ("live_wire", "strong_current", "stranded_person"): reasons.append(HAZARD_LABEL[h].lower())
    if lvl in ("knee", "waist", "higher"): reasons.append(f"{lvl}-deep water")
    if rising: reasons.append("water rising")
    if len(rs) > 1: reasons.append(f"{len(rs)} reports grouped")
    if last_action == "reject":
        tier = "monitor"; reasons = ["rejected by responder"]
    elif sev == "critical" and lad != "responder_verified" and conf is None:
        tier = "needs_verification"; reasons.append("no confidence yet")
    elif sev == "critical" or last_action == "escalate":
        tier = "critical"
    elif action == "Needs confirmation" or (sev == "high" and lad in ("user_reported", "ai_grouped")):
        tier = "needs_verification"
        if lvl is None: reasons.append("depth unknown")
        elif lad in ("user_reported", "ai_grouped"): reasons.append("not yet corroborated")
    else:
        tier = "monitor"
    score = SEVERITY_RANK[sev] * 20 + (10 if rising else 0) + min(3, len(rs) - 1) * 3 + (15 if help_req else 0) + still * 2
    age_min = int((now - ts(latest)).total_seconds() // 60)
    return {"severity": sev, "action_label": action, "level": lvl, "level_source": lvl_src, "hazards": hz,
            "people_at_risk": people or help_req, "rising": rising, "confidence": conf, "ladder": lad,
            "needs_human_verification": lad != "responder_verified", "tier": tier, "priority_score": score,
            "priority_reason": "; ".join(dict.fromkeys(reasons)) or "low depth, no hazards reported",
            "updated_min_ago": age_min, "active": age_min <= ACTIVE_H * 60 and last_action != "reject"}


def evidence(rs, votes_rows, reviews):
    ev = []
    for r in rs:
        who = "Sample report" if r.get("simulated") else ("Help request" if r.get("kind") == "help" else "Resident report")
        bits = [f"{who} #{r['id']}"]
        if r.get("water_level"): bits.append(f"reporter tapped '{r['water_level']}'")
        if r.get("note"): bits.append(f"note: “{r['note']}”")
        ev.append({"source": "user_reported", "at": r["reported_at"], "text": ", ".join(bits), "report_id": r["id"]})
        if r.get("band") and r["band"] != "cant_tell":
            prov = r.get("provider") or "?"
            label = {"meta": "SAM 3.1 photo depth", "mock-fallback": "Offline estimator (Meta unavailable)",
                     "sample": "Sample data (not analyzed live)", "mock": "Offline estimator"}.get(prov, prov)
            ev.append({"source": "ai_detected", "at": r["reported_at"], "report_id": r["id"],
                       "text": f"{label}: ~{r['depth_cm']} cm ({r['band']}) vs {r.get('reference') or 'reference'}, confidence {r.get('confidence')}"})
        a = r.get("assessment") or {}
        if a.get("hazards") or a.get("summary_en"):
            src = {"meta": "Muse Spark read the note", "mock-fallback": "Keyword rules (Meta unavailable)",
                   "mock": "Keyword rules", "sample": "Keyword rules (sample)"}.get(a.get("source"), "Note analysis")
            hz = ", ".join(HAZARD_LABEL[h] for h in a.get("hazards", []))
            ev.append({"source": "ai_detected", "at": r["reported_at"], "report_id": r["id"],
                       "text": f"{src}: {hz or 'no hazards'}{(' — ' + a['summary_en']) if a.get('summary_en') else ''}"})
    for v in votes_rows:
        ev.append({"source": "community_confirmed", "at": v["at"], "text": {"still": "Community: still flooded", "clear": "Community: already clear", "unsure": "Community: not sure"}[v["vote"]]})
    for rv in reviews:
        ev.append({"source": "responder", "at": rv["at"], "text": f"Responder: {rv['action'].replace('_', ' ')}{(' — ' + rv['note']) if rv.get('note') else ''}"})
    return sorted(ev, key=lambda e: e["at"])


def area_status(incidents: list[dict]) -> dict:
    act = [i for i in incidents if i["active"]]
    danger = [i for i in act if i["severity"] in ("critical", "high") and
              (i["people_at_risk"] or i["ladder"] in ("community_corroborated", "responder_verified"))]
    watch = [i for i in act if i["severity"] in ("moderate", "high", "critical") or i["action_label"] in ("Avoid this area", "Help may be needed")]
    status = "danger" if danger else ("watch" if watch else "safe")
    text = {"danger": "Danger: deep water with people possibly at risk, or confirmed deep flooding",
            "watch": "Watch: flood reports nearby, take care",
            "safe": "No recent serious reports"}[status]
    upd = min((i["updated_min_ago"] for i in act), default=None)
    return {"status": status, "text": text, "incidents": len(act), "reports": sum(i["reports"] for i in act),
            "updated_min_ago": upd, "danger_ids": [i["id"] for i in danger]}


# ---------- share / advisory
LEVEL_FIL = {"none": "walang baha", "ankle": "hanggang bukung-bukong", "knee": "hanggang tuhod", "waist": "hanggang baywang", "higher": "lampas baywang"}
ACTION_FIL = {"Safe to pass": "Madadaanan", "Use caution": "Mag-ingat", "Avoid this area": "Iwasan muna",
              "Needs confirmation": "Kailangan ng kumpirmasyon", "Help may be needed": "Maaaring may nangangailangan ng tulong"}


def share_text(inc: dict) -> str:
    lvl = inc.get("level")
    depth = f"{LEVEL_FIL[lvl]} / {lvl}-deep" if lvl else "di pa alam ang lalim / depth unknown"
    return (f"BahaBantay: {inc['street']}, Brgy {inc['barangay']}: {depth}. {ACTION_FIL[inc['action_label']]} / {inc['action_label']}. "
            f"{inc['reports']} ulat/reports, {inc['updated_min_ago']} min ago. Community report, not an official order.")


def advisory_facts(barangay: str, incidents: list[dict]) -> dict:
    act = [i for i in incidents if i["active"] and i["barangay"] == barangay]
    return {"barangay": barangay, "area": area_status(act),
            "incidents": [{k: i[k] for k in ("street", "level", "action_label", "severity", "rising", "people_at_risk", "reports", "ladder", "updated_min_ago")}
                          for i in sorted(act, key=lambda i: -i["priority_score"])[:8]]}


def advisory_template(facts: dict) -> dict:
    b, inc = facts["barangay"], facts["incidents"]
    avoid = [i["street"] for i in inc if i["action_label"] in ("Avoid this area", "Help may be needed")]
    caution = [i["street"] for i in inc if i["action_label"] == "Use caution"]
    rising = [i["street"] for i in inc if i["rising"]]
    help_ = [i["street"] for i in inc if i["people_at_risk"]]
    en = [f"Flood advisory for Barangay {b} ({facts['area']['text']})."]
    fil = [f"Abiso sa baha para sa Barangay {b}."]
    if avoid: en.append("Avoid: " + ", ".join(avoid) + "."); fil.append("Iwasan muna: " + ", ".join(avoid) + ".")
    if caution: en.append("Use caution: " + ", ".join(caution) + "."); fil.append("Mag-ingat sa: " + ", ".join(caution) + ".")
    if rising: en.append("Water reported rising on " + ", ".join(rising) + "."); fil.append("Tumataas ang tubig sa " + ", ".join(rising) + ".")
    if help_: en.append("Possible people needing help on " + ", ".join(help_) + "; responders are checking."); fil.append("May posibleng nangangailangan ng tulong sa " + ", ".join(help_) + "; sinusuri ng responders.")
    if not inc: en.append("No active community reports."); fil.append("Walang aktibong ulat mula sa komunidad.")
    en.append("Based on community reports. Follow official BDRRMO and PAGASA instructions.")
    fil.append("Batay sa ulat ng komunidad. Sundin ang opisyal na abiso ng BDRRMO at PAGASA.")
    sms = f"BahaBantay Brgy {b}: "
    sms += ("Iwasan/Avoid " + ", ".join(avoid[:3]) + ". ") if avoid else "Walang malalang ulat/No serious reports. "
    if rising: sms += "Tumataas/Rising: " + rising[0] + ". "
    sms += "Sundin BDRRMO."
    if len(sms) > 160: sms = sms[:157] + "..."
    return {"en": " ".join(en), "fil": " ".join(fil), "sms": sms}
