"""The `/v1` base-path router.

All REST routes are mounted under `/v1` (frozen contract, line 13). The
WebSocket endpoint `/v1/ws` is reserved by the contract for real-time
delivery and must never be stubbed as a REST route here — it is wired
separately (`app.ws.router.ws_router`, T23) directly onto the app with
the same `/v1` prefix, in `app.main.create_app`.

T10 adds the `/v1/auth/sessions` list/revoke routes (session store +
`require_auth`, ADR-0006). T15 adds `/v1/auth/login`, `/refresh`, and
`/logout` (`app.api.auth`). T14 adds `/v1/auth/register`
(`app.api.auth`, invite redemption — depends on T13). T16 adds
`/v1/auth/password-reset`,
`/v1/auth/password-reset/confirm`, and `/v1/auth/password/change`
(`app.api.password`). T17 adds `/v1/me` (own profile — `GET`/`PATCH`).
T13 adds `/v1/invites*` (System Admin invite issuance/lifecycle,
`app.api.invites`, extended by T43 with the `GET /v1/invites` list read).
T18 adds `/v1/channels*` (create/get/public browse, `app.api.channels`).
T44 adds `/v1/admin/*` (System Admin user directory + deactivate/
reactivate, `app.api.admin`). T21 adds `/v1/channels/{id}/messages` +
`/v1/messages/{id}` (channel message send/edit/delete/history,
`app.api.messages`, persist-only — fan-out is T24).
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api import admin, auth, channels, health, invites, me, messages, password, sessions

api_router = APIRouter(prefix="/v1")
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(sessions.router)
api_router.include_router(password.router)
api_router.include_router(me.router)
api_router.include_router(invites.router)
api_router.include_router(channels.router)
api_router.include_router(messages.router)
api_router.include_router(admin.router)
