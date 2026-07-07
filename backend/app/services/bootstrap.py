"""System Admin bootstrap (T12, ADR-0009, technical spec §10 Phase 0, FS F8/F9).

A startup routine, not a wire endpoint: when the `users` table is empty,
it creates exactly one **active** `is_system_admin` user from env-seeded
credentials (`Settings.bootstrap_admin_*`, pydantic-settings — never
hardcoded, never logged). It is idempotent on restart — re-running it
against a workspace that already has users never creates a duplicate —
and it is a Phase-0 **non-skippable** prerequisite: if it cannot
guarantee at least one active System Admin exists, it raises
`BootstrapError`, and `app.main.create_app`'s lifespan lets that
propagate so the process refuses to serve (mirrors
`app.services.email.verify_email_config`'s fail-loud posture, and is the
startup-side twin of the "last active System Admin" `409` guard in the
`POST /v1/admin/users/{user_id}/deactivate` contract, T20/F27).

Concurrency: two instances racing to bootstrap at once is handled by the
database, not application-level locking — `uq_users_username_lower` and
`uq_users_email_lower` (both case-insensitive unique indexes, frozen in
the initial migration) guarantee a second concurrent INSERT for the same
seeded identity fails with a Postgres unique-violation. That specific
failure is treated as "someone else already bootstrapped it" (a benign
race, not an error); any other integrity failure (e.g. a malformed
env-seeded username/name violating a CHECK constraint) is a genuine
misconfiguration and is re-raised as `BootstrapError` so startup fails
loudly instead of silently leaving the workspace without an admin. The
seeded password is likewise run through
`app.core.password_policy.enforce_password_policy` before the candidate
user is even constructed — the same rule every other password path
(register/change/reset) enforces — so a blank/weak
`BOOTSTRAP_ADMIN_PASSWORD` is a fail-loud misconfiguration, not a
silently-accepted standing credential.

Compensating control (ADR-0009): the seeded admin is created with
`must_change_password=True` (enforced at the login endpoint, out of
scope for this module — see T15) and `email_verified=True` (there is no
invite/registration flow to verify it against, so it is treated as
pre-verified).

Never logs `settings.bootstrap_admin_password` (a `SecretStr`, unwrapped
only for hashing) or `settings.bootstrap_admin_email` (PII) — log lines
from this module carry only the generated user id and a boolean outcome.
"""

from __future__ import annotations

import logging

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.ids import generate_id
from app.core.password_policy import PasswordPolicyError, enforce_password_policy
from app.core.security import hash_password
from app.models.user import User

logger = logging.getLogger(__name__)

# Postgres SQLSTATE for `unique_violation` (see PostgreSQL Appendix A).
# `asyncpg`'s exceptions (wrapped by SQLAlchemy as `IntegrityError.orig`)
# expose this via `.sqlstate`.
_UNIQUE_VIOLATION_SQLSTATE = "23505"


class BootstrapError(RuntimeError):
    """Raised when the workspace cannot be guaranteed to have an active
    System Admin at startup.

    `app.main`'s lifespan lets this propagate uncaught so the ASGI
    application never finishes starting up — "the app REFUSES to serve"
    per ADR-0009 — rather than booting into a zero-admin workspace.
    """


def _is_unique_violation(exc: IntegrityError) -> bool:
    sqlstate = getattr(exc.orig, "sqlstate", None)
    return sqlstate == _UNIQUE_VIOLATION_SQLSTATE


async def _active_system_admin_exists(session: AsyncSession) -> bool:
    stmt = select(
        select(User.id).where(User.is_system_admin.is_(True), User.is_active.is_(True)).exists()
    )
    return bool(await session.scalar(stmt))


async def ensure_system_admin_bootstrapped(session: AsyncSession, settings: Settings) -> None:
    """Guarantee the workspace has at least one active System Admin.

    Idempotent: a no-op when any user already exists (the ordinary case
    on every restart after the first). Only when the `users` table is
    completely empty does this create the env-seeded bootstrap admin.

    Raises `BootstrapError` if, after this call, no active System Admin
    exists — whether because the seeded credentials are malformed (a
    genuine configuration error) or because some other invariant was
    violated. Callers are expected to run this inside a transaction they
    control and to let `BootstrapError` abort application startup.
    """

    user_count = await session.scalar(select(func.count()).select_from(User))

    if user_count == 0:
        raw_password = settings.bootstrap_admin_password.get_secret_value()
        try:
            enforce_password_policy(raw_password)
        except PasswordPolicyError as exc:
            # A blank/weak env-seeded password is a genuine misconfiguration,
            # not a benign race — fail loudly instead of silently seeding an
            # admin account that bypasses the same policy every other
            # password path enforces (register/change/reset).
            raise BootstrapError(
                "System Admin bootstrap failed: BOOTSTRAP_ADMIN_PASSWORD does not meet "
                "the password policy. Check BOOTSTRAP_ADMIN_PASSWORD (minimum length, "
                "must contain at least one letter and one digit)."
            ) from exc

        candidate = User(
            id=generate_id(),
            username=settings.bootstrap_admin_username,
            email=settings.bootstrap_admin_email,
            hashed_password=hash_password(raw_password),
            first_name=settings.bootstrap_admin_first_name,
            last_name=settings.bootstrap_admin_last_name,
            is_active=True,
            is_system_admin=True,
            # ADR-0009 compensating control for a standing env-seeded
            # credential: the seeded admin must be forced to change their
            # password on first login, and is treated as pre-verified
            # since there is no invite/registration flow to verify it.
            must_change_password=True,
            email_verified=True,
        )
        session.add(candidate)
        try:
            await session.flush()
        except IntegrityError as exc:
            await session.rollback()
            if not _is_unique_violation(exc):
                # A genuine misconfiguration (e.g. a CHECK-constraint
                # violation on a blank/oversized seeded name/username) —
                # not a benign concurrent-bootstrap race. Fail loudly.
                raise BootstrapError(
                    "System Admin bootstrap failed: the env-seeded bootstrap "
                    "admin row violates a database constraint. Check "
                    "BOOTSTRAP_ADMIN_* env vars (username length/charset, "
                    "non-blank first/last name)."
                ) from exc
            # Unique violation: another instance/process won the race and
            # already inserted a user (almost certainly the same seeded
            # admin) between our count check and our insert. Idempotent
            # by design — fall through to the verification check below.
            logger.info(
                "system admin bootstrap skipped: concurrent bootstrap already inserted a user",
            )
        else:
            logger.info(
                "system admin bootstrap created the first System Admin",
                extra={"user_id": str(candidate.id)},
            )
    else:
        logger.info(
            "system admin bootstrap skipped: users already exist",
            extra={"user_count": user_count},
        )

    if not await _active_system_admin_exists(session):
        raise BootstrapError(
            "No active System Admin exists and bootstrap could not create one — "
            "refusing to serve (ADR-0009: workspace can never reach a zero-admin "
            "state at startup)."
        )
