"""Responder Q&A over a barangay summary (e.g. "Saan pwedeng dumaan ang truck?").

Deterministic answers grounded only in `aggregate.summarize` output. The Meta
provider can phrase answers with Muse Spark, but must fall back to this.
"""
from __future__ import annotations

INTENTS = {  # checked in order; first match wins
    "risk": ("risk", "rescue", "stranded", "trapped", "tulong", "saklolo", "panganib", "naiipit", "rescue"),
    "boat": ("boat", "bangka", "rubber"),
    "truck": ("truck", "trak", "trucks", "fire truck", "ambulance", "ambulansya", "rescue vehicle"),
    "car": ("car", "kotse", "sasakyan", "vehicle", "jeep", "tricycle", "motor", "pass", "daan", "dumaan", "makakadaan"),
    "rising": ("rising", "worse", "tumataas", "lumalala", "trend", "falling", "bumababa"),
    "worst": ("worst", "deepest", "pinakamalalim", "pinakamataas", "malalim", "deep"),
}
OK_FOR = {"car": {"all"}, "truck": {"all", "trucks"}, "boat": {"boats"}}
T = {
    "en": {"none": "No usable reports for Barangay {b} yet.",
           "car": "Passable to all vehicles", "truck": "Passable to trucks", "boat": "Boats needed",
           "no_route": "No street with reports in {b} fits that right now.",
           "risk": "Possible people at risk", "no_risk": "No reports in {b} mention people at risk.",
           "rising": "Rising", "no_rising": "No street in {b} has a rising trend from the current reports.",
           "worst": "Deepest right now", "unknown": "I can only answer about passability (cars, trucks, boats), rising streets, the deepest street, or people at risk.",
           "pending": "{n} report(s) still waiting for reporter follow-up, so depth there is unknown.",
           "basis": "Based on {n} street(s) with reports; check on the ground before dispatch."},
    "fil": {"none": "Wala pang magagamit na ulat para sa Barangay {b}.",
            "car": "Madadaanan ng lahat ng sasakyan", "truck": "Madadaanan ng trak", "boat": "Bangka ang kailangan",
            "no_route": "Walang kalyeng may ulat sa {b} ang pasok diyan ngayon.",
            "risk": "May posibleng taong nangangailangan ng tulong", "no_risk": "Walang ulat sa {b} na may binanggit na taong nasa panganib.",
            "rising": "Tumataas", "no_rising": "Walang kalye sa {b} na tumataas ang tubig ayon sa mga ulat.",
            "worst": "Pinakamalalim ngayon", "unknown": "Masasagot ko lang ang tungkol sa madadaanan (kotse, trak, bangka), tumataas na kalye, pinakamalalim na kalye, o taong nasa panganib.",
            "pending": "{n} ulat ang naghihintay pa ng sagot mula sa nag-ulat, kaya hindi pa alam ang lalim doon.",
            "basis": "Batay sa {n} kalyeng may ulat; kumpirmahin muna sa lugar bago magpadala."},
}


def intent(question: str) -> str:
    q = f" {(question or '').lower()} "
    for name, words in INTENTS.items():
        if any(f" {w}" in q or f"{w} " in q for w in words):
            return name
    return "unknown"


def _line(s: dict) -> str:
    rate = f", {s['trend_arrow']} {s['rate_cm_per_h']:+} cm/h" if s.get("rate_cm_per_h") is not None and s.get("trend_arrow") else ""
    return f"{s['street']} (~{s['latest_depth_cm']} cm{rate})"


def answer(summary: dict, question: str, lang: str = "en") -> dict:
    lang = "fil" if lang == "fil" else "en"
    t, b, streets = T[lang], summary["barangay"], summary["streets"]
    kind = intent(question)
    if not streets:
        return {"intent": kind, "answer": t["none"].format(b=b), "streets": []}
    if kind in OK_FOR:
        hit = [s for s in streets if s["passability"] in OK_FOR[kind]]
        hit.sort(key=lambda s: s["latest_depth_cm"])
        text = f"{t[kind]}: " + "; ".join(_line(s) for s in hit) + "." if hit else t["no_route"].format(b=b)
    elif kind == "risk":
        hit = [s for s in streets if s.get("people_at_risk")]
        text = f"{t['risk']}: " + "; ".join(_line(s) for s in hit) + "." if hit else t["no_risk"].format(b=b)
    elif kind == "rising":
        hit = sorted((s for s in streets if s.get("trend") == "rising"), key=lambda s: -(s["rate_cm_per_h"] or 0))
        text = f"{t['rising']}: " + "; ".join(_line(s) for s in hit) + "." if hit else t["no_rising"].format(b=b)
    elif kind == "worst":
        hit = streets[:1]
        text = f"{t['worst']}: {_line(hit[0])}."
    else:
        hit, text = [], t["unknown"]
    extra = [t["pending"].format(n=summary["needs_info"])] if summary.get("needs_info") else []
    extra.append(t["basis"].format(n=len(streets)))
    return {"intent": kind, "answer": " ".join([text, *extra]), "streets": [s["street"] for s in hit]}
