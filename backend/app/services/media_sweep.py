"""Orphan-sweep job: remove unbound `attachments` rows + purge their object bytes (T28, F62).

F62: "orphaned media (parent message-create never completed) is cleaned
up." An attachment becomes orphaned when its upload (`POST /v1/media`)
never gets bound to a message (`message_id` stays `NULL` forever -- the
client abandoned the two-phase flow, crashed, or the message-create call
simply never happened).

Query shape mirrors the shipped partial index exactly: `ix_attachments_orphans`
is `(created_at) WHERE message_id IS NULL`, so `sweep_orphaned_media`'s
`WHERE message_id IS NULL AND created_at < :cutoff` hits that index rather
than a sequential scan.

## Ordering: purge object bytes *before* deleting the metadata row

A Postgres `DELETE`/CASCADE never touches the object store (the database
design doc is explicit: "CASCADE/DB delete does not touch object storage
-- the reaper must purge bytes"). This sweep purges the S3 object first
and only deletes the Postgres row once that purge succeeds: if the purge
fails (object store outage), the row is left in place so the *next* sweep
run retries it -- rather than deleting the metadata and leaking bytes in
the bucket with no remaining record to ever find and delete them again.
The tradeoff is that a row can, in the failure case, outlive its nominal
TTL by one or more sweep intervals; that is preferable to an unbounded,
untracked storage leak.

## Orphan TTL (Open Q1 -- flagged, not yet an architect-confirmed value)

The frozen contract/database design call out the orphan TTL as an open
policy question ("Orphan-TTL value is an open policy question (Open Q1)
-- pick a default and flag it"). `DEFAULT_ORPHAN_TTL` picks 24 hours as a
generous default: a legitimate two-phase upload normally binds within
seconds, so 24h comfortably covers a slow/flaky client without
prematurely sweeping a still-in-flight upload, while not leaving orphaned
bytes billed/stored indefinitely. This should be confirmed by the
architect/product owner and, ideally, coordinated with the bucket's own
lifecycle policy (ADR-0007's "coordinate TTL with the bucket lifecycle
policy" follow-up) -- `infrastructure-engineer` scope, not done here.

## Invocation

No in-process scheduler exists in this codebase (CLAUDE.md: single Docker
host / small managed platform, no k8s -- a k8s CronJob is out of scope,
and adding a new scheduling *library* dependency (e.g. APScheduler) for a
single periodic job is unwarranted complexity at this scale). This module
exposes `sweep_orphaned_media` as a plain importable async function; a
minimal CLI entrypoint (`app.jobs.media_orphan_sweep`, `python -m
app.jobs.media_orphan_sweep`) wraps it for `infrastructure-engineer` to
wire onto a host cron / platform scheduled-task facility.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy import delete, select
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.attachment import Attachment
from app.services.media_storage import MediaStorageError, delete_object

logger = logging.getLogger(__name__)

# See module docstring's "Orphan TTL" section -- an explicitly flagged
# default, not a confirmed architecture decision.
DEFAULT_ORPHAN_TTL = timedelta(hours=24)

# Bounds how many orphan rows a single sweep call processes, so one run
# never holds a long-lived transaction or an unbounded result set against
# a pathologically large backlog -- a subsequent scheduled run picks up
# whatever is left.
DEFAULT_BATCH_SIZE = 500


@dataclass(frozen=True, slots=True)
class SweepResult:
    """Summary of one sweep call -- counts only, no filenames/ids (audit-safe log shape)."""

    scanned: int
    purged: int
    purge_failures: int


async def sweep_orphaned_media(
    db: AsyncSession,
    s3_client: Any,
    *,
    ttl: timedelta = DEFAULT_ORPHAN_TTL,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> SweepResult:
    """Delete unbound `attachments` rows older than `ttl`, purging their object bytes first.

    Safe to call repeatedly/concurrently at low frequency (e.g. hourly
    cron): a row already purged and deleted by a prior/concurrent run
    simply will not be found again. Never raises on an individual purge
    failure -- it logs and leaves that row for the next run (see module
    docstring) so one bad object doesn't abort the whole batch.

    Race safety (T28 code review Major #2): the initial `SELECT` snapshots
    candidate rows into Python objects, but a row can be concurrently bound
    to a message (`app.services.messages._bind_media_atomically`'s
    `UPDATE ... WHERE id = ANY(...) AND message_id IS NULL`) between that
    snapshot and this function reaching it in the loop -- a legitimately
    slow/late client can still complete its two-phase upload while an
    eligible row sits in a sweep's in-memory batch. Purging the object
    bytes first (see "Ordering" above) means a bare re-check right before
    the `DELETE` is not sufficient on its own -- the bytes a concurrently
    bound message now references could already be gone by the time that
    check runs. Instead, immediately before touching the object store for
    each row, this re-selects that *specific* row with `SELECT ... FOR
    UPDATE`, re-verifying `message_id IS NULL` under a row lock held for
    the rest of this transaction: `_bind_media_atomically`'s `UPDATE`
    targeting the same row blocks until this transaction commits (at the
    end of the batch) or a prior row's failed purge lets it fall through
    to the next iteration, and by the time our lock is granted, Postgres
    re-evaluates the `WHERE` clause against the now-current row -- so a
    concurrent bind that already landed is detected here and that row is
    skipped entirely (no purge, no delete). The `DELETE` itself is still
    issued with the same `message_id IS NULL` condition as defense in
    depth, matching the guard `_bind_media_atomically` applies on the other
    side of the race.
    """

    cutoff = datetime.now(UTC) - ttl
    settings = get_settings()

    result = await db.execute(
        select(Attachment)
        .where(Attachment.message_id.is_(None), Attachment.created_at < cutoff)
        .limit(batch_size)
    )
    rows = list(result.scalars().all())

    purged = 0
    purge_failures = 0
    for attachment in rows:
        # Re-check + lock this specific row immediately before purging its
        # object bytes -- guards against a concurrent
        # `_bind_media_atomically` bind that landed after the batch scan
        # above (see "Race safety" in this function's docstring).
        still_orphaned = await db.execute(
            select(Attachment.id)
            .where(Attachment.id == attachment.id, Attachment.message_id.is_(None))
            .with_for_update()
        )
        if still_orphaned.scalar_one_or_none() is None:
            logger.info(
                "orphan sweep: row was bound concurrently since the batch scan; skipping",
                extra={"media_id": str(attachment.id)},
            )
            continue

        try:
            await delete_object(
                s3_client, bucket=settings.s3_bucket_name, key=attachment.storage_key
            )
        except MediaStorageError:
            purge_failures += 1
            logger.error(
                "orphan sweep: failed to purge object bytes; row retained for next run",
                extra={"media_id": str(attachment.id)},
            )
            continue

        delete_result = cast(
            CursorResult[Any],
            await db.execute(
                delete(Attachment).where(
                    Attachment.id == attachment.id, Attachment.message_id.is_(None)
                )
            ),
        )
        if delete_result.rowcount:
            purged += 1
        else:
            # Should be unreachable given the `FOR UPDATE` lock taken above
            # (nothing else can have changed `message_id` on this row since)
            # -- defense in depth only, logged since it would mean the
            # object bytes were just purged out from under a bound message.
            logger.error(
                "orphan sweep: row bound after lock was taken; object bytes already purged",
                extra={"media_id": str(attachment.id)},
            )

    await db.commit()

    logger.info(
        "orphan sweep completed",
        extra={"scanned": len(rows), "purged": purged, "purge_failures": purge_failures},
    )
    return SweepResult(scanned=len(rows), purged=purged, purge_failures=purge_failures)
