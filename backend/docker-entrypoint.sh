#!/usr/bin/env bash
# CPI backend entrypoint for Docker Compose.
# 1. Wait for PostgreSQL to accept connections.
# 2. Run Alembic migrations (idempotent).
# 3. Ingest the sample dataset (idempotent — checksum-based, skips unchanged files).
# 4. Start uvicorn.
set -euo pipefail

echo "[entrypoint] Waiting for PostgreSQL at ${DB_HOST:-db}:${DB_PORT:-5432}…"
until pg_isready -h "${DB_HOST:-db}" -p "${DB_PORT:-5432}" -U "${DB_USER:-cpi}" -q; do
    sleep 1
done
echo "[entrypoint] PostgreSQL is ready."

echo "[entrypoint] Running Alembic migrations…"
cd /app/backend
PYTHONPATH=/app/backend alembic upgrade head

echo "[entrypoint] Ingesting sample dataset from ${SAMPLE_DATA_DIR:-/app/data/sample/matches}…"
# Collect all JSON files in the sample directory and pass them explicitly to the script.
# This avoids the hardcoded GAMEDATA_DIR inside ingest_gamedata.py.
SAMPLE_DIR="${SAMPLE_DATA_DIR:-/app/data/sample/matches}"
mapfile -t sample_files < <(find "$SAMPLE_DIR" -name '*.json' | sort)
if [[ ${#sample_files[@]} -gt 0 ]]; then
    PYTHONPATH=/app/backend python scripts/ingest_gamedata.py --files "${sample_files[@]}"
    echo "[entrypoint] Sample ingestion complete (${#sample_files[@]} files)."
else
    echo "[entrypoint] WARNING: No JSON files found in $SAMPLE_DIR — skipping ingestion."
fi

echo "[entrypoint] Starting uvicorn…"
exec uvicorn app.main:app --host 0.0.0.0 --port 8000

