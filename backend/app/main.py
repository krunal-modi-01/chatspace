"""FastAPI application entrypoint.

Wires: settings (fail-fast on missing secrets), structured JSON logging,
the correlation-id middleware, the global request-body-size ceiling, the
RFC 7807 problem+json error handlers, CORS, and the `/v1` base-path
router. No business routes, DB models, or auth live here — see the
package layout in CLAUDE.md for where those belong (`app/api`,
`app/models`, `app/schemas`, `app/services`, `app/db`, `app/core`,
`app/ws`).
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.body_limit import MaxBodySizeMiddleware
from app.core.config import get_settings
from app.core.correlation import HEADER_NAME
from app.core.errors import install_error_handlers
from app.core.logging import configure_logging
from app.core.middleware import correlation_id_middleware
from app.db.redis import dispose_redis_client, get_redis_client
from app.db.session import dispose_engine, get_sessionmaker
from app.services.bootstrap import ensure_system_admin_bootstrapped
from app.services.email import verify_email_config
from app.ws.connection_manager import connection_manager
from app.ws.fanout import PubSubRelay
from app.ws.router import ws_router

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

    # T24: one Redis pub/sub relay per app instance, started before the app
    # is considered ready to accept traffic. `relay.start()` itself never
    # blocks on Redis being reachable and never raises — the actual
    # `psubscribe` runs in the relay's own background task, retried with
    # backoff until it succeeds (`PubSubRelay._subscribe_with_retry`), so a
    # Redis blip at exactly this moment (a deploy/autoscale restart racing
    # a Redis restart) self-heals instead of leaving this instance's live
    # fan-out permanently degraded until an operator restarts it. The
    # `try/except` below is defense-in-depth only (e.g. no running event
    # loop to schedule the task on), not the primary safety net; the same
    # fail-open posture `app.services.message_events.publish_message_event`
    # applies to the publish side.
    relay = PubSubRelay(get_redis_client())
    try:
        await relay.start()
    except Exception:  # noqa: BLE001 - degrade, do not abort startup over Redis unavailability
        logger.exception("ws pub/sub relay failed to start; live fan-out degraded on this instance")

    yield

    # Server shutdown/instance drain (T23, contract close code 1001): give
    # every live `/v1/ws` connection a documented close instead of a hard
    # TCP drop, before tearing down the DB/Redis clients those connections
    # would otherwise still be trying to use.
    await relay.stop()
    await connection_manager.close_all()
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

    # T28 security review HIGH-1 / code review Major #1: added *first* --
    # `app.add_middleware` prepends to Starlette's `user_middleware` list,
    # so the *last*-added middleware ends up *outermost* (closest to
    # `ServerErrorMiddleware`, run first/last in the request/response
    # cycle) and the *first*-added ends up *innermost* (closest to
    # Starlette's `ExceptionMiddleware`). Adding `MaxBodySizeMiddleware`
    # here, before CORS/correlation are registered, makes it the innermost
    # of the three: CORS and correlation-id wrap it, so both its
    # streamed-overflow path (`BodyTooLargeError`, caught by the exception
    # handler inside `ExceptionMiddleware`) *and* its immediate
    # `Content-Length`-precheck `413` (sent directly via `send()`, never
    # reaching `self._app`/`ExceptionMiddleware`) flow back out through
    # CORS and correlation-id before reaching the client. Getting this
    # backwards (adding it last) silently strips
    # `Access-Control-Allow-Origin` and `X-Correlation-Id` from the
    # precheck response and breaks the "correlation_id is always present"
    # contract in `errors.py` -- see `app.core.body_limit`'s module
    # docstring for why this must still run before the multipart/body
    # parser buffers anything.
    app.add_middleware(MaxBodySizeMiddleware)

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
    # `/v1/ws` (T23): wired directly rather than through `api_router` since
    # that router is documented REST-only — see `app.api.router`'s module
    # docstring.
    app.include_router(ws_router, prefix="/v1")

    logger.info("chatspace API startup complete", extra={"app_env": settings.app_env})

    return app


app = create_app()
