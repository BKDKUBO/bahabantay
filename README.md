# BahaBantay 🌊

**Turns messy Filipino flood reports into a clear action for residents and a ranked, verified queue for barangay responders.**
Built for the Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026), using **Meta SAM 3.1** and **Muse Spark**.

Live demo: https://bahabantay-466317436519.asia-southeast1.run.app (append `#responder` for the responder view)

> The map starts with 18 **sample reports** (synthetic, Marikina area, placeholder images) so there is something to look at.
> Sample reports are not run through the models. Every photo you submit in the app *is* analyzed live by SAM 3.1 and
> Muse Spark; the header shows which provider is answering and says so if the offline fallback was used.

## The loop
**Report → AI understands → Resident confirms → Alert → Help**

1. **Resident ("Pulse") view**, mobile-first: area status *Safe / Watch / Danger* with report count and freshness,
   four big actions (*Report flood, Check my area, I need help, Help someone*), nearby incident cards, map below.
2. **Report flood**: photo → street/landmark (GPS, map tap, or "barangay area" marked approximate) → tap water level
   (Ankle/Knee/Waist/Higher) + *Is it rising?* + optional note (optional browser speech-to-text; that part is the browser, not Meta).
3. Progress screen while **SAM 3.1** segments the photo and **Muse Spark** reads the note.
4. **"AI understood" card**: what the photo said vs. what the reporter tapped, hazards found, with sources. The reporter
   can correct the level, then confirms. Nothing is published before that.
5. **Action card**: what we detected / what to do now / how to help, labeled *AI estimate, verify locally; not an official order*,
   plus a **Share alert** button (short Filipino-English text for Messenger/Facebook/SMS).
6. Neighbors tap **Still flooded / Already clear / Not sure** on each incident.
7. **I need help** sends a high-priority request straight into the responder queue (exact location shown to responders only).
8. **Responder view — Action Grid**: incidents ranked *Critical / Needs verification / Monitor* with the reason for the
   priority; evidence drawer (original reports and photos, AI detections, community votes, responder actions, timestamps,
   confidence, recommendation); **Confirm / Reject / Request more info / Escalate**; advisory generator (English, Filipino,
   ≤160-char SMS); Q&A (*"Saan pwedeng dumaan ang truck?"*).

## Where the Meta models are used
| Step | Model | Code |
|---|---|---|
| Segment water + reference objects (person, door, car tire, jeepney, curb) in each photo → depth in cm, level, confidence | **SAM 3.1** (`sam-3.1`, Responses API, one noun phrase per call) | `app/providers/meta.py` `MetaVision.segment`, `app/depth.py` |
| Read Filipino / English / Taglish notes into fixed fields: hazards, people at risk, water level, rising, short summary | **Muse Spark** (`muse-spark-1.3`) | `MetaReports.extract` |
| Triage plan: which agent tools to run (nearby reports, duplicate merge, people-at-risk, follow-up question) | Muse Spark | `MetaAgent.run`, `app/agent.py` |
| Barangay advisory in English + Filipino + SMS digest, from current incidents only | Muse Spark | `MetaReports.advisory` |
| Responder Q&A phrasing, grounded on a deterministic draft | Muse Spark | `MetaReports.answer`, `app/qa.py` |
| Bilingual situation report | Muse Spark | `MetaReports.situation_report` |

If a Meta call fails, the app falls back to a deterministic offline estimator (when `BAHABANTAY_META_FALLBACK=true`),
records it (`provider: "mock-fallback"` on the report, counter in `/api/health`) and shows it in the UI.

## Safety rules (run after the model, in `app/assess.py`)
The model proposes; fixed rules decide what people see:
- Never **Safe to pass** from a single photo/report: needs ≥2 reports or community "clear" votes.
- Never invent an exact location: location is only what the reporter gave; public views round to ~100 m; no pin = "approximate".
- Never escalate without a confidence value (`409` otherwise).
- Area **Danger** requires community/responder corroboration or people at risk.
- AI grouping alone is never "verified". Status ladder: *User reported → AI grouped → Community corroborated → Responder verified*.
- Live wires or strong current → *Avoid this area* even before depth is known. Can't-tell photos ask a follow-up question instead of guessing.
- Model JSON is clamped to the schema (unknown hazards/levels dropped).

## Architecture
```
static/index.html    Single page: resident Pulse view, report + help flows, responder Action Grid, Leaflet map
app/main.py          FastAPI routes (below)
app/assess.py        extraction schema, clustering into incidents, severity, action labels, ladder, priority, safety rules, advisory template
app/depth.py         segmentation → waterline vs reference-object height → depth cm, level, confidence (or "can't tell")
app/agent.py         agent tools: nearby reports, duplicate merge, people-at-risk, follow-up question; language detection
app/aggregate.py     per-street rollup: latest depth, least-squares trend (cm/h), passability
app/qa.py            grounded responder Q&A
app/db.py            SQLite (reports, votes, reviews)
app/providers/       base.py interfaces · meta.py (SAM 3.1 + Muse Spark, visible fallback) · mock.py (deterministic, offline)
scripts/             seed.py, eval_depth.py, eval_reports.py, make_eval_set.py, smoke_meta_sam.py
```
API: `GET /api/health` · `POST /api/reports` (multipart; `draft=true` for the confirm step) · `POST /api/reports/{id}/publish` ·
`POST /api/reports/{id}/answer` · `POST /api/help` · `GET /api/incidents?view=public|responder&barangay=` ·
`POST /api/incidents/{id}/vote` · `POST /api/incidents/{id}/review` · `GET /api/area/{brgy}` · `GET /api/advisory/{brgy}` ·
`GET /api/summary/{brgy}` · `GET /api/sitrep/{brgy}` · `POST /api/ask` · `GET /api/reports`, `/api/barangays`.

## Run it
```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m scripts.seed                 # 18 sample reports
.venv/bin/uvicorn app.main:app --port 8765       # http://localhost:8765  (offline estimator by default)
.venv/bin/pytest -q                              # 44 tests
```
Live Meta models: put `META_API_KEY=...` and `BAHABANTAY_PROVIDER=meta` in a local `.env` (gitignored) or the environment.
Other env vars: `BAHABANTAY_META_FALLBACK` (default true), `BAHABANTAY_DB`, `BAHABANTAY_UPLOADS`. Deploy notes: `docs/deploy.md`.

## Prototype evaluation (synthetic data only)
| Eval | Data | Result |
|---|---|---|
| Depth math (`scripts/eval_depth.py`) | 25 synthetic mask sets with known depths | MAE 5.3 cm, level accuracy 71%, can't-tell 16% |
| Report understanding (`scripts/eval_reports.py`), **Muse Spark** | 26 synthetic FIL/EN/Taglish text reports | water level 92%, people-at-risk 88%, hazards P/R 94%/94%, severity agreement 92%, critical recall 100%, ~5.7 s per report |
| Same, keyword rules (offline fallback) | same 26 | water level 96%, people-at-risk 100%, hazards P/R 100%/94%, severity 92% — **optimistic: the keyword list and the test set were written by the same team** |
| Incident grouping | same 26 | pairwise accuracy 100%, precision 100%, recall 92% |

These are prototype checks on data we wrote and labeled ourselves. They are not field accuracy. Details: `docs/eval/`.

## Honest limits
- No real flood photos with measured depths yet; depth accuracy on real photos is unmeasured.
- Sample reports are synthetic and use placeholder images.
- SQLite on one Cloud Run instance; submitted reports reset when the container restarts. No login: the responder view is open in the demo.
- Speech-to-text uses the browser's Web Speech API (not Meta) and only works in browsers that support it.
- Not an official warning system. Residents should follow BDRRMO, PAGASA and 911.
