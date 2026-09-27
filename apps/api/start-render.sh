#!/bin/sh
set -eu

echo "Running database migrations..."
alembic -c alembic.ini upgrade head

echo "Starting SlipIQ API..."
exec uvicorn app.main:app \
  --host 0.0.0.0 \
  --port "${PORT}" \
  --workers "${WEB_CONCURRENCY:-1}"
