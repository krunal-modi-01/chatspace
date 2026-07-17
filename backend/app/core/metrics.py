"""In-process, dependency-free metrics registry (T39, technical spec §9).

CLAUDE.md's constitution deliberately rejects a full metrics stack at
chatspace's 1,000-user scale ("no need for a full metrics stack unless
usage grows materially") — so this is a small, in-memory counter/gauge/
histogram registry, not a Prometheus client or any other new dependency.
It is scraped by `GET /v1/internal/metrics` (`app.api.metrics`, operator-
only) for an external dashboard/alerting tool to poll; see
`docs/observability/alerts.yaml` for the symptom-based alert definitions
that consume these signals.

Covers every metric the technical spec names (§9): active WebSocket
connections, message send throughput/error rate, the real-time delivery
lag SLI, `429` counts by scope, presence online/offline transitions,
media upload success/reject, email send success/failure, DB pool
saturation, and Redis availability. Instrumentation call sites live next
to the code they measure (`app.ws.connection_manager`, `app.ws.fanout`,
`app.api.messages`, `app.api.media`, `app.services.email`,
`app.services.presence`, `app.core.errors`, `app.api.metrics`) — this
module only owns the registry itself.

**Content-free by construction (F68/SEC):** label *values* passed to
`increment_counter`/`set_gauge`/`observe_histogram` must always come from
a small, fixed vocabulary the caller controls (a conversation kind, an
HTTP status code, a rate-limit scope, a media kind, an error class name)
— never a raw id, email, username, or message content. This module does
not itself scrub labels (unlike `app.core.redact`'s log formatter): it is
the caller's responsibility never to pass a sensitive value in here,
exactly as documented at each instrumentation call site.

**Per-instance only.** Like `app.ws.connection_manager.connection_manager`,
this registry is process-local — chatspace runs 1-2 app instances
(CLAUDE.md) and does not aggregate metrics across them; an external
dashboard scraping `/v1/internal/metrics` from every instance is expected
to sum/merge as needed. Not safe to share across processes.
"""

from __future__ import annotations

import threading
from collections import deque
from typing import Any

# Guards every registry mutation. Metrics call sites run inside a single
# asyncio event loop per process (no real contention), but a background
# job (`app.jobs.media_orphan_sweep`) or a future thread-based caller could
# touch this concurrently — cheap insurance, never held across an await.
_LOCK = threading.Lock()

# Bounds memory for a histogram's per-label-combination sample buffer. Old
# samples are dropped (deque maxlen) rather than the histogram growing
# unbounded for the life of the process.
_HISTOGRAM_MAX_SAMPLES = 2000

LabelKey = tuple[tuple[str, str], ...]


def _label_key(labels: dict[str, str]) -> LabelKey:
    return tuple(sorted(labels.items()))


def _format_label_key(key: LabelKey) -> str:
    if not key:
        return "_total"
    return ",".join(f"{name}={value}" for name, value in key)


def _percentiles(sorted_values: list[float]) -> dict[str, float]:
    if not sorted_values:
        return {"count": 0, "p50": 0.0, "p95": 0.0, "p99": 0.0, "max": 0.0}

    def _pct(p: float) -> float:
        index = min(len(sorted_values) - 1, int(round(p * (len(sorted_values) - 1))))
        return sorted_values[index]

    return {
        "count": len(sorted_values),
        "p50": _pct(0.50),
        "p95": _pct(0.95),
        "p99": _pct(0.99),
        "max": sorted_values[-1],
    }


class MetricsRegistry:
    """Process-wide counters, gauges, and lightweight histograms.

    Not a singleton by class design (tests construct their own instances
    to assert in isolation) — `get_metrics_registry()` below returns the
    one process-wide instance every non-test call site should use.
    """

    def __init__(self) -> None:
        self._counters: dict[str, dict[LabelKey, int]] = {}
        self._gauges: dict[str, dict[LabelKey, float]] = {}
        self._histograms: dict[str, dict[LabelKey, deque[float]]] = {}

    def increment_counter(self, name: str, *, by: int = 1, **labels: str) -> None:
        key = _label_key(labels)
        with _LOCK:
            bucket = self._counters.setdefault(name, {})
            bucket[key] = bucket.get(key, 0) + by

    def set_gauge(self, name: str, value: float, **labels: str) -> None:
        key = _label_key(labels)
        with _LOCK:
            self._gauges.setdefault(name, {})[key] = value

    def observe_histogram(self, name: str, value: float, **labels: str) -> None:
        key = _label_key(labels)
        with _LOCK:
            bucket = self._histograms.setdefault(name, {})
            samples = bucket.setdefault(key, deque(maxlen=_HISTOGRAM_MAX_SAMPLES))
            samples.append(value)

    def snapshot(self) -> dict[str, Any]:
        """A plain-JSON-serializable snapshot of every recorded metric."""

        with _LOCK:
            counters = {
                name: {_format_label_key(key): value for key, value in bucket.items()}
                for name, bucket in self._counters.items()
            }
            gauges = {
                name: {_format_label_key(key): value for key, value in bucket.items()}
                for name, bucket in self._gauges.items()
            }
            histograms = {
                name: {
                    _format_label_key(key): _percentiles(sorted(samples))
                    for key, samples in bucket.items()
                }
                for name, bucket in self._histograms.items()
            }
        return {"counters": counters, "gauges": gauges, "histograms": histograms}

    def reset(self) -> None:
        """Test-only: clear every recorded counter/gauge/histogram."""

        with _LOCK:
            self._counters.clear()
            self._gauges.clear()
            self._histograms.clear()


_REGISTRY = MetricsRegistry()


def get_metrics_registry() -> MetricsRegistry:
    """The one process-wide registry every non-test call site should use."""

    return _REGISTRY


def increment_counter(name: str, *, by: int = 1, **labels: str) -> None:
    _REGISTRY.increment_counter(name, by=by, **labels)


def set_gauge(name: str, value: float, **labels: str) -> None:
    _REGISTRY.set_gauge(name, value, **labels)


def observe_histogram(name: str, value: float, **labels: str) -> None:
    _REGISTRY.observe_histogram(name, value, **labels)


def snapshot() -> dict[str, Any]:
    return _REGISTRY.snapshot()


def reset_metrics() -> None:
    """Test-only: clear the process-wide registry between test cases."""

    _REGISTRY.reset()
