#!/usr/bin/env bash
# Run a local Mailpit mail catcher for testing emails (password reset, etc.)
# in development. Mailpit accepts SMTP on :1025 and serves a web inbox on :8025.
#
#   scripts/mailpit.sh [start|stop|status]   (default: start)
#
# Then start the dev server pointed at it:
#   DJANGO_DEV_SMTP=localhost:1025 scripts/start.sh
#   # or simply:  MAILPIT=1 scripts/start.sh   (does both)
#
# View sent emails at http://localhost:8025
set -euo pipefail

NAME="devplanner-mailpit"
IMAGE="axllent/mailpit"
SMTP_PORT="${MAILPIT_SMTP_PORT:-1025}"
UI_PORT="${MAILPIT_UI_PORT:-8025}"
CMD="${1:-start}"

if ! command -v docker >/dev/null 2>&1; then
    echo "[mailpit] docker not found. Install Docker, or use the console backend"
    echo "[mailpit] (emails print to .devserver.log when DJANGO_DEV_SMTP is unset)."
    exit 1
fi

running() { [ -n "$(docker ps -q -f "name=^${NAME}$")" ]; }
exists()  { [ -n "$(docker ps -aq -f "name=^${NAME}$")" ]; }

case "$CMD" in
    start)
        if running; then
            echo "[mailpit] already running."
        elif exists; then
            docker start "$NAME" >/dev/null
            echo "[mailpit] started existing container."
        else
            docker run -d --name "$NAME" \
                -p "${SMTP_PORT}:1025" -p "${UI_PORT}:8025" "$IMAGE" >/dev/null
            echo "[mailpit] created and started."
        fi
        echo "[mailpit] SMTP: localhost:${SMTP_PORT}   Inbox: http://localhost:${UI_PORT}"
        ;;
    stop)
        if exists; then
            docker rm -f "$NAME" >/dev/null
            echo "[mailpit] stopped and removed."
        else
            echo "[mailpit] not running."
        fi
        ;;
    status)
        if running; then
            echo "[mailpit] running — inbox at http://localhost:${UI_PORT}"
        else
            echo "[mailpit] not running."
        fi
        ;;
    *)
        echo "usage: scripts/mailpit.sh [start|stop|status]"
        exit 1
        ;;
esac
