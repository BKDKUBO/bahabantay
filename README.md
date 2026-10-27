# BahaBantay 🌊 (scaffold, pre-hackathon)

Residents send flood photos with a location. A vision model segments the water and reference objects (people, doors, car tires, jeepneys, curbs) to estimate depth. A report agent writes street-by-street situation reports in **Filipino and English**, and a live map serves barangay disaster offices (BDRRMO).

> **Status:** runs fully offline with a **mock** provider. No Meta API calls, no credentials, no cloud resources. All 18 sample reports and the 25-item eval set are **SIMULATED** (Marikina area, placeholder images).

## Setup
```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python scripts/seed.py          # loads 18 SIMULATED reports (incl. time series) into data/bahabantay.db
.venv/bin/uvicorn app.main:app --port 8765
# open http://localhost:8765
.venv/bin/pytest -q                        # tests
.venv/bin/python scripts/eval_depth.py     # accuracy check -> docs/eval/results.md
```
Env vars: `BAHABANTAY_PROVIDER=mock|meta` (default mock), `BAHABANTAY_DB`, `BAHABANTAY_UPLOADS`,
`META_API_KEY` / `MODEL_API_KEY` (Meta Model API; never commit), `BAHABANTAY_META_FALLBACK=true|false` (default true — fall back to mock on Meta errors).
Optional project `.env` (gitignored) is loaded automatically.

To use Meta SAM 3.1 + Muse Spark:
```bash
export META_API_KEY="…"   # or MODEL_API_KEY
export BAHABANTAY_PROVIDER=meta
.venv/bin/uvicorn app.main:app --port 8765
# live SAM smoke: .venv/bin/python scripts/smoke_meta_sam.py
```

## Features
- **Photo → depth:** segment water + reference object (person, door, car tire, jeepney, curb) → depth in cm, level, confidence.
- **Can't tell instead of guessing:** no reference object or confidence < 0.55 → `cant_tell`, no depth.
- **Agent with tools** (`app/agent.py`, provider `run()`): `get_nearby_reports(radius)`, `merge_duplicates` (same street, ≤30 m, ≤20 min), `flag_people_at_risk`, `ask_followup`. A can't-tell photo gets a follow-up question in the reporter's language (Filipino/English, detected from the note), e.g. *"May pinto, kotse, gulong o tao ba sa litrato? Hanggang saan ang tubig dito?"* The report stays **needs info** until answered via `POST /api/reports/{id}/answer` `{reference, submerged_pct}`, which re-estimates depth. Questions show on the map popup and in a "Needs info" panel.
- **Rising / falling trend:** per street, readings in the last 6 h → least-squares slope in cm/hour; ±5 cm/h = steady. Arrows on the map, in the street table and in the sitrep.
- **Bilingual situation report** per barangay, with passability (all / trucks / boats), trend, people-at-risk and pending follow-ups.
- **Accuracy check:** `scripts/eval_depth.py` → mean absolute error, per-level accuracy, can't-tell rate.

## Accuracy check (SIMULATED data only)
`sample_data/eval/labeled_simulated.json` (made by `scripts/make_eval_set.py`) is 25 synthetic items with known depths. Current result: MAE 5.3 cm, level accuracy 71%, can't tell 16%. **These numbers only test the math. The set must be replaced by real flood photos with measured depths before any accuracy claim.** See `docs/eval/results.md`.

## Architecture
```
static/index.html  Leaflet map (markers colored by depth band), upload form, bilingual report view
app/main.py        FastAPI: POST/GET /api/reports, POST /api/reports/{id}/answer, GET /api/reports/{id}/nearby,
                   /api/barangays, /api/summary/{brgy}, /api/sitrep/{brgy}, /api/health
app/agent.py       agent tools, language detection, follow-up questions
app/depth.py       pipeline: provider.segment() -> waterline vs reference-object height -> depth cm, band, confidence
app/aggregate.py   per-street rollup (latest depth, trend cm/h, passability, people-at-risk)
app/db.py          SQLite storage
app/providers/     base.py (Vision/Report/Agent interfaces)  mock.py (deterministic)  meta.py (SAM 3.1 segment +
                   per-frame tracking, Muse Spark agent + sitrep; mock fallback on failure)
scripts/           seed.py, make_eval_set.py, eval_depth.py
```
Depth bands: can't tell (no reference / low confidence), none <3 cm, ankle <20, knee <55, waist <110, chest 110+. Passability: all <25 cm, trucks <60, boats 60+.

## Mock vs Meta provider
- **mock**: fake masks derived from a hash of the image bytes, so the same photo always gives the same depth. Reports come from fixed EN/FIL templates and say so. Default for pytest / offline demos.
- **meta**: `MetaVision.segment` calls SAM 3.1 (`sam-3.1` via `POST /v1/responses`, one noun phrase per request, image as data URL). `MetaVision.track_frames` segments each frame. `MetaAgent.run` asks Muse Spark (`muse-spark-1.3`) for a JSON tool plan then runs `Tools` methods. `MetaReports.situation_report` drafts a BDRRMO bulletin with Muse (no SIMULATED/MOCK wording). On API/network/parse failure (or missing key), falls back to mock when `BAHABANTAY_META_FALLBACK` is true (default). Keys from env / `.env` only — never committed.

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

## Judging criteria mapping
| Criterion | How BahaBantay answers it |
|---|---|
| **Impact** | ~20 typhoons/yr in PH; turns scattered "baha na dito!" posts into street-level depth, trend and passability for BDRRMOs; flags people at risk; Filipino-first. |
| **Meta tooling** | SAM 3.1 for water + reference-object segmentation and multi-frame tracking (trend); Muse Spark as the tool-calling agent (nearby, dedupe, risk, follow-up) and bilingual sitrep writer. |
| **Technical** | Clean provider interfaces, can't-tell instead of guessing, follow-up loop, least-squares trend, dedupe, eval harness with MAE / per-level accuracy / can't-tell rate, 18 tests. |
| **Demo** | Live map with colored dots and trend arrows, a follow-up question answered on screen, Filipino ↔ English sitrep toggle. |

## Demo script outline (≈3 min)
1. Problem: scattered "baha na dito!" posts; responders guess depth.
2. Resident uploads a flood photo; pin drops; masks + depth level + confidence.
3. Unclear photo → app answers "can't tell" and asks *"May pinto o kotse ba sa litrato?"*; resident answers → depth fills in.
4. Map: Bayabas St ↑ +24 cm/h (rising), Rodriguez Ave ↓ (falling); duplicate reports merged.
5. BDRRMO opens the Filipino sitrep, switches to English; people-at-risk flag and pending follow-ups.
6. Accuracy slide: eval method (real measured photos by then), MAE and can't-tell rate.
7. Close: impact, Meta models used, what's next.
