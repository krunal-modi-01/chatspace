"""`GET /v1/internal/metrics` — operator observability snapshot (T39).

Like `app.api.health`'s `/healthz`/`/readyz`, this is an operational
route, not part of the frozen business API contract (no REST/WS surface
for it exists in `docs/spec/chatspace-v1-api-contract.md`). Backs the
symptom-based alert definitions in `docs/observability/alerts.yaml` (an
external dashboard/alerting tool polls this endpoint) and exposes every
key metric the technical spec (§9) names: active WebSocket connections,
message send throughput/error rate, the delivery-lag SLI, `429` counts by
endpoint class, presence online/offline transitions, media upload
success/reject, email send success/failure, DB pool saturation, and
Redis availability.

Gated behind `require_system_admin` (least privilege, CLAUDE.md): the
payload never carries PII/secrets/message content (see
`app.core.metrics`'s content-free labeling contract), but operational
counts/gauges are still internal detail, not meant for anonymous/public
consumption — unlike `/healthz`/`/readyz`, nothing external (a load
balancer) needs this endpoint unauthenticated.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends

from app.core.deps import AuthenticatedUser, require_system_admin
from app.core.metrics import snapshot as metrics_snapshot
from app.db.session import get_engine
from app.services.readiness import ReadinessStatus, check_redis

router = APIRouter(tags=["observability"])

_SystemAdmin = Annotated[AuthenticatedUser, Depends(require_system_admin)]


def _db_pool_snapshot() -> dict[str, int]:
    """Key metric (technical spec §9): "DB pool saturation".

    `AsyncEngine.pool` proxies the underlying sync `Pool`'s introspection
    methods (`size`/`checkedout`/`overflow`) — a pure in-memory read, no
    network round-trip, so this never itself risks hanging the endpoint
    the way a real DB probe would (`app.services.readiness.check_database`
    already covers that case for `/readyz`).
    """

    pool = get_engine().pool
    # `Pool`'s base class doesn't declare these (they live on the
    # `QueuePool`/`AsyncAdaptedQueuePool` subclass `app.db.engine` actually
    # configures -- see that module's `create_async_engine` call), so
    # mypy's static type for `.pool` doesn't know about them.
    return {
        "size": pool.size(),  # type: ignore[attr-defined]
        "checked_out": pool.checkedout(),  # type: ignore[attr-defined]
        "overflow": pool.overflow(),  # type: ignore[attr-defined]
    }


@router.get("/internal/metrics")
async def get_metrics(admin: _SystemAdmin) -> dict[str, Any]:
    del admin  # dependency enforces the gate; no further use of the identity

    redis_check = await check_redis()

    body = metrics_snapshot()
    body["db_pool"] = _db_pool_snapshot()
    # Key metric (technical spec §9): "Redis availability".
    body["redis_available"] = redis_check.status == ReadinessStatus.OK
    return body
