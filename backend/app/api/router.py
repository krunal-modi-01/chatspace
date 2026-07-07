"""The `/v1` base-path router.

All REST routes are mounted under `/v1` (frozen contract, line 13). The
WebSocket endpoint `/v1/ws` is reserved by the contract for real-time
delivery and must never be stubbed as a REST route here — it is wired
separately by the `app.ws` package in a later task.

T10 adds the `/v1/auth/sessions` list/revoke routes (session store +
`require_auth`, ADR-0006). Login/logout/refresh are out of scope (T15).
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api import health, sessions

api_router = APIRouter(prefix="/v1")
api_router.include_router(health.router)
api_router.include_router(sessions.router)
