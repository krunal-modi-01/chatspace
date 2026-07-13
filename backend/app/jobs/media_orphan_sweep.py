"""CLI entrypoint: `python -m app.jobs.media_orphan_sweep` (T28, F62).

Runs one `app.services.media_sweep.sweep_orphaned_media` pass against the
process's configured Postgres/S3 and exits. Intended to be invoked
periodically by an external scheduler (host cron, or the deploy
platform's scheduled-task facility) -- see `app.services.media_sweep`'s
module docstring and `app.jobs`'s package docstring for why no
in-process scheduler is wired here.

Exit code is `0` on a clean pass (including zero rows found) and `1` if
the pass raised -- so a wrapping cron/systemd-timer/platform job can
alert on failure via the process exit status alone, without parsing logs.
"""

from __future__ import annotations

import asyncio
import logging
import sys

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import dispose_engine, get_sessionmaker
from app.db.storage import get_s3_client
from app.services.media_sweep import sweep_orphaned_media

logger = logging.getLogger(__name__)


async def _run() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)

    session_factory = get_sessionmaker()
    s3_client = get_s3_client()

    async with session_factory() as db:
        await sweep_orphaned_media(db, s3_client)

    await dispose_engine()


def main() -> int:
    try:
        asyncio.run(_run())
    except Exception:
        logger.exception("media orphan sweep failed")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
