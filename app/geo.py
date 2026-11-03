"""Nationwide barangay lookup (PSA PSGC, 42,010 barangays) with approximate centroids.

Data: app/geo/barangays.csv.gz, built from the MIT-licensed `psgc` package (v2026.4.13.0, PSA PSGC
Q1 2026 names/codes; coordinates are polygon centroids from HDX/OCHA COD-AB Nov 2023 shapefiles,
sourced from PSA/NAMRIA). See docs/data-sources.md. Centroids are approximate: a barangay
centroid is a label position, never a flood location.
The full list stays on the server; clients only ever get <=limit search hits.
"""
from __future__ import annotations
import csv, gzip, math, unicodedata
from functools import lru_cache
from pathlib import Path

DATA = Path(__file__).resolve().parent / "geo" / "barangays.csv.gz"
COVERED_CITIES = {"City of Marikina"}   # responder coverage for the demo


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    for ch in ",.()-'/": s = s.replace(ch, " ")
    return " ".join(w for w in s.split() if w not in ("brgy", "bgy", "barangay", "city", "of"))


def short_city(c: str) -> str:
    return c[8:] + " City" if c.startswith("City of ") else c


@lru_cache(maxsize=1)
def _load():
    rows = []
    with gzip.open(DATA, "rt", encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            prov = r["province"]
            prov = "Metro Manila" if prov.startswith("National Capital") else prov
            if prov.startswith("City of "): prov = ""   # independent cities: "Barangay 4-A, Davao City"
            covered = r["city"] in COVERED_CITIES
            label = r["name"] if covered else ", ".join(x for x in (r["name"], short_city(r["city"]), prov) if x)
            rows.append({"code": r["code"], "name": r["name"], "city": short_city(r["city"]), "province": prov,
                         "region": r["region"], "lat": float(r["lat"]) if r["lat"] else None,
                         "lng": float(r["lng"]) if r["lng"] else None, "approx": r["approx"] == "1",
                         "covered": covered, "label": label})
    seen = {}
    for r in rows:   # labels must be unique: append the PSGC code on the rare collision
        if r["label"] in seen: r["label"] += f" ({r['code']})"
        seen[r["label"]] = r
    keys = [(norm(r["name"]), norm(f"{r['name']} {r['city']} {r['province']}")) for r in rows]
    return rows, seen, keys


def all_rows(): return _load()[0]


def resolve(label: str) -> dict | None:
    """Exact label (as returned by search) or a PSGC code -> record."""
    rows, by_label, _ = _load(); label = (label or "").strip()
    if label in by_label: return by_label[label]
    if label.isdigit(): return next((r for r in rows if r["code"] == label), None)
    return None


def public(r: dict, dist_km: float | None = None) -> dict:
    out = {k: r[k] for k in ("code", "label", "name", "city", "province", "lat", "lng", "approx", "covered")}
    if dist_km is not None: out["distance_km"] = round(dist_km, 2)
    return out


def search(q: str, limit: int = 10) -> list[dict]:
    toks = norm(q).split()
    if not toks: return []
    rows, _, keys = _load(); hits = []
    for r, (nm, full) in zip(rows, keys):
        words = full.split()
        if all(any(w.startswith(t) for w in words) for t in toks):
            score = (0 if nm == " ".join(toks) else 1 if nm.startswith(toks[0]) else 2, not r["covered"], len(nm), r["label"])
            hits.append((score, r))
    hits.sort(key=lambda h: h[0])
    return [public(r) for _, r in hits[:limit]]


def km(a_lat, a_lng, b_lat, b_lng):
    p = math.pi / 180
    h = math.sin((b_lat - a_lat) * p / 2) ** 2 + math.cos(a_lat * p) * math.cos(b_lat * p) * math.sin((b_lng - a_lng) * p / 2) ** 2
    return 12742 * math.asin(math.sqrt(h))


def nearest(lat: float, lng: float, n: int = 3) -> list[dict]:
    """Nearest barangay centroids. Centroid distance, not point-in-polygon: a suggestion, the user confirms."""
    cand = []
    for r in all_rows():
        if r["lat"] is None or abs(r["lat"] - lat) > 0.3 or abs(r["lng"] - lng) > 0.3: continue
        cand.append((km(lat, lng, r["lat"], r["lng"]), r))
    cand.sort(key=lambda c: c[0])
    return [public(r, d) for d, r in cand[:n]]
