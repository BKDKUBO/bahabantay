# BahaBantay demo deploy plan (cost approval)

**Status:** **DEPLOYED** 2026-10-27 (Asia/Manila) — live at https://bahabantay-466317436519.asia-southeast1.run.app (project `bahabantay-demo`, service `bahabantay`, region asia-southeast1, minScale 0, provider meta, $5 budget).  
**Written:** 2026-10-27 (Asia/Manila). **Target window:** ~2 weeks through Meta submission **2026-11-05 09:00 Asia/Manila**.  
**Repo:** private [BKDKUBO/bahabantay](https://github.com/BKDKUBO/bahabantay).

---

## What exists today

| Piece | State |
|---|---|
| App | FastAPI (`app/main.py`) + single-page Leaflet UI (`static/index.html`) |
| Data | SQLite (`app/db.py`), local file under `data/`; uploads on disk |
| Providers | `mock` (default) / `meta` (SAM 3.1 + Muse Spark 1.3); key via `META_API_KEY` |
| Container | **No Dockerfile yet** — would be added only after approval |
| Live site | None (local `uvicorn` only) |

SQLite on Cloud Run is **ephemeral**: a new container (cold start, new revision, crash) starts empty unless we seed. Fine for a judge demo; not for durable production.

---

## Recommended stack (cheap + judge-friendly)

**Single Cloud Run service** that serves API + static UI + `/uploads` + `/samples`.

| Choice | Recommendation | Why |
|---|---|---|
| Compute | **1× Cloud Run** service `bahabantay` | One URL, no Firebase needed for demo |
| Region | **asia-southeast1** (Singapore) | Same as InvoiceSentinel; low latency for PH |
| Scale | **min instances = 0**, max = **1** (or 2) | Avoid InvoiceSentinel-style idle burn |
| Billing | **Request-based** (CPU only during request / startup) | Sporadic judge traffic |
| Size | **1 vCPU, 512 MiB–1 GiB** | Pillow + image bytes; start at 1 GiB if cold OOM |
| Data | **Seed SQLite on container start** (`scripts/seed.py` in entrypoint) | Map has 18 simulated reports immediately |
| Secrets | Cloud Run secret / env: `META_API_KEY`; `BAHABANTAY_PROVIDER=meta`; `BAHABANTAY_META_FALLBACK=true` | Key never in image or git |
| Hosting / domain | **Cloud Run URL only** for v1 (`https://bahabantay-….a.run.app`) | Skip Firebase Hosting rewrite unless you want a prettier name |
| Auth | Public HTTPS (demo); optional IAP later | Judges can open without login |
| Budget alert | **$5 / month** warning on the demo project | Hard stop not required; alert is enough |

**Not recommended for this demo:** always-on minScale 1, separate Firebase Hosting + rewrite, Firestore migration, Artifact Registry multi-region, custom domain.

**Optional later (not in day-1 cost):** Firebase Hosting rewrite → `bahabantay.web.app`, Cloud Storage for uploads, Firestore if you need durable multi-instance data.

### Demo URL (proposed)

After approve + deploy:

`https://bahabantay-<hash>-as.a.run.app`

Exact hostname is assigned by Cloud Run; we can paste it into the Meta submission.

### Build notes (when approved — not doing now)

1. Add a slim `Dockerfile` (python 3.12-slim, `requirements.txt`, copy `app/`, `static/`, `sample_data/`, `scripts/`).
2. Entrypoint: seed DB if missing → `uvicorn app.main:app --host 0.0.0.0 --port $PORT`.
3. `gcloud run deploy` from source or Cloud Build; inject secrets; minScale 0.
4. Smoke: `/api/health` shows `"provider": "meta"`; open map; one real photo upload.

---

## Cost estimate (honest ranges)

Currency: **USD**. GCP prices from [Cloud Run pricing](https://cloud.google.com/run/pricing) (request-based Tier‑1 active ~**$0.000024**/vCPU-s, ~**$0.0000025**/GiB-s, **$0.40**/M requests; free tier shared per billing account). Meta prices from [Meta Model API pricing](https://dev.meta.ai/docs/pricing-rate-limits).

### A. Google Cloud (demo, minScale 0)

**Assumptions for ~2 weeks (through Nov 5):** light traffic — you + a few judges; ~20–80 photo uploads; a few hundred page loads; cold starts common; max instances 1; no always-on.

| Item | Estimate | Notes |
|---|---|---|
| Cloud Run CPU/RAM while serving | **~$0.00–1.50** | Often covered by free tier; InvoiceSentinel’s always-on may already consume most free-tier CPU on **My Billing Account**, so treat free tier as **uncertain** |
| Cloud Run requests | **~$0** | Well under 2M free requests |
| Container Registry / Artifact Registry + builds | **~$0.10–1.00** | One image, a few rebuilds |
| Egress (map tiles are Leaflet CDN; our images small) | **~$0–0.50** | Unknown exact; photos ≤8 MB each, few uploads |
| Firebase Hosting | **$0** if skipped | Optional rewrite: still usually free-tier for demo |
| **GCP subtotal (2 weeks)** | **≈ $0–3 typical; budget ≤ $5** | Worst case still low unless traffic spikes or someone leaves a minScale>0 by mistake |
| **GCP if left running a full idle month @ minScale 0** | **≈ $0–2** | Idle ≈ $0; only pay when hit |
| **Compare: InvoiceSentinel** | **~$10+ MTD / ~$12/mo** Cloud Run alone with **minScale 1** on api+web | This plan deliberately avoids that pattern |

**Unknowns that could raise GCP:** leaving minScale ≥1; max instances high + load test; storing large uploads and serving them a lot; unexpected crawler traffic (mitigate with budget alert).

### B. Meta Model API (separate from GCP — uses hackathon credits)

Per upload today: depth runs **6 SAM noun-phrase segmentations** (`water` + 5 reference labels) → SAM **$2.50 / 1k images** → **≈ $0.015 / upload** for SAM alone. Plus Muse Spark for agent/sitrep (**$1.25 / M input**, **$4.25 / M output** tokens) — token counts vary; order-of-magnitude **~$0.01–0.10** Muse per interactive report/sitrep (unknown exact until we meter one live session).

| Scenario (2 weeks) | Rough Meta spend | vs $150 credits |
|---|---|---|
| Light demo (30 uploads + sitreps) | **~$1–5** | Comfortably inside credits |
| Heavier judge hammer (200 uploads) | **~$5–25** | Still likely inside $150 |
| Contributor-mode Muse (`muse-spark-1.3-contributor`) | Lower Muse $; **content may train Meta models** | Only if you explicitly opt in |

**Unknowns:** exact Muse tokens per sitrep/agent trace; SAM retries on failure; whether hackathon `$150` is already partially spent. Meter in Meta dashboard after first live day.

### C. Headline for approval

| Horizon | GCP (this plan) | Meta API | Combined “out of pocket” GCP |
|---|---|---|---|
| **~2 weeks through Nov 5** | **~$0–5** (plan for **$5** budget alert) | **~$1–25** against **$150 credits** (not GCP) | Treat as **≤ $5** GCP unless you change scale |
| Full idle month after | ≈ **$0–2** if minScale stays 0 | Only if traffic continues | — |
| InvoiceSentinel-style always-on | **Do not do** — would add ~**$5–12/mo** for one warm instance | — | Avoid |

---

## Decisions that need your go-ahead

Reply with choices (defaults in **bold**):

1. **Deploy?** Yes / No — nothing ships until you say yes to this plan’s cost.
2. **GCP project:** **new project `bahabantay-demo`** (clean $5 budget, easy to delete) vs reuse `gen-lang-client-0252871691` (InvoiceSentinel; shared free tier / noisier bills).
3. **Region:** **asia-southeast1** vs other.
4. **Public URL:** **Cloud Run default `*.a.run.app`** vs add Firebase Hosting rewrite (`*.web.app`).
5. **Provider on demo:** **`BAHABANTAY_PROVIDER=meta`** with fallback to mock vs mock-only (safer offline, weaker Meta judging story).
6. **Secrets:** store `META_API_KEY` in **Secret Manager** (recommended) vs plain Cloud Run env.
7. **max instances:** **1** (SQLite-safe, no split brain) vs 2 (more headroom; seed data can diverge across instances).
8. **Budget alert amount:** **$5/mo** vs other.
9. **After Nov 5:** leave up at minScale 0 / tear down project / pause.

---

## Explicit non-goals until approved

- No `gcloud run deploy`, no Dockerfile commit required for this plan doc, no Firebase project create, no domain buy, no minScale > 0, no change to InvoiceSentinel or global gcloud defaults beyond read-only pricing lookups already done as `mmocanaiii@gmail.com`.

When you approve (with the decisions above), the next turn can add the Dockerfile + deploy under the chosen project and paste the live URL.
