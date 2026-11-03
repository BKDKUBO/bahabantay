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
PRIORITY_CITIES = {"Marikina City", "Quezon City"}   # ranked first on ties (demo area)


def short_region(r: str) -> str:
    """'Region XI (Davao Region)' -> 'Davao Region'; 'National Capital Region (NCR)' -> 'NCR'."""
    return r[r.rfind("(") + 1:-1] if r.endswith(")") and "(" in r else r


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
                         "region": short_region(r["region"]), "lat": float(r["lat"]) if r["lat"] else None,
                         "lng": float(r["lng"]) if r["lng"] else None, "approx": r["approx"] == "1",
                         "covered": covered, "label": label})
    seen = {}
    for r in rows:   # labels must be unique: append the PSGC code on the rare collision
        if r["label"] in seen: r["label"] += f" ({r['code']})"
        seen[r["label"]] = r
    keys = [(norm(r["name"]), norm(f"{r['city']} {r['province']} {r['region']}").split()) for r in rows]
    return rows, seen, keys


def all_rows(): return _load()[0]


def resolve(label: str) -> dict | None:
    """Exact label (as returned by search) or a PSGC code -> record."""
    rows, by_label, _ = _load(); label = (label or "").strip()
    if label in by_label: return by_label[label]
    if label.isdigit(): return next((r for r in rows if r["code"] == label), None)
    return None


def place_label(label: str) -> str:
    """'Malanday' -> 'Malanday, Marikina City'; adds the province outside Metro Manila. Unknown labels pass through."""
    r = resolve(label)
    if not r: return label or ""
    prov = r["province"] if r["province"] and r["province"] != "Metro Manila" else ""
    return ", ".join(x for x in (r["name"], r["city"], prov) if x)


def public(r: dict, dist_km: float | None = None) -> dict:
    out = {k: r[k] for k in ("code", "label", "name", "city", "province", "region", "lat", "lng", "approx", "covered")}
    out["place"] = place_label(r["label"])
    if dist_km is not None: out["distance_km"] = round(dist_km, 2)
    return out


def search_full(q: str, limit: int = 10) -> tuple[int, list[dict]]:
    """Token search. Every query token must prefix a word of the barangay name or of its
    city/province/region, so 'san isidro cebu' or 'poblacion, davao' narrow by place.
    Ranking: exact name match > name starts with query > other; then Marikina/QC; then
    more tokens on the name (fewer spent on place), exact place-word hits, shorter name.
    Returns (total matches, top `limit`)."""
    toks = norm(q).split()
    if not toks: return 0, []
    rows, _, keys = _load(); hits = []
    for r, (nm, loc) in zip(rows, keys):
        nw = nm.split(); name_t, loc_exact, ok, lead, cross = [], 0, True, True, False
        for t in toks:
            if lead and any(w.startswith(t) for w in nw): name_t.append(t); continue
            lead = False
            if any(w.startswith(t) for w in loc): loc_exact += t in loc
            elif any(w.startswith(t) for w in nw): name_t.append(t); cross = True
            else: ok = False; break
        if not ok or not name_t: continue          # at least one token must hit the barangay name
        nq = " ".join(name_t)
        tier = 0 if nm == nq else 1 if nm.startswith(nq) else 2
        # leading query tokens should name the barangay, trailing ones the place; a row whose
        # name is only hit by a trailing token (e.g. Brgy "Cebu" in San Isidro, Isabela) ranks last
        score = (cross or toks[0] not in name_t, tier, r["city"] not in PRIORITY_CITIES, -len(name_t), -loc_exact, len(nm), r["label"])
        hits.append((score, r))
    if any(not h[0][0] for h in hits):             # drop cross-matches when clean matches exist
        hits = [h for h in hits if not h[0][0]]
    hits.sort(key=lambda h: h[0])
    return len(hits), [public(r) for _, r in hits[:limit]]


def search(q: str, limit: int = 10) -> list[dict]:
    return search_full(q, limit)[1]


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
