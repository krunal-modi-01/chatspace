#!/usr/bin/env bash
# CI migration round-trip gate (T38): `alembic upgrade head` -> `alembic
# downgrade base` against a dedicated, throwaway ("scratch") database — not
# the shared `chatspace_test` database the pytest suite uses, and not any
# environment that could hold real data. This validates that the reverse
# migrations the T04 design promises (see docs/spec database design, "DOWN
# order") are total and safe to run, independent of pytest fixture ordering.
#
# Never run this against a shared/staging/production database — it drops
# the target database outright at the end. Intended for CI and local dev
# only, against a disposable local Postgres.
#
# Required env (already exported by the caller):
#   PG_HOST, PG_PORT, PG_SUPERUSER, PG_SUPERUSER_PASSWORD
# Everything else (REDIS_URL, JWT_SIGNING_KEY, SMTP_*, S3_*, BOOTSTRAP_ADMIN_*)
# must already be set in the environment so `app.core.config.Settings`
# validates — see the `backend-verify` job's `env:` block in ci.yml for the
# non-secret test values. REDIS_URL only needs to be syntactically valid:
# `alembic/env.py` calls `get_settings()` before this script ever touches the
# DB, and that call never opens a Redis connection.
set -euo pipefail

: "${PG_HOST:=localhost}"
: "${PG_PORT:=5432}"
: "${PG_SUPERUSER:=postgres}"
: "${PG_SUPERUSER_PASSWORD:=postgres}"
SCRATCH_DB="chatspace_ci_migration_scratch"

cd "$(dirname "${BASH_SOURCE[0]}")/../../backend"

PGPASSWORD=$PG_SUPERUSER_PASSWORD
export PGPASSWORD

# -w (--no-password) so any psql invocation that somehow loses the inherited
# PGPASSWORD env (e.g. a future edit runs it via `sudo`) fails fast with a
# clear "no password supplied" error instead of hanging on an interactive
# password prompt in CI.
PSQL_OPTS=(-w)

echo "== migration-roundtrip: (re)creating scratch database $SCRATCH_DB =="
psql "${PSQL_OPTS[@]}" -h "$PG_HOST" -p "$PG_PORT" -U "$PG_SUPERUSER" -d postgres -v ON_ERROR_STOP=1 \
  -c "DROP DATABASE IF EXISTS ${SCRATCH_DB};"
psql "${PSQL_OPTS[@]}" -h "$PG_HOST" -p "$PG_PORT" -U "$PG_SUPERUSER" -d postgres -v ON_ERROR_STOP=1 \
  -c "CREATE DATABASE ${SCRATCH_DB};"

export DATABASE_URL="postgresql+asyncpg://${PG_SUPERUSER}:${PG_SUPERUSER_PASSWORD}@${PG_HOST}:${PG_PORT}/${SCRATCH_DB}"

echo "== migration-roundtrip: alembic upgrade head =="
uv run alembic upgrade head

echo "== migration-roundtrip: verifying schema is non-empty after upgrade =="
table_count="$(psql "${PSQL_OPTS[@]}" -h "$PG_HOST" -p "$PG_PORT" -U "$PG_SUPERUSER" -d "$SCRATCH_DB" -tA \
  -c "SELECT count(*) FROM information_schema.tables WHERE table_schema='public';")"
if [ "$table_count" -lt 2 ]; then
  echo "expected multiple tables after 'upgrade head', found $table_count" >&2
  exit 1
fi

echo "== migration-roundtrip: alembic downgrade base =="
uv run alembic downgrade base

echo "== migration-roundtrip: verifying schema is empty (only alembic bookkeeping) after downgrade =="
remaining="$(psql "${PSQL_OPTS[@]}" -h "$PG_HOST" -p "$PG_PORT" -U "$PG_SUPERUSER" -d "$SCRATCH_DB" -tA \
  -c "SELECT count(*) FROM information_schema.tables WHERE table_schema='public' AND table_name <> 'alembic_version';")"
if [ "$remaining" -ne 0 ]; then
  echo "expected only alembic_version table after 'downgrade base', found $remaining extra table(s)" >&2
  exit 1
fi

enum_count="$(psql "${PSQL_OPTS[@]}" -h "$PG_HOST" -p "$PG_PORT" -U "$PG_SUPERUSER" -d "$SCRATCH_DB" -tA \
  -c "SELECT count(*) FROM pg_type WHERE typtype = 'e';")"
if [ "$enum_count" -ne 0 ]; then
  echo "expected zero leftover enum types after 'downgrade base', found $enum_count" >&2
  exit 1
fi

echo "== migration-roundtrip: dropping scratch database =="
psql "${PSQL_OPTS[@]}" -h "$PG_HOST" -p "$PG_PORT" -U "$PG_SUPERUSER" -d postgres -v ON_ERROR_STOP=1 \
  -c "DROP DATABASE IF EXISTS ${SCRATCH_DB};"

echo "migration-roundtrip: OK (upgrade head -> downgrade base is total and reversible)."
