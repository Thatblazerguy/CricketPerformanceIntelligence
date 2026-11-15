#!/bin/bash
# Optional: run the CPI sync worker automatically at login via launchd (macOS).
#
#   backend/scripts/install_launchd.sh install     # write ~/Library/LaunchAgents/com.cpi.syncworker.plist and load it
#   backend/scripts/install_launchd.sh uninstall   # unload and remove it
#   backend/scripts/install_launchd.sh status
#
# launchd restarts the worker if it crashes (not after a clean exit, e.g. when
# another worker already holds the lock). PostgreSQL must also start at login
# (e.g. `brew services start postgresql@16`); the worker waits for it.
set -euo pipefail

LABEL="com.cpi.syncworker"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
BACKEND_DIR="$ROOT/backend"
TEMPLATE="$ROOT/deploy/macos/$LABEL.plist.template"
TARGET="$HOME/Library/LaunchAgents/$LABEL.plist"
DOMAIN="gui/$(id -u)"

case "${1:-}" in
  install)
    if [[ -f "$BACKEND_DIR/run/sync_worker.pid" ]] && kill -0 "$(cat "$BACKEND_DIR/run/sync_worker.pid")" 2>/dev/null; then
      echo "Stopping the manually started worker first..."
      "$BACKEND_DIR/scripts/sync_worker.sh" stop
    fi
    mkdir -p "$HOME/Library/LaunchAgents" "$BACKEND_DIR/logs"
    sed -e "s#__BACKEND_DIR__#$BACKEND_DIR#g" "$TEMPLATE" >"$TARGET"
    plutil -lint "$TARGET" >/dev/null
    launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
    launchctl bootstrap "$DOMAIN" "$TARGET"
    launchctl enable "$DOMAIN/$LABEL"
    echo "Installed $TARGET; the worker now starts at login and restarts after crashes."
    ;;
  uninstall)
    launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
    rm -f "$TARGET"
    echo "Removed $LABEL. Start the worker manually with backend/scripts/sync_worker.sh start."
    ;;
  status)
    if launchctl print "$DOMAIN/$LABEL" 2>/dev/null | grep -E "state =|pid =|last exit code"; then :; else
      echo "$LABEL is not loaded."
    fi
    ;;
  *) echo "Usage: $0 {install|uninstall|status}" >&2; exit 2 ;;
esac
