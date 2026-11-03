"""Street-scale affected area: reports snapped to ~250 m grid cells, with time decay and dedupe.

A barangay is an administrative label, not a flood footprint. The public map colors only the
cells that contain recent observations; it never shows a resident's exact point.

  weight      w = exp(-ln2 * age / HALF_LIFE)     (HALF_LIFE_MIN, default 60)
  expiry      reports older than EXPIRE_H hours (default 6) are ignored
  dedupe      reports from the same client id in the same cell count as ONE independent reporter
  confidence  1 - prod(1 - s_i) over independent reporters, s_i = best(w * evidence * location accuracy)
  state       observed (solid): recent, confidence >= OBSERVED_MIN, and confirmed
                                (>=2 independent reporters, a "still flooded" vote, or responder confirm)
              unconfirmed (hatched): recent but a single reporter / low confidence
              stale (gray): newest report older than RECENT_MIN, or very low confidence
Cells with no report are unknown, never "not flooded".
"""
from __future__ import annotations
import math, os
from datetime import datetime
from .agent import ts
from . import assess

CELL_M = float(os.getenv("BAHABANTAY_CELL_M", 250))
HALF_LIFE_MIN = float(os.getenv("BAHABANTAY_HALF_LIFE_MIN", 60))
EXPIRE_H = float(os.getenv("BAHABANTAY_EXPIRE_H", 6))
RECENT_MIN = float(os.getenv("BAHABANTAY_RECENT_MIN", 90))
OBSERVED_MIN = 0.5
STALE_CONF = 0.15
LOC_ACC = {"gps": 1.0, "map": 0.8, "barangay": 0.3}
LEVEL_ORDER = ["none", "ankle", "knee", "waist", "higher"]
DEG_M = 111_320.0


def cell_of(lat: float, lng: float) -> tuple[int, int]:
    dlat = CELL_M / DEG_M; row = math.floor(lat / dlat)
    dlng = CELL_M / (DEG_M * math.cos(math.radians((row + 0.5) * dlat)))
    return row, math.floor(lng / dlng)


def bounds(row: int, col: int) -> list[list[float]]:
    dlat = CELL_M / DEG_M
    dlng = CELL_M / (DEG_M * math.cos(math.radians((row + 0.5) * dlat)))
    return [[round(row * dlat, 6), round(col * dlng, 6)], [round((row + 1) * dlat, 6), round((col + 1) * dlng, 6)]]


def weight(age_min: float) -> float:
    if age_min > EXPIRE_H * 60: return 0.0
    return math.exp(-math.log(2) * max(0.0, age_min) / HALF_LIFE_MIN)


def evidence(r: dict) -> float:
    """0..1 quality of one report: confident photo > reporter's tap > note only."""
    lvl, src = assess.report_level(r)
    if src == "ai_detected": q = max(0.6, min(1.0, r.get("confidence") or 0.6))
    elif r.get("reported_depth_cm") is not None: q = 0.6
    elif lvl: q = 0.55
    else: q = 0.3
    if r.get("kind") == "help": q = max(q, 0.6)
    return q * LOC_ACC.get(r.get("loc_source") or "map", 0.8)


def reporter_key(r: dict) -> str:
    return f"c:{r['client_id']}" if r.get("client_id") else f"r:{r['id']}"


def build(reports: list[dict], now: datetime, votes_by_report: dict[int, dict] | None = None,
          confirmed_reports: set[int] | None = None, responder: bool = False) -> list[dict]:
    votes_by_report = votes_by_report or {}; confirmed_reports = confirmed_reports or set()
    cells: dict[tuple, list] = {}
    for r in reports:
        if r.get("status") == "draft": continue
        age = (now - ts(r)).total_seconds() / 60
        w = weight(age)
        if w <= 0: continue
        cells.setdefault(cell_of(r["lat"], r["lng"]), []).append((r, age, w))
    out = []
    for (row, col), items in cells.items():
        best: dict[str, float] = {}
        for r, age, w in items:
            k = reporter_key(r); best[k] = max(best.get(k, 0.0), w * evidence(r))
        conf = 1 - math.prod(1 - s for s in best.values())
        still = sum(votes_by_report.get(r["id"], {}).get("still", 0) for r, _, _ in items)
        gone = sum(votes_by_report.get(r["id"], {}).get("gone", 0) + votes_by_report.get(r["id"], {}).get("clear", 0) for r, _, _ in items)
        verified = any(r["id"] in confirmed_reports for r, _, _ in items)
        if still: conf = 1 - (1 - conf) * 0.7 ** min(still, 3)
        if verified: conf = max(conf, 0.9)
        newest = min(age for _, age, _ in items)
        # level: deepest among reports that still carry >=25% weight (<=2 half-lives), else the newest
        weighted = [(r, w) for r, _, w in items if w >= 0.25] or [min(items, key=lambda x: x[1])[:3:2]]
        lvls = [assess.report_level(r)[0] for r, _ in weighted]
        lvls = [l for l in lvls if l]
        level = max(lvls, key=LEVEL_ORDER.index) if lvls else None
        depths = [(r["depth_cm"] if r.get("depth_cm") is not None else r.get("reported_depth_cm"), w) for r, _, w in items]
        depths = [(d, w) for d, w in depths if d is not None]
        depth = round(sum(d * w for d, w in depths) / sum(w for _, w in depths)) if depths else None
        independent = len(best)
        confirmed = independent >= 2 or still > 0 or verified
        if newest > RECENT_MIN or conf < STALE_CONF: state = "stale"
        elif conf >= OBSERVED_MIN and confirmed: state = "observed"
        else: state = "unconfirmed"
        if gone >= 2 and gone > still: state, level = "stale", "none"
        car_no = any(r.get("car_passable") == "no" for r, age, _ in items if age <= RECENT_MIN)
        rising = [x for x in ((r.get("rising") or (r.get("assessment") or {}).get("rising")) for r, _, _ in items) if x]
        c = {"id": f"{row}:{col}", "bounds": bounds(row, col), "state": state, "confidence": round(conf, 2),
             "level": level, "depth_cm_weighted": depth, "reports": len(items), "independent_reporters": independent,
             "last_observed_min_ago": int(newest), "cars_cannot_pass": car_no, "people_at_risk": any(r.get("people_at_risk") or r.get("kind") == "help" for r, _, _ in items),
             "barangays": sorted({r["barangay"] for r, _, _ in items}), "sample": all(r.get("simulated") for r, _, _ in items),
             "streets": sorted({r["street"] for r, _, _ in items})[:4]}
        if responder:
            c["points"] = [{"id": r["id"], "lat": r["lat"], "lng": r["lng"], "loc_source": r.get("loc_source"),
                            "weight": round(w, 2)} for r, _, w in items]
        out.append(c)
    out.sort(key=lambda c: ({"observed": 0, "unconfirmed": 1, "stale": 2}[c["state"]], -c["confidence"]))
    return out
