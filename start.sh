#!/usr/bin/env bash
# Render "Start Command":  bash start.sh
set -euo pipefail

export DATABASE_PATH="${DATABASE_PATH:-/tmp/dealpick/dealpick.db}"
mkdir -p "$(dirname "$DATABASE_PATH")"
CONFIG="${LITESTREAM_CONFIG:-litestream.yml}"
APP="gunicorn dealpick_app:app --workers 1 --threads 8 --timeout 180 --bind 0.0.0.0:${PORT:-8081}"

if [ -n "${LITESTREAM_BUCKET:-}" ]; then
  # 1. Bring back the latest copy of the database (does nothing on the very first run).
  ./litestream restore -if-db-not-exists -if-replica-exists -config "$CONFIG" "$DATABASE_PATH"
  # 2. Run the app while Litestream keeps the bucket copy up to date.
  exec ./litestream replicate -config "$CONFIG" -exec "$APP"
else
  echo "WARNING: LITESTREAM_BUCKET is not set. Data will be lost whenever this service sleeps or restarts."
  exec $APP
fi
