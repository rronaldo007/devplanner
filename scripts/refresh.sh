#!/usr/bin/env bash
# Refresh DevPlanner in development mode: stop the server, reinstall
# dependencies, re-apply migrations, then start it again. Run this after
# pulling new code or changing requirements / models.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRIPTS="$ROOT/scripts"

echo "[refresh] stopping any running dev server ..."
"$SCRIPTS/stop.sh" || true

echo "[refresh] restarting (deps + migrations handled by start.sh) ..."
"$SCRIPTS/start.sh"

echo "[refresh] done."
