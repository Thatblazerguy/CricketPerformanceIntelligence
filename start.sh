#!/bin/bash
# CPI local startup: FastAPI backend + Cricsheet sync worker + Vite frontend.
#
#   ./start.sh            start everything; Ctrl+C stops what this script started
#
# The sync worker is independent of the browser and the frontend. If the launchd
# agent is installed (backend/scripts/install_launchd.sh) it is left to launchd.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
BACKEND="$ROOT/backend"
cd "$ROOT"

echo "=== Cricket Performance Intelligence ==="

# Warn (do not auto-apply) if the database schema is behind the code.
CURRENT="$(cd "$BACKEND" && .venv/bin/alembic current 2>/dev/null | awk '{print $1}' | tail -1 || true)"
HEAD="$(cd "$BACKEND" && .venv/bin/alembic heads 2>/dev/null | awk '{print $1}' | tail -1 || true)"
if [[ -n "$HEAD" && "$CURRENT" != "$HEAD" ]]; then
  echo "!! Database schema is at '${CURRENT:-unknown}', code expects '$HEAD'."
  echo "   Apply with: (cd backend && .venv/bin/alembic upgrade head)"
fi

PIDS=()
cleanup() {
  echo
  echo "Stopping services started by start.sh..."
  for pid in "${PIDS[@]:-}"; do [[ -n "$pid" ]] && kill "$pid" 2>/dev/null || true; done
  if [[ "${STARTED_WORKER:-0}" == "1" ]]; then "$BACKEND/scripts/sync_worker.sh" stop || true; fi
  exit 0
}
trap cleanup INT TERM

echo "[1/3] FastAPI backend on http://127.0.0.1:8000 ..."
(cd "$BACKEND" && exec .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload) &
PIDS+=($!)

echo "[2/3] Cricsheet sync worker ..."
STARTED_WORKER=0
if launchctl print "gui/$(id -u)/com.cpi.syncworker" >/dev/null 2>&1; then
  echo "      managed by launchd (com.cpi.syncworker) - leaving it running."
else
  if ! "$BACKEND/scripts/sync_worker.sh" start | grep -q "already running"; then STARTED_WORKER=1; fi
fi

echo "[3/3] Frontend on http://localhost:5173 ..."
(cd "$ROOT/frontend" && exec npm run dev) &
PIDS+=($!)

cat <<MSG

=== CPI is running ===
  Frontend : http://localhost:5173   (Settings -> Data Management for sync status)
  API docs : http://127.0.0.1:8000/api/docs
  Worker   : backend/scripts/sync_worker.sh status | logs | stop

Press Ctrl+C to stop.
MSG
wait
