"""
Преинициализация метрик нулями при старте процесса.

Counter/histogram регистрируются лениво (при первом событии), поэтому после
рестарта серии исчезают из /metrics до первого инкремента: rate()/increase()
в Grafana показывают дыры, а stat-панели — «No data». Warmup создаёт известные
комбинации label заранее, чтобы серии существовали с нуля.
"""

from .registry import (
    counter_inc,
    gauge_set,
    histogram_init,
    ANALYSIS_BUCKETS,
    FAST_BUCKETS,
    LLM_BUCKETS,
)

_LLM_OUTCOMES = ("success", "rate_limit", "connection_error", "api_error", "parse_error")
_LLM_CALLS = ("identification", "weight")
_ANALYSIS_OUTCOMES = ("ok", "error", "rejected", "clarification")
_PAYMENT_OUTCOMES = (
    "ok",
    "invalid_signature",
    "missing_params",
    "amount_mismatch",
    "forbidden_ip",
    "duplicate",
)
_UPDATE_TYPES = ("message", "callback_query")


def warmup_metrics(llm_provider: str) -> None:
    """Создаёт нулевые серии для всех известных counter/gauge/histogram.

    llm_provider — активный провайдер из конфига (openai/gemini): только его
    комбинации имеют смысл, чужие серии не плодим.
    """
    for outcome in _ANALYSIS_OUTCOMES:
        counter_inc(
            "fivekcal_analysis_total",
            labels={"outcome": outcome},
            amount=0.0,
            help="Total photo analyses by outcome (ok/error/rejected/clarification)",
        )

    for call in _LLM_CALLS:
        base = {"provider": llm_provider, "call": call}
        for outcome in _LLM_OUTCOMES:
            counter_inc(
                "fivekcal_llm_requests_total",
                labels={**base, "outcome": outcome},
                amount=0.0,
                help="Total LLM requests by provider, call and outcome",
            )
        counter_inc(
            "fivekcal_llm_retries_total",
            labels=base,
            amount=0.0,
            help="Total LLM retries triggered",
        )
        histogram_init(
            "fivekcal_llm_duration_seconds",
            labels=base,
            buckets=LLM_BUCKETS,
            help="Successful LLM request duration in seconds",
        )

    for outcome in _PAYMENT_OUTCOMES:
        counter_inc(
            "fivekcal_payments_total",
            labels={"outcome": outcome},
            amount=0.0,
            help="Robokassa payment callbacks by outcome",
        )

    for update_type in _UPDATE_TYPES:
        counter_inc(
            "fivekcal_telegram_updates_total",
            labels={"update_type": update_type},
            amount=0.0,
            help="Total Telegram updates received by type",
        )

    counter_inc("fivekcal_meals_saved_total", amount=0.0, help="Total meals saved to database")
    counter_inc("fivekcal_users_new_total", amount=0.0, help="Total new users registered")

    # Два платёжных провайдера: Robokassa (RUB) и Telegram Stars (XTR)
    for provider, currency in (("robokassa", "RUB"), ("stars", "XTR")):
        for kind in ("paid", "trial", "refund"):
            counter_inc(
                "fivekcal_payment_records_total",
                labels={"kind": kind, "provider": provider},
                amount=0.0,
                help="Payment records created by kind and provider",
            )
        counter_inc(
            "fivekcal_payment_amount_total",
            labels={"currency": currency, "provider": provider},
            amount=0.0,
            help="Total amount received, in payment currency units",
        )
        counter_inc(
            "fivekcal_refund_amount_total",
            labels={"currency": currency, "provider": provider},
            amount=0.0,
            help="Total amount refunded, in payment currency units",
        )

    for token_type in ("input", "output", "thinking", "cached"):
        counter_inc(
            "fivekcal_llm_tokens_total",
            labels={"token_type": token_type, "provider": llm_provider},
            amount=0.0,
            help="Total LLM tokens consumed by type and provider",
        )

    gauge_set("fivekcal_analyses_active", 0.0, help="Currently running photo analyses")

    histogram_init(
        "fivekcal_analysis_duration_seconds",
        buckets=ANALYSIS_BUCKETS,
        help="Full photo analysis pipeline duration in seconds",
    )
    histogram_init(
        "fivekcal_resize_duration_seconds",
        buckets=FAST_BUCKETS,
        help="Image resize duration in seconds",
    )
