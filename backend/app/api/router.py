"""The `/v1` base-path router.

All REST routes are mounted under `/v1` (frozen contract, line 13). The
WebSocket endpoint `/v1/ws` is reserved by the contract for real-time
delivery and must never be stubbed as a REST route here — it is wired
separately by the `app.ws` package in a later task.

T10 adds the `/v1/auth/sessions` list/revoke routes (session store +
`require_auth`, ADR-0006). T15 adds `/v1/auth/login`, `/refresh`, and
`/logout` (`app.api.auth`). T16 adds `/v1/auth/password-reset`,
`/v1/auth/password-reset/confirm`, and `/v1/auth/password/change`
(`app.api.password`).
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api import auth, health, password, sessions

api_router = APIRouter(prefix="/v1")
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(sessions.router)
api_router.include_router(password.router)
