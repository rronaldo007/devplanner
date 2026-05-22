#!/usr/bin/env sh
# Entrypoint: apply migrations, then exec the container CMD.
set -eu

echo "[entrypoint] applying database migrations..."
python manage.py migrate --noinput

echo "[entrypoint] starting: $*"
exec "$@"
