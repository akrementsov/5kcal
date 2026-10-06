"""Провайдер-агностичные ошибки LLM."""


class LLMConnectionError(Exception):
    """Ошибка соединения с LLM API (таймаут, недоступность)."""


class LLMRateLimitError(Exception):
    """Превышен лимит запросов к LLM API."""


class LLMAPIError(Exception):
    """Общая ошибка LLM API (не connection и не rate limit)."""
