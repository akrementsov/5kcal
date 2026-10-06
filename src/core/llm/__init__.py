from .protocol import LLMClient
from .errors import LLMConnectionError, LLMRateLimitError, LLMAPIError
from .manager import (
    get_food_identification_data,
    get_weight_estimation_data,
    PromptId,
)

__all__ = [
    "LLMClient",
    "LLMConnectionError",
    "LLMRateLimitError",
    "LLMAPIError",
    "create_llm_client",
    "get_food_identification_data",
    "get_weight_estimation_data",
    "PromptId",
]


def create_llm_client(config) -> LLMClient:
    """Фабрика: создаёт LLM-клиент по значению config.llm_provider."""
    from src.core.utils import get_logger

    logger = get_logger()

    provider = config.llm_provider

    if provider not in ("openai", "gemini"):
        raise ValueError(
            f"Неизвестный LLM_PROVIDER: {provider!r}. Допустимые: openai, gemini"
        )

    if provider == "gemini":
        from .gemini.client import GeminiLLMClient

        client = GeminiLLMClient(api_key=config.gemini_api_key)
        logger.info(
            "LLM клиент создан",
            extra={"provider": "gemini", "model": client._model},
        )
        return client

    from .openai.client import OpenAILLMClient

    client = OpenAILLMClient(api_key=config.openai_api_key)
    logger.info(
        "LLM клиент создан",
        extra={"provider": "openai", "model": client._model},
    )
    return client
