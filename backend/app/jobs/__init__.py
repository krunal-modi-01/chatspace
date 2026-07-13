"""Standalone, externally-scheduled maintenance jobs (T28).

Not wired into the FastAPI app's own process/lifespan -- each module here
is a small `python -m app.jobs.<name>` entrypoint that opens its own
short-lived DB/S3 clients, does one unit of work, and exits.
`infrastructure-engineer` wires the actual periodic invocation (host cron
/ platform scheduled task) per CLAUDE.md's single-Docker-host deployment
target -- no in-process scheduler library is introduced for this.
"""

from __future__ import annotations
