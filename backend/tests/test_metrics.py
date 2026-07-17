"""Unit tests for `app.core.metrics` (T39, technical spec §9).

Pure in-memory registry assertions — no Postgres/Redis needed.
"""

from __future__ import annotations

from app.core.metrics import MetricsRegistry


class TestCounters:
    def test_increment_defaults_to_one(self) -> None:
        registry = MetricsRegistry()
        registry.increment_counter("widgets_total")
        registry.increment_counter("widgets_total")

        snapshot = registry.snapshot()
        assert snapshot["counters"]["widgets_total"]["_total"] == 2

    def test_increment_by_custom_amount(self) -> None:
        registry = MetricsRegistry()
        registry.increment_counter("widgets_total", by=5)

        assert registry.snapshot()["counters"]["widgets_total"]["_total"] == 5

    def test_labels_are_tracked_independently(self) -> None:
        registry = MetricsRegistry()
        registry.increment_counter("message_send_error_total", conversation_kind="channel")
        registry.increment_counter("message_send_error_total", conversation_kind="channel")
        registry.increment_counter("message_send_error_total", conversation_kind="dm")

        bucket = registry.snapshot()["counters"]["message_send_error_total"]
        assert bucket["conversation_kind=channel"] == 2
        assert bucket["conversation_kind=dm"] == 1

    def test_label_order_is_normalized(self) -> None:
        """Two calls with the same label set in different kwarg order must
        collide onto the same bucket, not create two separate entries.
        """

        registry = MetricsRegistry()
        registry.increment_counter("x", a="1", b="2")
        registry.increment_counter("x", b="2", a="1")

        bucket = registry.snapshot()["counters"]["x"]
        assert len(bucket) == 1
        assert next(iter(bucket.values())) == 2


class TestGauges:
    def test_set_overwrites_not_accumulates(self) -> None:
        registry = MetricsRegistry()
        registry.set_gauge("ws_active_connections", 3)
        registry.set_gauge("ws_active_connections", 7)

        assert registry.snapshot()["gauges"]["ws_active_connections"]["_total"] == 7

    def test_gauge_can_go_down(self) -> None:
        registry = MetricsRegistry()
        registry.set_gauge("ws_active_connections", 3)
        registry.set_gauge("ws_active_connections", 0)

        assert registry.snapshot()["gauges"]["ws_active_connections"]["_total"] == 0


class TestHistograms:
    def test_percentiles_over_a_known_distribution(self) -> None:
        registry = MetricsRegistry()
        for value in range(1, 101):  # 1..100
            registry.observe_histogram("message_delivery_lag_ms", float(value))

        stats = registry.snapshot()["histograms"]["message_delivery_lag_ms"]["_total"]
        assert stats["count"] == 100
        assert stats["max"] == 100.0
        # p50/p95/p99 should land near the expected rank, not exactly at the
        # textbook value (nearest-rank on a 0-indexed sorted list).
        assert 48 <= stats["p50"] <= 52
        assert 93 <= stats["p95"] <= 97
        assert 97 <= stats["p99"] <= 100

    def test_empty_histogram_reports_zeroed_stats_not_a_crash(self) -> None:
        registry = MetricsRegistry()

        stats = registry.snapshot()["histograms"]
        assert stats == {}

    def test_bounded_sample_buffer_drops_oldest(self) -> None:
        registry = MetricsRegistry()
        for value in range(3000):
            registry.observe_histogram("x", float(value))

        stats = registry.snapshot()["histograms"]["x"]["_total"]
        # Bounded at 2000 samples; the buffer keeps the most recent ones.
        assert stats["count"] == 2000
        assert stats["max"] == 2999.0


class TestSnapshotIsolation:
    def test_reset_clears_everything(self) -> None:
        registry = MetricsRegistry()
        registry.increment_counter("a")
        registry.set_gauge("b", 1)
        registry.observe_histogram("c", 1.0)

        registry.reset()

        snapshot = registry.snapshot()
        assert snapshot == {"counters": {}, "gauges": {}, "histograms": {}}

    def test_snapshot_is_json_serializable(self) -> None:
        import json

        registry = MetricsRegistry()
        registry.increment_counter("a", label="x")
        registry.set_gauge("b", 1.5)
        registry.observe_histogram("c", 2.0)

        json.dumps(registry.snapshot())


class TestModuleLevelConvenienceFunctions:
    """The module-level `increment_counter`/`set_gauge`/`observe_histogram`
    helpers bind to the one process-wide registry — reset it before/after
    so this test doesn't leak state into other tests in the same process.
    """

    def test_module_functions_use_the_shared_registry(self) -> None:
        from app.core import metrics as metrics_module

        metrics_module.reset_metrics()
        try:
            metrics_module.increment_counter("shared_total")
            snapshot = metrics_module.snapshot()
            assert snapshot["counters"]["shared_total"]["_total"] == 1
        finally:
            metrics_module.reset_metrics()
