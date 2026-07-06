"""Liveness and readiness endpoints.

These are operational routes, not governed by the frozen business API
contract (which defines no health/readiness endpoints). They live under
the `/v1` base path per the skeleton's single base-path convention, but
return plain JSON — not `application/problem+json` — on success, since
they are outside the versioned business contract.
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.services.readiness import ReadinessStatus, check_database, check_redis

router = APIRouter(tags=["health"])


@router.get("/healthz", summary="Liveness probe")
async def healthz() -> dict[str, str]:
    """Return 200 as long as the process is up and able to handle requests.

    This does not check downstream dependencies — see `/readyz` for that.
    """

    return {"status": "ok"}


@router.get("/readyz", summary="Readiness probe")
async def readyz() -> JSONResponse:
    """Aggregate downstream dependency readiness.

    Both checks are real: Postgres (T03, a bounded `SELECT 1` against the
    async engine) and Redis (T05, a bounded `PING` against the shared
    async client). Either dependency being unreachable degrades this
    endpoint's response — it never crashes the process.

    Returns HTTP 200 when ready and 503 when any dependency is
    `UNAVAILABLE`, so a load balancer / orchestrator can gate traffic on
    the status code (not just the body).
    """

    checks = [await check_database(), await check_redis()]
    overall_ok = all(check.status != ReadinessStatus.UNAVAILABLE for check in checks)

    body = {
        "status": "ok" if overall_ok else "unavailable",
        "checks": [
            {"name": check.name, "status": check.status.value, "detail": check.detail}
            for check in checks
        ],
    }
    return JSONResponse(status_code=200 if overall_ok else 503, content=body)
