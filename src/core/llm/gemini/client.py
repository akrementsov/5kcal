"""GeminiLLMClient — клиент Google Gemini API под LLMClient protocol."""

import re
from pathlib import Path
from typing import Any, Optional

import yaml
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

# Паттерн для извлечения mime_type и base64 из data URL
_DATA_URL_RE = re.compile(r"^data:([^;]+);base64,(.+)$", re.DOTALL)


def _parse_data_url(data_url: str) -> tuple[str, str]:
    """Извлекает (mime_type, base64_string) из data URL."""
    m = _DATA_URL_RE.match(data_url)
    if m:
        return m.group(1), m.group(2)
    # Fallback: считаем что это просто base64 без префикса
    return "image/jpeg", data_url


class GeminiLLMClient:
    """Клиент Google Gemini API, реализующий LLMClient protocol."""

    provider = "gemini"

    def __init__(self, api_key: str):
        from google import genai

        cfg = _load_config()
        self._genai_client = genai.Client(api_key=api_key)
        self._model = cfg.get("model", "gemini-3.1-flash-lite-preview")
        self._timeout = cfg.get("timeout", 90)
        self._thinking_level = cfg.get("thinking_level", "low")
        # Переопределения thinking по префиксу prompt_cache_scope
        self._thinking_levels: dict[str, str] = cfg.get("thinking_levels") or {}

    def _resolve_thinking(self, scope: Optional[str]) -> str:
        """Уровень thinking для вызова: самый длинный совпавший префикс scope."""
        if scope:
            for prefix in sorted(self._thinking_levels, key=len, reverse=True):
                if scope.startswith(prefix):
                    return self._thinking_levels[prefix]
        return self._thinking_level

    @staticmethod
    def _translate_content(content: Content) -> dict[str, Any]:
        """Переводит Content в Gemini Part dict."""
        if content.type == "input_image" and content.image_url:
            mime_type, b64_str = _parse_data_url(content.image_url)
            return {
                "inline_data": {
                    "mime_type": mime_type,
                    "data": b64_str,
                }
            }
        # input_text и output_text → text part
        return {"text": content.text or ""}

    @staticmethod
    def _translate_role(role: MessageRole) -> str:
        """MessageRole → Gemini role."""
        if role == MessageRole.ASSISTANT:
            return "model"
        return "user"

    def _translate_messages(
        self,
        messages: list[tuple[MessageRole, list[Content]]],
    ) -> list[dict[str, Any]]:
        """Переводит канонические messages в формат Gemini contents."""
        contents: list[dict[str, Any]] = []

        for role, content_list in messages:
            parts = [self._translate_content(c) for c in content_list]
            gemini_role = self._translate_role(role)

            # Gemini не допускает два подряд сообщения с одной ролью — мержим
            if contents and contents[-1]["role"] == gemini_role:
                contents[-1]["parts"].extend(parts)
            else:
                contents.append({"role": gemini_role, "parts": parts})

        return contents

    async def get_response(
        self,
        system_prompt: Optional[str],
        messages: list[tuple[MessageRole, list[Content]]],
        response_schema: type[BaseModel],
        response_schema_name: str,
        user_id: str,
        prompt_cache_scope: Optional[str] = None,
    ) -> str:
        """Вызывает Gemini API и возвращает текст ответа.

        Raises: LLMConnectionError, LLMRateLimitError, LLMAPIError, ValueError
        """
        from google.genai import types as genai_types
        from google.genai.errors import APIError

        contents = self._translate_messages(messages)
        json_schema = response_schema.model_json_schema()

        images_count = sum(
            1
            for role, cl in messages
            for c in cl
            if c.type == "input_image"
        )

        thinking_level = self._resolve_thinking(prompt_cache_scope)

        logger.debug(
            "Запрос к Gemini",
            extra={
                "provider": "gemini",
                "chat_id": user_id,
                "model": self._model,
                "images_count": images_count,
                "system_prompt_len": len(system_prompt) if system_prompt else 0,
                "thinking_level": thinking_level,
            },
        )

        config = genai_types.GenerateContentConfig(
            system_instruction=system_prompt,
            response_mime_type="application/json",
            response_json_schema=json_schema,
            thinking_config=genai_types.ThinkingConfig(
                thinking_level=thinking_level,
            ),
            http_options=genai_types.HttpOptions(
                timeout=self._timeout * 1000,
            ),
        )

        try:
            response = await self._genai_client.aio.models.generate_content(
                model=self._model,
                contents=contents,
                config=config,
            )
        except APIError as e:
            code = getattr(e, "code", None)
            extra = {
                "provider": "gemini",
                "error": str(e),
                "error_code": code,
                "error_status": getattr(e, "status", None),
            }
            if code == 429:
                logger.warning("Gemini rate limit", extra=extra)
                raise LLMRateLimitError(str(e)) from e
            if code in (408, 503, 504):
                logger.warning("Gemini connection issue", extra=extra)
                raise LLMConnectionError(str(e)) from e
            if code in (401, 403):
                logger.error(
                    "Gemini permission denied (проверьте GEMINI_API_KEY)", extra=extra
                )
                raise LLMAPIError(str(e)) from e
            logger.warning("Gemini API error", extra=extra)
            raise LLMAPIError(str(e)) from e

        # Метрики токенов
        usage = getattr(response, "usage_metadata", None)
        input_tokens = getattr(usage, "prompt_token_count", 0) or 0
        output_tokens = getattr(usage, "candidates_token_count", 0) or 0
        thinking_tokens = getattr(usage, "thoughts_token_count", 0) or 0
        cached_tokens = getattr(usage, "cached_content_token_count", 0) or 0

        logger.debug(
            "Ответ от LLM получен",
            extra={
                "provider": "gemini",
                "chat_id": user_id,
                "model": self._model,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "thinking_tokens": thinking_tokens,
                "cached_tokens": cached_tokens,
            },
        )

        for token_type, amount in [
            ("input", input_tokens),
            ("output", output_tokens),
            ("thinking", thinking_tokens),
            ("cached", cached_tokens),
        ]:
            if amount:
                counter_inc(
                    "fivekcal_llm_tokens_total",
                    labels={"token_type": token_type, "provider": "gemini"},
                    amount=float(amount),
                    help="Total LLM tokens consumed by type and provider",
                )

        set_last_usage(
            provider="gemini",
            model=self._model,
            input_tokens=input_tokens,
            # thinking-токены тарифицируются как output
            output_tokens=output_tokens + thinking_tokens,
            cached_tokens=cached_tokens,
        )

        text = getattr(response, "text", None)
        if not text or not text.strip():
            raise ValueError("Пустой ответ от Gemini")

        return text

    async def close(self) -> None:
        pass
