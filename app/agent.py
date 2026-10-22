"""Tools the triage agent can call. Pure functions over stored reports."""
from __future__ import annotations
import math
from datetime import datetime

RISK_WORDS = ("stranded", "trapped", "naiipit", "tulong", "help", "matanda", "bata", "elderly", "child", "saklolo", "nalulunod")
FIL_WORDS = ("ang", "ng", "sa", "na", "po", "baha", "tulong", "dito", "bahay", "mga", "may", "wala", "naiipit", "hanggang")
DUP_RADIUS_M, DUP_WINDOW_MIN = 30, 20

QUESTIONS = {
    "no_reference": {"fil": "May pinto, kotse, gulong o tao ba sa litrato? Hanggang saan ang tubig dito?",
                     "en": "Is there a door, car, tire or person in the photo? How high is the water on it?"},
    "low_confidence": {"fil": "Hindi malinaw ang litrato. Ano ang nasa tubig (pinto, kotse, tao) at hanggang saan ang baha?",
                       "en": "The photo isn't clear. What object is in the water (door, car, person) and how high does it reach?"},
}


def detect_lang(note: str | None) -> str:
    words = (note or "").lower().split()
    return "fil" if sum(w.strip(".,!?") in FIL_WORDS for w in words) >= 1 else "en"


def meters(a, b) -> float:
    dlat = (a["lat"] - b["lat"]) * 111_320
    dlng = (a["lng"] - b["lng"]) * 111_320 * math.cos(math.radians(a["lat"]))
    return math.hypot(dlat, dlng)


def ts(r) -> datetime:
    return datetime.fromisoformat(r["reported_at"])


class Tools:
    def __init__(self, reports: list[dict]):
        self.reports = reports

    def get_nearby_reports(self, report, radius_m=100):
        return [r for r in self.reports if r["id"] != report["id"] and meters(r, report) <= radius_m]

    def merge_duplicates(self, report, nearby):
        """Earliest report within DUP_RADIUS_M and DUP_WINDOW_MIN on same street, else None."""
        c = [r for r in nearby if r["street"] == report["street"] and meters(r, report) <= DUP_RADIUS_M
             and abs((ts(r) - ts(report)).total_seconds()) <= DUP_WINDOW_MIN * 60 and not r.get("duplicate_of")]
        return min(c, key=ts)["id"] if c else None

    def flag_people_at_risk(self, report):
        n = (report.get("note") or "").lower()
        return any(w in n for w in RISK_WORDS)

    def ask_followup(self, report):
        lang = report.get("lang") or "en"
        return QUESTIONS.get(report.get("reason") or "no_reference", QUESTIONS["no_reference"])[lang]
