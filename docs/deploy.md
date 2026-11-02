# Deploying BahaBantay (Cloud Run)

One Cloud Run service serves the API, the single-page UI, uploads and sample images.

```bash
gcloud run deploy bahabantay --source . --project <your-project> --region asia-southeast1 \
  --min-instances 0 --max-instances 1 --allow-unauthenticated \
  --set-env-vars BAHABANTAY_PROVIDER=meta,BAHABANTAY_META_FALLBACK=true \
  --set-secrets META_API_KEY=<secret-name>:latest
```

- `max-instances 1` because storage is SQLite on the container's local disk.
- The container re-seeds the 18 sample reports on every cold start (`scripts/entrypoint.sh`), so user reports are
  **not durable**; a restart clears them. Fine for a demo, not for production.
- The Meta key lives in Secret Manager and is injected at runtime; it is never in the image or the repo.
- Smoke test: `GET /api/health` should return `"provider": "meta"` and `"key_present": true`.
