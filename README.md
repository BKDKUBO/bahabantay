# BahaBantay 🌊 (scaffold, pre-hackathon)

Residents send flood photos with a location. A vision model segments the water and reference objects (people, doors, car tires, jeepneys, curbs) to estimate depth. A report agent writes street-by-street situation reports in **Filipino and English**, and a live map serves barangay disaster offices (BDRRMO).

> **Status:** runs fully offline with a **mock** provider. No Meta API calls, no credentials, no cloud resources. All 10 sample reports are **SIMULATED** (Marikina area, placeholder images).

## Setup
```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python scripts/seed.py          # loads 10 SIMULATED reports into data/bahabantay.db
.venv/bin/uvicorn app.main:app --port 8765
# open http://localhost:8765
.venv/bin/pytest -q                        # tests
```
Env vars: `BAHABANTAY_PROVIDER=mock|meta` (default mock), `BAHABANTAY_DB`, `BAHABANTAY_UPLOADS`.

## Architecture
```
static/index.html  Leaflet map (markers colored by depth band), upload form, bilingual report view
app/main.py        FastAPI: POST/GET /api/reports, /api/barangays, /api/summary/{brgy}, /api/sitrep/{brgy}, /api/health
app/depth.py       pipeline: provider.segment() -> waterline vs reference-object height -> depth cm, band, confidence
app/aggregate.py   per-street rollup (max depth, passability: all / trucks / boats, people-at-risk flag)
app/db.py          SQLite storage
app/providers/     base.py (interface)  mock.py (deterministic fake)  meta.py (stub, raises NotImplementedError)
```
Depth bands: none <3 cm, ankle <20, knee <55, waist <110, chest 110+. Passability: all <25 cm, trucks <60, boats 60+.

## Mock vs Meta provider
- **mock**: fake masks derived from a hash of the image bytes, so the same photo always gives the same depth. Reports come from fixed EN/FIL templates and say so.
- **meta**: `MetaVision.segment` (SAM 3.1) and `MetaReports.situation_report` (Muse Spark) raise `NotImplementedError` with TODOs. The API returns HTTP 501 if selected. Keys must come from env vars, never committed.

## 10-day build plan (Oct 26 – Nov 4, 2026)
| Day | Date | Work |
|---|---|---|
| 1 | Oct 26 | Kickoff; get Meta API access; wire SAM 3.1 call in `meta.py` on 3 test photos |
| 2 | Oct 27 | Real masks -> depth; mask overlay in UI; fall back to mock on error |
| 3 | Oct 28 | Calibrate reference heights on ~30 photos; confidence tuning |
| 4 | Oct 29 | Muse Spark sitrep (EN/FIL) from street summary JSON |
| 5 | Oct 30 | Agent tools: nearby_reports, flag_people_at_risk, dedupe |
| 6 | Oct 31 | Responder Q&A ("Saan pwedeng dumaan ang truck?"); hourly bulletin |
| 7 | Nov 1 | Mobile-first upload, GPS capture, image resize, rate limit |
| 8 | Nov 2 | Native Filipino review of templates/prompts; eval set; bug fixes |
| 9 | Nov 3 | Demo deploy (only after approval); record video |
| 10 | Nov 4 | Submission write-up, README polish; submit before 9 PM ET (Nov 5, 9 AM Manila) |

## Demo script outline (≈3 min)
1. Problem: scattered "baha na dito!" posts; responders guess depth.
2. Resident uploads a flood photo on a phone; pin drops on map.
3. Show masks (water + door/person) and estimated depth band with confidence.
4. Map fills with colored reports across Tumana / Malanday / Nangka.
5. BDRRMO opens the Filipino sitrep, switches to English; people-at-risk flag highlighted.
6. Ask a follow-up question to the agent (truck route).
7. Close: impact, Meta models used, what's next.
