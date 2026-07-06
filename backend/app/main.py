"""FastAPI application entrypoint.

Wires: settings (fail-fast on missing secrets), structured JSON logging,
the correlation-id middleware, the RFC 7807 problem+json error handlers,
CORS, and the `/v1` base-path router. No business routes, DB models, or
auth live here — see the package layout in CLAUDE.md for where those
belong (`app/api`, `app/models`, `app/schemas`, `app/services`, `app/db`,
`app/core`, `app/ws`).
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import get_settings
from app.core.correlation import HEADER_NAME
from app.core.errors import install_error_handlers
from app.core.logging import configure_logging
from app.core.middleware import correlation_id_middleware
from app.db.redis import dispose_redis_client
from app.db.session import dispose_engine

logger = logging.getLogger(__name__)


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Dispose the DB engine's and Redis client's pooled connections on shutdown.

    Both are created lazily (see `app.db.session.get_engine` and
    `app.db.redis.get_redis_client`) on first use — typically the first
    `/v1/readyz` call or a DB/Redis-backed request — so there is nothing
    to open here, only to close cleanly.
    """

    yield
    await dispose_engine()
    await dispose_redis_client()


def create_app() -> FastAPI:
    """Application factory.

    Building the app behind a factory (rather than at import time) keeps
    settings validation lazy and makes the app importable for tooling
    (OpenAPI generation, tests) without requiring a fully configured
    environment unless the app is actually instantiated.
    """

    settings = get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(
        title="chatspace API",
        version="1.0.0",
        docs_url="/v1/docs",
        openapi_url="/v1/openapi.json",
        lifespan=_lifespan,
    )

    # Only send credentialed CORS responses to a concrete origin allowlist.
    # A wildcard origin with credentials is a credential-theft vector, so
    # credentials are disabled unless every configured origin is explicit.
    allowed_origins = settings.cors_allowed_origins
    allow_credentials = bool(allowed_origins) and "*" not in allowed_origins

    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=allow_credentials,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key", HEADER_NAME],
    )

    app.middleware("http")(correlation_id_middleware)

    install_error_handlers(app)

    app.include_router(api_router)

    logger.info("chatspace API startup complete", extra={"app_env": settings.app_env})

    return app


app = create_app()
