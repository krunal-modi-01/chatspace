"""Pydantic response schemas for `/v1/auth/sessions` (frozen contract).

Schema (verbatim from the contract):

    { items: [ { session_id, created_at, last_seen_at, device_label,
                 current: bool } ] }

"never any token material" — no field here ever carries
`refresh_token`/`refresh_token_hash` or any other secret.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class SessionSummary(BaseModel):
    """One row of `GET /v1/auth/sessions`.

    `created_at` maps from `sessions.issued_at` and `last_seen_at` from
    `sessions.last_used_at` — the contract's field names for this endpoint
    differ from the underlying column names (see database design doc).
    `device_label` is derived from `sessions.user_agent` (no dedicated
    user-agent-parsing dependency is in scope for T10); it is `None` when
    no user agent was recorded at session creation.
    """

    model_config = ConfigDict(from_attributes=True)

    session_id: UUID
    created_at: datetime
    last_seen_at: datetime | None
    device_label: str | None
    current: bool


class SessionListResponse(BaseModel):
    """`GET /v1/auth/sessions` `200` envelope."""

    items: list[SessionSummary]
