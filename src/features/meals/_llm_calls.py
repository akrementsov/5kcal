"""Retry-обёртки над вызовами LLM для анализа блюд."""

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import TypeVar

from src.i18n import DEFAULT_LOCALE

from src.core.llm.protocol import LLMClient
from src.core.llm.errors import LLMConnectionError, LLMRateLimitError, LLMAPIError
from src.core.llm.usage import record_usage
from src.core.llm import (
    get_food_identification_data,
    get_weight_estimation_data,
)
from src.core.llm.two_call_models import (
    FoodItemOk,
    FoodItemError,
    WeightComponent,
    WeightItemOk,
    WeightItemError,
)
from config.bot import config
from src.core.ui.texts import ErrSvc
from src.core.metrics import counter_inc, histogram_observe, LLM_BUCKETS
from src.core.utils import get_logger
from ._types import AnalysisResult

logger = get_logger()

_RETRYABLE_ERRORS = (
    LLMConnectionError,
    LLMRateLimitError,
)
_RETRY_DELAYS = (1.0, 2.0)

_T = TypeVar("_T")


async def _retry_llm_call(
    call_fn: Callable[..., Awaitable[_T]],
    call_name: str,
    llm_client: LLMClient,
    user_id: int,
    messages: list,
    chat_id: int,
    locale: str = DEFAULT_LOCALE,
    on_retry: Callable[[], Awaitable[None]] | None = None,
) -> "_T | AnalysisResult":
    """Общая retry-логика для LLM-вызовов.

    Args:
        call_fn: async-функция LLM (get_food_identification_data / get_weight_estimation_data).
        call_name: человекочитаемое имя для логов ("identification" / "weight").
        llm_client: клиент LLM.
        user_id: ID пользователя.
        messages: список сообщений для LLM.
        chat_id: ID чата (для логов).
        locale: локаль пользователя.
        on_retry: опциональный callback, вызываемый перед каждым повтором.
    """
    last_exc: Exception | None = None
    base_labels = {
        "provider": getattr(llm_client, "provider", "unknown"),
        "call": call_name,
    }

    def _count_request(outcome: str) -> None:
        counter_inc(
            "fivekcal_llm_requests_total",
            labels={**base_labels, "outcome": outcome},
            help="Total LLM requests by provider, call and outcome",
        )

    for attempt, delay in enumerate((*_RETRY_DELAYS, None), start=1):
        try:
            t0 = time.monotonic()
            result = await call_fn(llm_client, str(user_id), messages, locale)
            elapsed = time.monotonic() - t0
            logger.debug(
                f"Call ({call_name}) ответил",
                extra={
                    "chat_id": chat_id,
                    "attempt": attempt,
                    "elapsed_s": round(elapsed, 2),
                },
            )
            _count_request("success")
            histogram_observe(
                "fivekcal_llm_duration_seconds",
                elapsed,
                labels=base_labels,
                buckets=LLM_BUCKETS,
                help="Successful LLM request duration in seconds",
            )
            record_usage(user_id, call_name, int(elapsed * 1000))
            return result
        except _RETRYABLE_ERRORS as e:
            last_exc = e
            is_rate_limit = isinstance(e, LLMRateLimitError)
            _count_request("rate_limit" if is_rate_limit else "connection_error")
            if delay is not None:
                counter_inc(
                    "fivekcal_llm_retries_total",
                    labels=base_labels,
                    help="Total LLM retries triggered",
                )
                logger.warning(
                    f"Временная ошибка LLM ({call_name}), повтор через {delay:.0f}s (попытка {attempt})",
                    extra={"chat_id": chat_id, "attempt": attempt, "error": str(e)},
                )
                if on_retry is not None:
                    await on_retry()
                await asyncio.sleep(delay)
        except LLMAPIError as e:
            _count_request("api_error")
            logger.error(
                f"Ошибка LLM API ({call_name})",
                extra={"chat_id": chat_id, "error": str(e)},
            )
            return AnalysisResult(error=ErrSvc.LLM_API)
        except ValueError as e:
            last_exc = e
            _count_request("parse_error")
            # Токены уже потрачены (модель ответила, упал парсинг) — фиксируем usage,
            # иначе спенд-лимит и meal_analysis_logs недосчитывают неудачные попытки
            record_usage(
                user_id,
                f"{call_name}_parse_error",
                int((time.monotonic() - t0) * 1000),
            )
            if delay is not None:
                counter_inc(
                    "fivekcal_llm_retries_total",
                    labels=base_labels,
                    help="Total LLM retries triggered",
                )
                logger.warning(
                    f"Ошибка парсинга ({call_name}), повтор через {delay:.0f}s (попытка {attempt})",
                    extra={"chat_id": chat_id, "attempt": attempt, "error": str(e)},
                )
                if on_retry is not None:
                    await on_retry()
                await asyncio.sleep(delay)
            else:
                return AnalysisResult(error=ErrSvc.LLM_PARSE)

    logger.error(
        f"{call_name} недоступен после 3 попыток",
        extra={"chat_id": chat_id, "error": str(last_exc)},
    )
    if isinstance(last_exc, LLMConnectionError):
        return AnalysisResult(error=ErrSvc.LLM_CONNECTION)
    return AnalysisResult(error=ErrSvc.LLM_UNAVAILABLE)


async def call_identification(
    llm_client: LLMClient,
    user_id: int,
    messages: list,
    chat_id: int,
    locale: str = DEFAULT_LOCALE,
    on_retry: Callable[[], Awaitable[None]] | None = None,
) -> "FoodItemOk | FoodItemError | AnalysisResult":
    """Вызывает Call 1 (идентификация блюда) с retry."""
    return await _retry_llm_call(
        call_fn=get_food_identification_data,
        call_name="identification",
        llm_client=llm_client,
        user_id=user_id,
        messages=messages,
        chat_id=chat_id,
        locale=locale,
        on_retry=on_retry,
    )


def _average_weight_estimates(results: list[WeightItemOk]) -> WeightItemOk:
    """Усредняет N оценок веса покомпонентно (по name).

    Компоненты у всех сэмплов одинаковы (общий FoodInfo из Call 1), поэтому
    усреднение по имени корректно. total = сумма усреднённых компонентов.
    reasoning/verification берём из первого сэмпла (нужны только для логов).
    """
    sums: dict[str, float] = {}
    counts: dict[str, int] = {}
    order: list[str] = []
    for r in results:
        for c in r.components:
            if c.name not in counts:
                order.append(c.name)
                sums[c.name] = 0.0
                counts[c.name] = 0
            sums[c.name] += c.weight_g
            counts[c.name] += 1
    components = [
        WeightComponent(name=name, weight_g=round(sums[name] / counts[name], 1))
        for name in order
    ]
    total = round(sum(c.weight_g for c in components), 1)
    return WeightItemOk(
        components=components,
        total_weight_g=total,
        reasoning=results[0].reasoning,
        verification=results[0].verification,
    )


async def call_weight_estimation(
    llm_client: LLMClient,
    user_id: int,
    messages: list,
    chat_id: int,
    locale: str = DEFAULT_LOCALE,
    on_retry: Callable[[], Awaitable[None]] | None = None,
) -> "WeightItemOk | WeightItemError | AnalysisResult":
    """Вызывает Call 2 (оценка веса) с retry.

    При config.weight_ensemble_samples ≥ 2 гоняет N независимых оценок веса
    параллельно (latency как у одного вызова) и усредняет их покомпонентно —
    гасит разброс одиночного вызова (бенчмарк: MAE −22%, ±50% 7.7→9/11).
    Ансамбль применяется только если получено ≥2 чистых WeightItemOk; иначе —
    поведение как у одиночного вызова (сохраняет clarification/error).
    Каждый вызов пишет usage → спенд-лимит учитывает полную косту ансамбля.
    """
    n = max(1, config.weight_ensemble_samples)

    async def _one() -> "WeightItemOk | WeightItemError | AnalysisResult":
        return await _retry_llm_call(
            call_fn=get_weight_estimation_data,
            call_name="weight",
            llm_client=llm_client,
            user_id=user_id,
            messages=messages,
            chat_id=chat_id,
            locale=locale,
            on_retry=on_retry,
        )

    if n == 1:
        return await _one()

    results = await asyncio.gather(*[_one() for _ in range(n)])
    ok = [r for r in results if isinstance(r, WeightItemOk)]
    if len(ok) >= 2:
        return _average_weight_estimates(ok)
    return results[0]
