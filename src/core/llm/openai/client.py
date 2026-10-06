"""OpenAILLMClient — адаптер OpenAI Responses API под LLMClient protocol."""

import inspect
import os
from pathlib import Path
from typing import Any, Optional

import yaml
import openai
from openai import AsyncOpenAI
from pydantic import BaseModel

from src.core.llm.models import MessageRole, Content
from src.core.utils import get_logger
from src.core.metrics import counter_inc
from src.core.llm.usage import set_last_usage
from src.core.llm.errors import LLMConnectionError, LLMRateLimitError, LLMAPIError

logger = get_logger()

_CONFIG_PATH = Path(__file__).parent / "config.yaml"


def _load_config() -> dict:
    with open(_CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


class OpenAILLMClient:
    """Обёртка над AsyncOpenAI, реализующая LLMClient protocol."""

    provider = "openai"

    def __init__(self, api_key: str):
        cfg = _load_config()
        self._client = AsyncOpenAI(api_key=api_key)
        self._model = cfg.get("model", "gpt-5.4-mini")
        self._max_output_tokens = cfg.get("max_output_tokens", 4096)
        self._timeout = cfg.get("timeout", 90)
        self._reasoning_effort = cfg.get("reasoning_effort", "medium")
        self._supports_prompt_cache_key: Optional[bool] = None

    # ── Внутренние хелперы ────────────────────────────────────────────────────

    def _check_prompt_cache_support(self) -> bool:
        if self._supports_prompt_cache_key is not None:
            return self._supports_prompt_cache_key
        try:
            signature = inspect.signature(self._client.responses.create)
        except (TypeError, ValueError):
            self._supports_prompt_cache_key = False
            return False

        if "prompt_cache_key" in signature.parameters:
            self._supports_prompt_cache_key = True
            return True

        self._supports_prompt_cache_key = any(
            p.kind == inspect.Parameter.VAR_KEYWORD
            for p in signature.parameters.values()
        )
        return self._supports_prompt_cache_key

    @staticmethod
    def _safe_get(value: Any, *path: str) -> Any:
        current = value
        for key in path:
            if current is None:
                return None
            if isinstance(current, dict):
                current = current.get(key)
            else:
                current = getattr(current, key, None)
        return current

    @staticmethod
    def _translate_messages(
        system_prompt: Optional[str],
        messages: list[tuple[MessageRole, list[Content]]],
    ) -> list[dict[str, Any]]:
        """Переводит канонические messages в формат OpenAI Responses API."""
        payload: list[dict[str, Any]] = []

        if system_prompt is not None:
            payload.append({
                "role": MessageRole.DEVELOPER,
                "content": [
                    Content.from_text(system_prompt).model_dump(exclude_none=True)
                ],
            })

        for role, contents in messages:
            payload.append({
                "role": role,
                "content": [c.model_dump(exclude_none=True) for c in contents],
            })

        return payload

    # ── Публичный интерфейс (LLMClient protocol) ────────────────────────────

    async def get_response(
        self,
        system_prompt: Optional[str],
        messages: list[tuple[MessageRole, list[Content]]],
        response_schema: type[BaseModel],
        response_schema_name: str,
        user_id: str,
        prompt_cache_scope: Optional[str] = None,
    ) -> str:
        """Вызывает OpenAI Responses API и возвращает текст ответа.

        Raises: LLMConnectionError, LLMRateLimitError, LLMAPIError, ValueError
        """
        payload_messages = self._translate_messages(system_prompt, messages)

        response_format = {
            "type": "json_schema",
            "name": response_schema_name,
            "schema": response_schema.model_json_schema(),
            "strict": True,
        }

        prompt_cache_key = (
            f"prompt:{prompt_cache_scope}" if prompt_cache_scope else None
        )

        request_kwargs: dict[str, Any] = {
            "model": self._model,
            "input": payload_messages,
            "max_output_tokens": self._max_output_tokens,
            "text": {"format": response_format},
            "user": str(user_id),
        }

        request_kwargs["reasoning"] = {"effort": self._reasoning_effort}

        if (
            self._check_prompt_cache_support()
            and prompt_cache_key
            and not os.environ.get("OPENAI_DISABLE_PROMPT_CACHE")
        ):
            request_kwargs["prompt_cache_key"] = prompt_cache_key

        try:
            response = await self._client.responses.create(
                **request_kwargs,
                timeout=self._timeout,
            )
        except openai.APIConnectionError as e:
            logger.warning(
                "OpenAI connection error",
                extra={"provider": "openai", "error": str(e)},
            )
            raise LLMConnectionError(str(e)) from e
        except openai.RateLimitError as e:
            logger.warning(
                "OpenAI rate limit",
                extra={"provider": "openai", "error": str(e)},
            )
            raise LLMRateLimitError(str(e)) from e
        except openai.InternalServerError as e:
            logger.warning(
                "OpenAI internal server error",
                extra={"provider": "openai", "error": str(e)},
            )
            raise LLMConnectionError(str(e)) from e
        except openai.APIError as e:
            logger.warning(
                "OpenAI API error",
                extra={"provider": "openai", "error": str(e)},
            )
            raise LLMAPIError(str(e)) from e

        input_tokens = self._safe_get(response, "usage", "input_tokens") or 0
        output_tokens = self._safe_get(response, "usage", "output_tokens") or 0
        cached_tokens = (
            self._safe_get(response, "usage", "input_tokens_details", "cached_tokens")
            or 0
        )

        logger.debug(
            "Ответ от LLM получен",
            extra={
                "provider": "openai",
                "chat_id": user_id,
                "model": self._model,
                "response_id": self._safe_get(response, "id"),
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cached_tokens": cached_tokens,
                "prompt_cache_key": (
                    prompt_cache_key if "prompt_cache_key" in request_kwargs else None
                ),
            },
        )

        for token_type, amount in [
            ("input", input_tokens),
            ("output", output_tokens),
            ("cached", cached_tokens),
        ]:
            if amount:
                counter_inc(
                    "fivekcal_llm_tokens_total",
                    labels={"token_type": token_type, "provider": "openai"},
                    amount=float(amount),
                    help="Total LLM tokens consumed by type and provider",
                )

        set_last_usage(
            provider="openai",
            model=self._model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_tokens=cached_tokens,
        )

        text = getattr(response, "output_text", None)
        if not text or not text.strip():
            raise ValueError("Пустой ответ от OpenAI")

        return text

    async def close(self) -> None:
        await self._client.close()
