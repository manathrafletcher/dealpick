#!/usr/bin/env bash
# Render "Start Command":  bash start.sh
# Nothing is stored, so there is no database or backup to start.
set -euo pipefail
exec gunicorn app:app --workers 1 --threads 8 --timeout 180 --bind 0.0.0.0:${PORT:-8081}
