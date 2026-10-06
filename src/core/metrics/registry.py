"""
Thread-safe Prometheus-совместимый реестр метрик.

Поддерживает counter, gauge, histogram без внешних зависимостей.
Вывод в формате Prometheus text exposition format 0.0.4.
"""

import threading
from collections import defaultdict
from typing import Optional

_lock = threading.Lock()

# {name: {"help": str, "type": str}}
_meta: dict[str, dict] = {}

# Counter: {(name, labels_tuple): float}
_counters: dict[tuple, float] = defaultdict(float)

# Gauge: {(name, labels_tuple): float}
_gauges: dict[tuple, float] = defaultdict(float)

# Histogram: {name: {"buckets": list[float], "counts": {labels_tuple: {bucket: float}},
#                    "sums": {labels_tuple: float}, "counts_total": {labels_tuple: float}}}
_histograms: dict[str, dict] = {}

# Analysis buckets: анализ фото занимает от ~1s до 30-60s
ANALYSIS_BUCKETS = [0.5, 1.0, 2.0, 3.0, 5.0, 8.0, 12.0, 20.0, 30.0, 45.0, 60.0]

# Fast buckets: ресайз, Redis, DB — обычно быстрые операции
FAST_BUCKETS = [0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0]

# LLM buckets: сетевой запрос + inference
LLM_BUCKETS = [0.5, 1.0, 2.0, 3.0, 5.0, 8.0, 12.0, 20.0, 30.0, 60.0]


def _labels_key(labels: dict) -> tuple:
    return tuple(sorted(labels.items()))


def _labels_str(labels: dict) -> str:
    if not labels:
        return ""
    pairs = ",".join(f'{k}="{v}"' for k, v in sorted(labels.items()))
    return "{" + pairs + "}"


def _register(name: str, help_text: str, metric_type: str) -> None:
    """Регистрирует метрику, если ещё не зарегистрирована. Вызывается под _lock."""
    if name not in _meta:
        _meta[name] = {"help": help_text, "type": metric_type}


# ── Counter ───────────────────────────────────────────────────────────────────


def counter_inc(
    name: str,
    labels: Optional[dict] = None,
    amount: float = 1.0,
    help: str = "",
) -> None:
    """Увеличивает счётчик (монотонно возрастающий)."""
    labels = labels or {}
    key = (name, _labels_key(labels))
    with _lock:
        _register(name, help, "counter")
        _counters[key] += amount


# ── Gauge ─────────────────────────────────────────────────────────────────────


def gauge_set(
    name: str,
    value: float,
    labels: Optional[dict] = None,
    help: str = "",
) -> None:
    """Устанавливает значение gauge."""
    labels = labels or {}
    key = (name, _labels_key(labels))
    with _lock:
        _register(name, help, "gauge")
        _gauges[key] = value


def gauge_inc(
    name: str,
    labels: Optional[dict] = None,
    amount: float = 1.0,
    help: str = "",
) -> None:
    """Увеличивает gauge."""
    labels = labels or {}
    key = (name, _labels_key(labels))
    with _lock:
        _register(name, help, "gauge")
        _gauges[key] = _gauges.get(key, 0.0) + amount


def gauge_dec(
    name: str,
    labels: Optional[dict] = None,
    amount: float = 1.0,
) -> None:
    """Уменьшает gauge."""
    labels = labels or {}
    key = (name, _labels_key(labels))
    with _lock:
        _gauges[key] = _gauges.get(key, 0.0) - amount


# ── Histogram ─────────────────────────────────────────────────────────────────


def _ensure_histogram(name: str, buckets: list, help_text: str) -> None:
    """Инициализирует histogram если не существует. Вызывается под _lock."""
    if name not in _histograms:
        _histograms[name] = {
            "buckets": sorted(buckets),
            "counts": defaultdict(lambda: defaultdict(float)),
            "sums": defaultdict(float),
            "counts_total": defaultdict(float),
        }
        _register(name, help_text, "histogram")


def histogram_observe(
    name: str,
    value: float,
    labels: Optional[dict] = None,
    buckets: Optional[list] = None,
    help: str = "",
) -> None:
    """Записывает наблюдение в histogram."""
    labels = labels or {}
    lkey = _labels_key(labels)
    buckets = buckets or FAST_BUCKETS

    with _lock:
        _ensure_histogram(name, buckets, help)
        h = _histograms[name]
        # Накопительные бакеты: каждый бакет b содержит кол-во наблюдений <= b
        for b in h["buckets"]:
            if value <= b:
                h["counts"][lkey][b] += 1.0
        # +Inf всегда равен общему числу наблюдений
        h["counts"][lkey][float("inf")] += 1.0
        h["sums"][lkey] += value
        h["counts_total"][lkey] += 1.0


def histogram_init(
    name: str,
    labels: Optional[dict] = None,
    buckets: Optional[list] = None,
    help: str = "",
) -> None:
    """Создаёт серию histogram с нулевыми счётчиками (без наблюдения).

    Нужно для преинициализации при старте: серия появляется в /metrics сразу,
    без дыр в rate() после рестарта.
    """
    labels = labels or {}
    lkey = _labels_key(labels)
    buckets = buckets or FAST_BUCKETS

    with _lock:
        _ensure_histogram(name, buckets, help)
        h = _histograms[name]
        h["counts_total"][lkey] += 0.0
        h["sums"][lkey] += 0.0


# ── Render ────────────────────────────────────────────────────────────────────


def render_metrics() -> str:
    """Возвращает все метрики в формате Prometheus text 0.0.4."""
    lines: list[str] = []

    with _lock:
        # Группируем counter/gauge по имени
        counter_names: set[str] = set()
        gauge_names: set[str] = set()

        for name, _ in _counters:
            counter_names.add(name)
        for name, _ in _gauges:
            gauge_names.add(name)

        for name in sorted(counter_names):
            meta = _meta.get(name, {})
            lines.append(f"# HELP {name} {meta.get('help', '')}")
            lines.append(f"# TYPE {name} counter")
            for (n, lkey), value in sorted(_counters.items()):
                if n != name:
                    continue
                lines.append(f"{name}{_labels_str(dict(lkey))} {_fmt(value)}")

        for name in sorted(gauge_names):
            meta = _meta.get(name, {})
            lines.append(f"# HELP {name} {meta.get('help', '')}")
            lines.append(f"# TYPE {name} gauge")
            for (n, lkey), value in sorted(_gauges.items()):
                if n != name:
                    continue
                lines.append(f"{name}{_labels_str(dict(lkey))} {_fmt(value)}")

        for name in sorted(_histograms.keys()):
            h = _histograms[name]
            meta = _meta.get(name, {})
            lines.append(f"# HELP {name} {meta.get('help', '')}")
            lines.append(f"# TYPE {name} histogram")
            for lkey in sorted(h["counts_total"].keys()):
                labels_base = dict(lkey)
                for b in h["buckets"]:
                    le_labels = {**labels_base, "le": _fmt_le(b)}
                    cnt = h["counts"][lkey].get(b, 0.0)
                    lines.append(f"{name}_bucket{_labels_str(le_labels)} {_fmt(cnt)}")
                # +Inf
                le_labels = {**labels_base, "le": "+Inf"}
                lines.append(
                    f'{name}_bucket{_labels_str(le_labels)} {_fmt(h["counts_total"][lkey])}'
                )
                lines.append(
                    f'{name}_sum{_labels_str(labels_base)} {_fmt(h["sums"][lkey])}'
                )
                lines.append(
                    f'{name}_count{_labels_str(labels_base)} {_fmt(h["counts_total"][lkey])}'
                )

    lines.append("")  # trailing newline
    return "\n".join(lines)


def _fmt(value: float) -> str:
    """Форматирует число: целые без дробной части, остальные с 6 знаками."""
    if value == int(value) and abs(value) < 1e15:
        return str(int(value))
    return f"{value:.6g}"


def _fmt_le(value: float) -> str:
    """Форматирует le-метку bucket: целые без .0, остальные через g."""
    if value == int(value) and abs(value) < 1e15:
        return str(int(value))
    return f"{value:g}"
