#!/usr/bin/env bash
# T37: boot entrypoint for the backend container.
#
# Runs pending Alembic migrations against `DATABASE_URL` (env-injected, never
# baked into the image) and then execs whatever CMD was given (uvicorn in
# normal operation, or an override for one-off tooling). `set -euo pipefail`
# so a failed migration aborts the container instead of serving against a
# stale/partial schema.
#
# Scope note: this is the LOCAL COMPOSE boot path only (T37). Migrations
# against a shared/prod database (T40) require explicit human approval and
# are never triggered by this script running against a shared DATABASE_URL.
set -euo pipefail

echo "[docker-entrypoint] running 'alembic upgrade head'..."
alembic upgrade head
echo "[docker-entrypoint] migrations applied; starting: $*"

exec "$@"
