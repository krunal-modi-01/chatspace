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
from app.db.session import dispose_engine, get_sessionmaker
from app.services.bootstrap import ensure_system_admin_bootstrapped
from app.services.email import verify_email_config

logger = logging.getLogger(__name__)


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Run the non-skippable Phase-0 System Admin bootstrap, then serve.

    ADR-0009 / technical spec §10 (Phase 0) / FS F8-F9: the app must
    never finish starting up into a workspace with zero System Admins.
    `ensure_system_admin_bootstrapped` is idempotent (a no-op once any
    user exists) but, on failure, raises `BootstrapError` — deliberately
    left uncaught here so application startup aborts and the process
    refuses to serve, mirroring `verify_email_config`'s fail-loud posture
    in `create_app` below (ADR-0010).

    The DB engine is created lazily elsewhere (see
    `app.db.session.get_engine`) — this is the first guaranteed real DB
    round-trip of the process lifecycle, and it runs before `yield`, i.e.
    before the ASGI server is considered ready to accept traffic.
    """

    settings = get_settings()
    session_factory = get_sessionmaker()
    async with session_factory() as session:
        try:
            await ensure_system_admin_bootstrapped(session, settings)
            await session.commit()
        except Exception:
            await session.rollback()
            raise

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

    # Phase-0 non-skippable prerequisite (ADR-0010, technical spec §10):
    # transactional email must be usable before the app is allowed to
    # serve traffic, since invites/resets would otherwise silently fail.
    # `Settings` already fails process startup if a `smtp_*` var is
    # missing entirely; this catches present-but-malformed values too.
    verify_email_config(settings)

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
