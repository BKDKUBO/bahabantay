#!/bin/sh
set -e
cd /app
mkdir -p /app/data/uploads /app/sample_data/images
# Seed SQLite on every cold start (ephemeral Cloud Run filesystem).
python -m scripts.seed
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8080}"
