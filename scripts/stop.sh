#!/usr/bin/env bash
# Stop the DevPlanner development server started by scripts/start.sh.
#
# start.sh launches the server in its own process group, so we signal the
# whole group to also catch the autoreloader child process.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PID_FILE="$ROOT/.devserver.pid"

if [ ! -f "$PID_FILE" ]; then
    echo "[stop] no PID file found; dev server does not appear to be running."
    exit 0
fi

PID="$(cat "$PID_FILE")"

# Negative PID targets the whole process group (parent + reloader child).
if kill -TERM -- "-$PID" 2>/dev/null; then
    echo "[stop] stopping dev server group (PGID $PID) ..."
    sleep 1
    if kill -0 -- "-$PID" 2>/dev/null; then
        echo "[stop] still alive, sending SIGKILL ..."
        kill -KILL -- "-$PID" 2>/dev/null || true
    fi
    echo "[stop] stopped."
elif kill -0 "$PID" 2>/dev/null; then
    # Fallback: single process (e.g. started without setsid).
    kill "$PID" 2>/dev/null || true
    echo "[stop] stopped (PID $PID)."
else
    echo "[stop] process $PID not running (stale PID file)."
fi

rm -f "$PID_FILE"
