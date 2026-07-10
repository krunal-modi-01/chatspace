"""The `/v1/ws` close-code catalogue (T23, F52/F70).

Every value here — and only these values — may be used to close a
`/v1/ws` connection. Must match the frozen API contract's close-code
table **exactly** (code, name, and trigger); do not add, rename, or
repurpose a code without routing the change through the api-reviewer.

| Code | Reason             | Trigger                                            |
|------|--------------------|-----------------------------------------------------|
| 1000 | normal closure     | client closed cleanly                              |
| 1001 | going away         | server shutdown / instance drain                   |
| 4401 | auth-failed        | missing/invalid/expired token at connect           |
| 4402 | token-expired      | access token expired mid-connection                |
| 4403 | token-revoked      | session revoked via logout / password change/reset |
| 4404 | user-deactivated   | target user deactivated by System Admin            |
| 4408 | heartbeat-timeout  | heartbeats stopped; connection reaped              |
| 4429 | rate-limited       | abusive frame rate                                 |
"""

from __future__ import annotations

from enum import IntEnum


class WSCloseCode(IntEnum):
    """WebSocket close codes used by `/v1/ws` (contract-exact)."""

    NORMAL_CLOSURE = 1000
    GOING_AWAY = 1001
    AUTH_FAILED = 4401
    TOKEN_EXPIRED = 4402
    TOKEN_REVOKED = 4403
    USER_DEACTIVATED = 4404
    HEARTBEAT_TIMEOUT = 4408
    RATE_LIMITED = 4429
