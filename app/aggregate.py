from datetime import datetime, timedelta
from .depth import band_for, passability
from .agent import RISK_WORDS, ts

TREND_WINDOW_H = 6
STEADY_CM_PER_H = 5
ARROWS = {"rising": "↑", "falling": "↓", "steady": "→", "unknown": ""}


def note_flags_risk(note):
    n = (note or "").lower(); return any(w in n for w in RISK_WORDS)


def trend(points: list[tuple[datetime, float]]) -> tuple[str, float | None]:
    """Least-squares slope (cm/hour) over readings; needs >=2 readings >=10 min apart."""
    if len(points) < 2: return "unknown", None
    t0 = points[0][0]; xs = [(t - t0).total_seconds() / 3600 for t, _ in points]; ys = [d for _, d in points]
    if xs[-1] - xs[0] < 1 / 6: return "unknown", None
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sum((x - mx) ** 2 for x in xs)
    slope = round(slope, 1)
    if abs(slope) < STEADY_CM_PER_H: return "steady", slope
    return ("rising" if slope > 0 else "falling"), slope


def summarize(reports: list[dict], barangay: str) -> dict:
    usable = [r for r in reports if r["barangay"] == barangay and r["depth_cm"] is not None and not r.get("duplicate_of")]
    pending = sum(1 for r in reports if r["barangay"] == barangay and r.get("status") == "needs_info")
    by_street: dict[str, list] = {}
    for r in usable: by_street.setdefault(r["street"], []).append(r)
    out = []
    for street, rs in by_street.items():
        rs.sort(key=ts); latest = rs[-1]
        window = [r for r in rs if ts(r) >= ts(latest) - timedelta(hours=TREND_WINDOW_H)]
        t, rate = trend([(ts(r), r["depth_cm"]) for r in window])
        d = latest["depth_cm"]
        out.append({"street": street, "reports": len(rs), "latest_depth_cm": d, "max_depth_cm": max(r["depth_cm"] for r in rs),
                    "max_band": band_for(d), "passability": passability(d), "trend": t, "rate_cm_per_h": rate,
                    "trend_arrow": ARROWS[t], "people_at_risk": any(r["people_at_risk"] for r in rs),
                    "lat": latest["lat"], "lng": latest["lng"], "latest_at": latest["reported_at"]})
    out.sort(key=lambda s: -s["latest_depth_cm"])
    return {"barangay": barangay, "streets": out, "needs_info": pending}
