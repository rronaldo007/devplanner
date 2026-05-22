#!/usr/bin/env bash
# Start DevPlanner in development mode (native, with auto-reload).
#
# Creates a virtualenv if missing, installs requirements, applies migrations,
# then runs the Django dev server. Use scripts/stop.sh to stop it.
set -euo pipefail

# Project root is the parent of this scripts/ directory.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

VENV="$ROOT/.venv"
PID_FILE="$ROOT/.devserver.pid"
LOG_FILE="$ROOT/.devserver.log"
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8000}"

# Don't start a second server on top of one we already manage.
if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    echo "[start] dev server already running (PID $(cat "$PID_FILE")). Run scripts/stop.sh first."
    exit 1
fi

# Returns 0 if something is already listening on $HOST:$1.
port_in_use() {
    (exec 3<>"/dev/tcp/$HOST/$1") 2>/dev/null && { exec 3>&- 3<&-; return 0; }
    return 1
}

# If the requested port is taken, walk forward to the next free one so the
# server still comes up (handy when another project owns 8000).
if port_in_use "$PORT"; then
    REQUESTED_PORT="$PORT"
    for candidate in $(seq "$((PORT + 1))" "$((PORT + 20))"); do
        if ! port_in_use "$candidate"; then
            PORT="$candidate"
            break
        fi
    done
    if [ "$PORT" = "$REQUESTED_PORT" ]; then
        echo "[start] port $REQUESTED_PORT and the next 20 ports are all in use. Free one up or set PORT explicitly."
        exit 1
    fi
    echo "[start] port $REQUESTED_PORT is in use; switching to free port $PORT."
fi

# 1. Virtualenv
if [ ! -d "$VENV" ]; then
    echo "[start] creating virtualenv at .venv ..."
    python3 -m venv "$VENV"
fi
# shellcheck disable=SC1091
source "$VENV/bin/activate"

# 2. Dependencies
echo "[start] installing requirements ..."
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt

# 3. Load .env if present (so ANTHROPIC_API_KEY etc. are available).
if [ -f "$ROOT/.env" ]; then
    echo "[start] loading .env ..."
    set -a
    # shellcheck disable=SC1091
    . "$ROOT/.env"
    set +a
fi

# Dev defaults: debug on unless the env already says otherwise.
export DJANGO_DEBUG="${DJANGO_DEBUG:-true}"

# Email catcher: when Docker is available, start Mailpit and route emails to its
# web inbox (http://localhost:8025) instead of the console. Default on; disable
# with MAILPIT=0. Honour an explicit DJANGO_DEV_SMTP if the user set one.
if [ "${MAILPIT:-1}" != "0" ] && [ "${MAILPIT:-1}" != "false" ] \
        && command -v docker >/dev/null 2>&1; then
    if "$ROOT/scripts/mailpit.sh" start; then
        export DJANGO_DEV_SMTP="${DJANGO_DEV_SMTP:-localhost:1025}"
        echo "[start] emails -> Mailpit inbox at http://localhost:8025"
    fi
fi

# 4. Migrations
echo "[start] applying migrations ..."
python manage.py migrate --noinput

# 5. Run server in its own process group so stop.sh can reap the autoreloader
#    child as well as the parent. Record the leader PID (== PGID).
echo "[start] starting dev server on http://$HOST:$PORT/ ..."
setsid python manage.py runserver "$HOST:$PORT" >"$LOG_FILE" 2>&1 &
SERVER_PID=$!
echo "$SERVER_PID" >"$PID_FILE"

# 6. Wait until it actually answers HTTP (catches bind failures, import errors).
echo "[start] waiting for server to become ready ..."
for _ in $(seq 1 20); do
    if ! kill -0 "$SERVER_PID" 2>/dev/null; then
        break  # process died; fall through to the failure report
    fi
    if (exec 3<>"/dev/tcp/$HOST/$PORT") 2>/dev/null; then
        exec 3>&- 3<&-
        echo "[start] running (PID $SERVER_PID). Logs: $LOG_FILE"
        echo "[start] open http://$HOST:$PORT/"
        exit 0
    fi
    sleep 0.5
done

echo "[start] server failed to start. Last log lines:"
tail -n 20 "$LOG_FILE" || true
# Clean up the process group if anything is lingering.
kill -- "-$SERVER_PID" 2>/dev/null || true
rm -f "$PID_FILE"
exit 1
