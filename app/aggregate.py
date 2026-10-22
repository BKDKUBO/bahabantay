from .depth import band_for, passability

RISK_WORDS = ("stranded", "trapped", "naiipit", "tulong", "help", "matanda", "bata", "elderly", "child")


def note_flags_risk(note: str | None) -> bool:
    n = (note or "").lower()
    return any(w in n for w in RISK_WORDS)


def summarize(reports: list[dict], barangay: str) -> dict:
    streets: dict[str, dict] = {}
    for r in reports:
        if r["barangay"] != barangay or r["depth_cm"] is None:
            continue
        s = streets.setdefault(r["street"], {"street": r["street"], "reports": 0, "max_depth_cm": 0, "people_at_risk": False})
        s["reports"] += 1
        s["max_depth_cm"] = max(s["max_depth_cm"], r["depth_cm"])
        s["people_at_risk"] |= r["people_at_risk"]
    out = []
    for s in sorted(streets.values(), key=lambda s: -s["max_depth_cm"]):
        s["max_band"] = band_for(s["max_depth_cm"]); s["passability"] = passability(s["max_depth_cm"]); out.append(s)
    return {"barangay": barangay, "streets": out}
