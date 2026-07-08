# syntax=docker/dockerfile:1
#
# Multi-stage build for the chatspace backend (FastAPI + uv).
#
# Stage 1 (builder) resolves/installs dependencies with uv into a local
# virtualenv using only the lockfile — so a source-only change never busts
# the dependency cache layer. Stage 2 (runtime) copies just the venv and
# application source into a slim, non-root image. No secret ever appears in
# an ENV/ARG/RUN instruction here — all runtime config (DB/Redis/SMTP/S3/JWT)
# is injected by docker-compose / the platform at container start, per
# CLAUDE.md `secrets_location`.

FROM python:3.12-slim AS builder

# `uv` ships as a static binary; copying it from its own pinned image avoids
# a network install step and keeps the builder reproducible.
COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /uvx /usr/local/bin/

WORKDIR /build

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv

# Dependency layer first: only the lockfile + project manifest are needed to
# resolve/install, so editing application source never invalidates this
# layer (docker skill: "dependency layer before source layer").
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

# Now bring in the source and install the project itself (no dev deps in
# the runtime image — pytest/mypy/ruff stay in the builder only).
COPY app ./app
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

FROM python:3.12-slim AS runtime

# curl is the smallest reliable HEALTHCHECK probe against /v1/healthz.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --system --gid 1000 chatspace \
    && useradd --system --uid 1000 --gid chatspace --create-home chatspace

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
COPY --chown=chatspace:chatspace app ./app
COPY --chown=chatspace:chatspace alembic ./alembic
COPY --chown=chatspace:chatspace alembic.ini ./alembic.ini
COPY --chown=chatspace:chatspace docker-entrypoint.sh ./docker-entrypoint.sh

RUN chmod +x ./docker-entrypoint.sh

ENV PATH="/opt/venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

USER chatspace

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --start-period=15s --retries=5 \
    CMD curl -f http://localhost:8000/v1/healthz || exit 1

ENTRYPOINT ["./docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
