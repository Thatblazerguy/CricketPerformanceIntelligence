#!/bin/bash
# CPI Cricsheet sync worker control.
#
#   backend/scripts/sync_worker.sh start     # start in the background (survives closing the terminal)
#   backend/scripts/sync_worker.sh stop      # graceful stop (finishes the current match, then exits)
#   backend/scripts/sync_worker.sh restart
#   backend/scripts/sync_worker.sh status    # worker health + data freshness from PostgreSQL
#   backend/scripts/sync_worker.sh logs      # follow backend/logs/sync_worker.log
#   backend/scripts/sync_worker.sh once      # run one sync cycle in the foreground
#   backend/scripts/sync_worker.sh run       # run in the foreground (what launchd uses)
#
# If the launchd agent (com.cpi.syncworker) is installed, launchd owns the worker;
# use backend/scripts/install_launchd.sh to manage it instead.
set -euo pipefail

BACKEND_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PY="$BACKEND_DIR/.venv/bin/python"
RUN_DIR="$BACKEND_DIR/run"
PID_FILE="$RUN_DIR/sync_worker.pid"
LOG_DIR="$BACKEND_DIR/logs"
LABEL="com.cpi.syncworker"

mkdir -p "$RUN_DIR" "$LOG_DIR"
cd "$BACKEND_DIR"

launchd_managed() {
  launchctl print "gui/$(id -u)/$LABEL" >/dev/null 2>&1
}

running_pid() {
  if [[ -f "$PID_FILE" ]]; then
    local pid
    pid="$(cat "$PID_FILE" 2>/dev/null || true)"
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
      echo "$pid"
      return 0
    fi
  fi
  return 1
}

cmd_start() {
  if launchd_managed; then
    echo "Worker is managed by launchd ($LABEL); it starts automatically. Status:"
    cmd_status
    return 0
  fi
  if pid="$(running_pid)"; then
    echo "Sync worker already running (pid $pid)."
    return 0
  fi
  nohup "$PY" worker.py "$@" >>"$LOG_DIR/sync_worker.out" 2>&1 &
  echo $! >"$PID_FILE"
  sleep 2
  if pid="$(running_pid)"; then
    echo "Sync worker started (pid $pid). Logs: $LOG_DIR/sync_worker.log"
  else
    echo "Sync worker exited immediately; last log lines:" >&2
    tail -n 20 "$LOG_DIR/sync_worker.log" >&2 || true
    rm -f "$PID_FILE"
    return 1
  fi
}

cmd_stop() {
  if launchd_managed; then
    echo "Worker is managed by launchd. Run: backend/scripts/install_launchd.sh uninstall" >&2
    return 1
  fi
  if ! pid="$(running_pid)"; then
    echo "Sync worker is not running."
    rm -f "$PID_FILE"
    return 0
  fi
  kill -TERM "$pid"
  for _ in $(seq 1 120); do
    kill -0 "$pid" 2>/dev/null || { rm -f "$PID_FILE"; echo "Sync worker stopped."; return 0; }
    sleep 1
  done
  echo "Worker did not stop within 120s; sending SIGKILL (PostgreSQL rolls back any open match import)." >&2
  kill -KILL "$pid" 2>/dev/null || true
  rm -f "$PID_FILE"
}

cmd_status() {
  "$PY" - <<'PYEOF'
import json, subprocess, sys
out = subprocess.run([sys.executable, "worker.py", "--status"], capture_output=True, text=True)
if out.returncode != 0:
    print(out.stderr.strip() or out.stdout.strip()); sys.exit(out.returncode)
s = json.loads(out.stdout[out.stdout.index("{"):])
w = s["worker"]
print(f"Worker:                {'healthy' if w['healthy'] else w['state']} (pid {w['pid']}, heartbeat {w['heartbeat_at']})")
print(f"Automatic sync:        {'on' if s['settings']['auto_sync_enabled'] else 'off'}, every {s['settings']['interval_hours']}h")
print(f"Next scheduled check:  {s['next_check_at']}")
print(f"Data updated through:  {s['data_updated_through']}  (latest match date)")
print(f"Last source check:     {s['last_checked_at']}")
print(f"Last successful import:{' ' + str(s['last_imported_at'])}")
print(f"Totals:                {s['total_matches']:,} matches / {s['total_innings']:,} innings / {s['total_deliveries']:,} deliveries")
ls = s["latest_sync"]
if ls:
    print(f"Latest sync:           {ls['status']} ({ls['triggered_by']}) new={ls['new_matches']} corrected={ls['updated_matches']} failed={ls['failed_records']}")
if s["current_sync"]:
    cur = [x for x in s["current_sync"]["sources"] if x["status"] == "running"]
    if cur:
        print(f"Running now:           {cur[0]['source_key']} - {cur[0]['phase']} {cur[0]['progress_current']}/{cur[0]['progress_total']}")
PYEOF
}

case "${1:-}" in
  start)   shift; cmd_start "$@" ;;
  stop)    cmd_stop ;;
  restart) cmd_stop; shift; cmd_start "$@" ;;
  status)  cmd_status ;;
  logs)    tail -n 50 -f "$LOG_DIR/sync_worker.log" ;;
  once)    exec "$PY" worker.py --once ;;
  run)     shift; exec "$PY" worker.py "$@" ;;
  *) echo "Usage: $0 {start|stop|restart|status|logs|once|run}" >&2; exit 2 ;;
esac
