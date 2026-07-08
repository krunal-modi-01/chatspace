"""The `/v1` base-path router.

All REST routes are mounted under `/v1` (frozen contract, line 13). The
WebSocket endpoint `/v1/ws` is reserved by the contract for real-time
delivery and must never be stubbed as a REST route here — it is wired
separately by the `app.ws` package in a later task.

T10 adds the `/v1/auth/sessions` list/revoke routes (session store +
`require_auth`, ADR-0006). T15 adds `/v1/auth/login`, `/refresh`, and
`/logout` (`app.api.auth`). T14 adds `/v1/auth/register`
(`app.api.auth`, invite redemption — depends on T13). T16 adds
`/v1/auth/password-reset`,
`/v1/auth/password-reset/confirm`, and `/v1/auth/password/change`
(`app.api.password`). T17 adds `/v1/me` (own profile — `GET`/`PATCH`).
T13 adds `/v1/invites*` (System Admin invite issuance/lifecycle,
`app.api.invites`). T18 adds `/v1/channels*` (create/get/public browse,
`app.api.channels`).
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api import auth, channels, health, invites, me, password, sessions

api_router = APIRouter(prefix="/v1")
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(sessions.router)
api_router.include_router(password.router)
api_router.include_router(me.router)
api_router.include_router(invites.router)
api_router.include_router(channels.router)
