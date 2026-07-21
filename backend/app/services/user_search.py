"""Workspace user-directory search (T73, F76/R59, ADR-0016).

Backs `GET /v1/users/search` — the scoped, minimal-field directory read
that fronts the channel member-picker (F32/F33) and the DM "new message"
picker (F46, ADR-0017). Deliberately distinct from
`app.services.admin_users.list_admin_users` (`GET /v1/admin/users`,
System-Admin-only, includes deactivated users and account fields): this
search excludes deactivated users by default and the caller
(`app.api.users`) only ever projects the result through
`app.schemas.user_search.UserSearchItem`, which can never carry
`email`/`is_active`/`last_seen`/`role`.

Query-pattern / pagination note (frozen database design, "T73" section):
`users` has no index on `first_name`/`last_name` and no trigram/prefix
index, so a case-insensitive substring match across
`username`/`first_name`/`last_name` is a sequential scan — acceptable at
v1 scale (~1,000 rows, "fully cacheable"/"fits in memory" per the
Performance section; constitution #7, "model for 1,000 users, not 1M").
No new index is added for this. Because the search predicate already
forces a seq scan, and `users` carries no index on `created_at`, the
keyset here orders by `id` alone (`WHERE id > :cursor ORDER BY id`,
served by `users_pkey`) rather than reusing
`app.core.pagination.apply_keyset`'s generic `(created_at, id)` tuple
keyset (which backs message/DM/invite/admin-user history and assumes a
`created_at`-ordered index) — `id` is a UUIDv7, already time-sortable, so
a single-column ascending keyset on the PK is both correct and stable.
The opaque cursor *encoding* is still `app.core.pagination.encode_cursor`/
`decode_cursor` (same `(created_at, id)` payload shape as everywhere else
in the app, per ADR-0003) — only the `id`-half of a decoded cursor is
used to build the `WHERE` predicate; `created_at` is carried through
solely so cursors keep one consistent binary shape workspace-wide.
"""

from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pagination import CursorKey, Page, paginate_rows
from app.models.user import User


def _escape_like(value: str) -> str:
    """Escape `%`/`_`/backslash so a search term can't smuggle SQL `LIKE` wildcards.

    Not a security boundary in the injection sense (the value is already
    bound as a parameter) — purely so a search for a literal `%` or `_`
    in a name/username behaves as the caller expects rather than matching
    everything. Mirrors `app.services.admin_users._escape_like` exactly.
    """

    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def search_users(
    db: AsyncSession,
    *,
    q: str,
    limit: int,
    cursor: CursorKey | None = None,
) -> Page[User]:
    """Cursor-paginated, case-insensitive user-directory search.

    `q` must already be validated non-empty (stripped) by the caller
    (`app.api.users`) — the contract's "min length 1" rule. Matches
    `username`/`first_name`/`last_name`, any substring, case-insensitive.
    Excludes deactivated users (`is_active = true`) by default — this
    function has no "include deactivated" escape hatch, unlike
    `list_admin_users`, since the frozen contract for this endpoint never
    exposes that toggle. `limit` must already be resolved/clamped by the
    caller (`app.core.pagination.resolve_limit`).
    """

    pattern = f"%{_escape_like(q)}%"

    stmt = (
        select(User)
        .where(
            User.is_active.is_(True),
            or_(
                User.username.ilike(pattern, escape="\\"),
                User.first_name.ilike(pattern, escape="\\"),
                User.last_name.ilike(pattern, escape="\\"),
            ),
        )
        .order_by(User.id.asc())
    )

    if cursor is not None:
        stmt = stmt.where(User.id > cursor.id)

    stmt = stmt.limit(limit + 1)

    result = await db.execute(stmt)
    rows = list(result.scalars().all())
    return paginate_rows(
        rows,
        limit=limit,
        cursor_key=lambda user: CursorKey(created_at=user.created_at, id=user.id),
    )
