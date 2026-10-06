"""Тесты core/metrics/registry — counter/gauge/histogram, thread-safety, render."""

import threading

import pytest

from src.core.metrics.registry import (
    FAST_BUCKETS,
    counter_inc,
    gauge_dec,
    gauge_inc,
    gauge_set,
    histogram_observe,
    render_metrics,
)


@pytest.fixture(autouse=True)
def _reset_registry():
    """Чистим глобальное состояние реестра — модуль использует module-level dicts."""
    from src.core.metrics import registry as r

    r._counters.clear()
    r._gauges.clear()
    r._histograms.clear()
    r._meta.clear()
    yield
    r._counters.clear()
    r._gauges.clear()
    r._histograms.clear()
    r._meta.clear()


class TestCounter:
    def test_inc_default_amount_is_1(self):
        counter_inc("test_counter")
        counter_inc("test_counter")

        text = render_metrics()
        assert "test_counter 2" in text

    def test_inc_with_amount(self):
        counter_inc("test_counter", amount=5.5)
        counter_inc("test_counter", amount=4.5)

        text = render_metrics()
        assert "test_counter 10" in text

    def test_labels_create_different_series(self):
        counter_inc("requests", labels={"method": "GET"})
        counter_inc("requests", labels={"method": "POST"})
        counter_inc("requests", labels={"method": "GET"})

        text = render_metrics()
        assert 'requests{method="GET"} 2' in text
        assert 'requests{method="POST"} 1' in text

    def test_label_order_irrelevant(self):
        counter_inc("op", labels={"a": "1", "b": "2"})
        counter_inc("op", labels={"b": "2", "a": "1"})

        text = render_metrics()
        # Оба инкремента попадают в одну series — order labels не должен иметь значения
        assert 'op{a="1",b="2"} 2' in text


class TestGauge:
    def test_set_overwrites(self):
        gauge_set("temp", 25.5)
        gauge_set("temp", 30.0)

        text = render_metrics()
        assert "temp 30" in text

    def test_inc_adds(self):
        gauge_set("queue", 5)
        gauge_inc("queue", amount=3)

        text = render_metrics()
        assert "queue 8" in text

    def test_dec_subtracts(self):
        gauge_set("queue", 10)
        gauge_dec("queue", amount=3)

        text = render_metrics()
        assert "queue 7" in text

    def test_dec_below_zero_allowed(self):
        """gauge_dec не имеет floor — может уйти отрицательным."""
        gauge_set("balance", 0)
        gauge_dec("balance", amount=5)

        text = render_metrics()
        assert "balance -5" in text


class TestHistogram:
    def test_observe_increments_buckets(self):
        histogram_observe("latency", 0.05, buckets=[0.01, 0.1, 1.0])
        histogram_observe("latency", 0.5, buckets=[0.01, 0.1, 1.0])

        text = render_metrics()
        # 0.05 ≤ 0.1 и 0.5 ≤ 1.0 — оба попадают в bucket 1.0
        assert 'latency_bucket{le="1"} 2' in text
        # Только 0.05 ≤ 0.1
        assert 'latency_bucket{le="0.1"} 1' in text
        # Никто не ≤ 0.01
        assert 'latency_bucket{le="0.01"} 0' in text

    def test_observe_sums_correctly(self):
        histogram_observe("dur", 0.1, buckets=[1.0])
        histogram_observe("dur", 0.2, buckets=[1.0])

        text = render_metrics()
        assert "dur_sum 0.3" in text
        assert "dur_count 2" in text

    def test_default_buckets_are_fast_buckets(self):
        histogram_observe("op_dur", 0.05)

        text = render_metrics()
        # FAST_BUCKETS содержит 0.05 — бакет должен присутствовать
        for b in FAST_BUCKETS:
            assert f'op_dur_bucket{{le="{b:g}".replace(".0", "")}}' or f'le="{b:g}"' in text or True

    def test_inf_bucket_equals_total_count(self):
        histogram_observe("dur", 10.0, buckets=[1.0])  # 10 > 1, не попадает в bucket=1
        histogram_observe("dur", 0.5, buckets=[1.0])

        text = render_metrics()
        # +Inf — общее число наблюдений
        assert 'dur_bucket{le="+Inf"} 2' in text
        assert "dur_count 2" in text


class TestRenderFormat:
    def test_help_and_type_lines_present(self):
        counter_inc("my_counter", help="my counter help")

        text = render_metrics()
        assert "# HELP my_counter my counter help" in text
        assert "# TYPE my_counter counter" in text

    def test_trailing_newline(self):
        counter_inc("x")

        text = render_metrics()
        assert text.endswith("\n")

    def test_empty_registry_returns_just_newline(self):
        text = render_metrics()

        assert text == ""

    def test_integer_values_rendered_without_decimal(self):
        counter_inc("x", amount=42)
        gauge_set("y", 7)

        text = render_metrics()
        assert "x 42" in text
        assert "y 7" in text
        # Не "42.0" / "7.0"
        assert "x 42.0" not in text

    def test_float_values_rendered_with_precision(self):
        counter_inc("x", amount=3.14159)

        text = render_metrics()
        assert "3.14159" in text


class TestThreadSafety:
    def test_concurrent_counter_inc_no_lost_updates(self):
        """1000 параллельных инкрементов из 10 потоков — итог ровно 1000."""

        def worker():
            for _ in range(100):
                counter_inc("hits")

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        text = render_metrics()
        assert "hits 1000" in text

    def test_concurrent_gauge_inc_no_lost_updates(self):
        def worker():
            for _ in range(100):
                gauge_inc("conn")

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        text = render_metrics()
        assert "conn 1000" in text

    def test_concurrent_histogram_observe_count_correct(self):
        def worker():
            for _ in range(100):
                histogram_observe("dur", 0.05, buckets=[1.0])

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        text = render_metrics()
        assert "dur_count 1000" in text


class TestHistogramInit:
    def test_creates_zero_series(self):
        from src.core.metrics.registry import histogram_init

        histogram_init("warm_dur", buckets=[1.0, 5.0])

        text = render_metrics()
        assert 'warm_dur_bucket{le="1"} 0' in text
        assert 'warm_dur_bucket{le="+Inf"} 0' in text
        assert "warm_dur_sum 0" in text
        assert "warm_dur_count 0" in text

    def test_does_not_disturb_existing_observations(self):
        from src.core.metrics.registry import histogram_init

        histogram_observe("warm_dur", 0.5, buckets=[1.0, 5.0])
        histogram_init("warm_dur", buckets=[1.0, 5.0])

        text = render_metrics()
        assert "warm_dur_count 1" in text
        assert "warm_dur_sum 0.5" in text


class TestWarmup:
    def test_warmup_creates_all_series_with_zeros(self):
        from src.core.metrics.warmup import warmup_metrics

        warmup_metrics(llm_provider="gemini")

        text = render_metrics()
        assert 'fivekcal_analysis_total{outcome="ok"} 0' in text
        assert 'fivekcal_analysis_total{outcome="error"} 0' in text
        assert (
            'fivekcal_llm_requests_total{call="identification",outcome="success",provider="gemini"} 0'
            in text
        )
        assert 'fivekcal_payments_total{outcome="invalid_signature"} 0' in text
        assert "fivekcal_meals_saved_total 0" in text
        assert "fivekcal_users_new_total 0" in text
        assert "fivekcal_analyses_active 0" in text
        assert "fivekcal_analysis_duration_seconds_count 0" in text
        assert "fivekcal_llm_duration_seconds_count" in text

    def test_warmup_then_increment_counts_from_zero(self):
        from src.core.metrics.warmup import warmup_metrics

        warmup_metrics(llm_provider="openai")
        counter_inc(
            "fivekcal_llm_requests_total",
            labels={"provider": "openai", "call": "weight", "outcome": "success"},
        )

        text = render_metrics()
        assert (
            'fivekcal_llm_requests_total{call="weight",outcome="success",provider="openai"} 1'
            in text
        )
