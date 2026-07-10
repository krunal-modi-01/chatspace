"""Per-connection WS frame-rate guard (T23, close code 4429).

A simple in-process sliding-window counter, deliberately **not** the
Redis-backed token bucket `app.core.redis_keys.RateLimitScope` describes
for REST message-send (T27's per-user limit across all of a user's
connections/requests) — this is a narrower, connection-local abuse guard
against a single misbehaving/compromised WS client hammering
`join`/`leave`/`typing`/`ping` frames. The two limits are independent and
both may apply.
"""

from __future__ import annotations

from collections import deque
from time import monotonic


class FrameRateLimiter:
    """Sliding-window frame counter for a single WS connection."""

    def __init__(self, *, max_frames: int, window_seconds: float) -> None:
        self._max_frames = max_frames
        self._window_seconds = window_seconds
        self._timestamps: deque[float] = deque()

    def record_and_check(self, *, now: float | None = None) -> bool:
        """Record one frame; return True iff the connection is over-limit.

        Evicts timestamps older than the window before counting, so the
        limit is a true sliding window rather than a fixed bucket reset.
        """

        current_time = now if now is not None else monotonic()
        self._timestamps.append(current_time)

        cutoff = current_time - self._window_seconds
        while self._timestamps and self._timestamps[0] < cutoff:
            self._timestamps.popleft()

        return len(self._timestamps) > self._max_frames
