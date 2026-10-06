"""
Передача token usage последнего LLM-вызова наверх без изменения протокола.

Клиент (openai/gemini) после каждого ответа кладёт usage в contextvar;
retry-обёртка (_llm_calls) забирает его и персистит в meal_analysis_logs
через sink, установленный из main.py. Contextvar корректно изолирует
конкурентные анализы в asyncio.
"""

from contextvars import ContextVar
from typing import Callable, Optional

from src.core.utils import get_logger

logger = get_logger()

# Usage последнего LLM-вызова в текущем asyncio-контексте
_last_usage: ContextVar[Optional[dict]] = ContextVar("llm_last_usage", default=None)

# Персистер: (user_id, call_type, usage, duration_ms) -> None
_sink: Optional[Callable[[int, str, dict, int], None]] = None


def set_last_usage(
    provider: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    cached_tokens: int,
) -> None:
    """Вызывается клиентом после каждого успешного ответа LLM."""
    _last_usage.set(
        {
            "provider": provider,
            "model": model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cached_tokens": cached_tokens,
        }
    )


def pop_last_usage() -> Optional[dict]:
    """Забирает usage последнего вызова (и очищает его)."""
    usage = _last_usage.get()
    _last_usage.set(None)
    return usage


def init_usage_sink(sink: Callable[[int, str, dict, int], None]) -> None:
    """Устанавливает персистер usage (из main.py)."""
    global _sink
    _sink = sink


def record_usage(user_id: int, call_type: str, duration_ms: int) -> None:
    """Персистит usage последнего вызова, если sink установлен.

    Ошибки записи не должны ломать анализ — только warning в лог.
    """
    usage = pop_last_usage()
    if usage is None or _sink is None:
        return
    try:
        _sink(user_id, call_type, usage, duration_ms)
    except Exception as e:
        logger.warning(
            "Не удалось записать LLM usage", extra={"chat_id": user_id, "error": str(e)}
        )
