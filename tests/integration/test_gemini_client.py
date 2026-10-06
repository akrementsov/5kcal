"""Тесты GeminiLLMClient — провайдер-обёртка над Google Gemini API.

Покрывают ключевую часть рефакторинга: schema передаётся как сырой
`model_json_schema()` через `response_json_schema=`, без кастомного конвертера.
Маппинг ошибок — на `google.genai.errors.APIError` по HTTP-коду.
"""

from typing import Literal, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from google.genai.errors import APIError
from pydantic import BaseModel

from src.core.llm.errors import LLMAPIError, LLMConnectionError, LLMRateLimitError
from src.core.llm.gemini.client import GeminiLLMClient
from src.core.llm.models import Content, MessageRole


class _Inner(BaseModel):
    kind: Literal["a", "b"]


class _NestedSchema(BaseModel):
    """Pydantic-модель с вложенностью ($defs+$ref), Optional и Literal — главный регрессионный кейс."""

    name: str
    inner: _Inner
    note: Optional[str] = None


def _make_client(*, model="test-model", timeout=90, thinking_level="low"):
    with patch("google.genai.Client") as ctor_mock:
        ctor_mock.return_value = MagicMock()
        client = GeminiLLMClient(api_key="test-key")
    client._model = model
    client._timeout = timeout
    client._thinking_level = thinking_level
    return client


def _stub_generate(client, response_text='{"ok": true}', usage=None):
    response = MagicMock()
    response.text = response_text
    response.usage_metadata = usage
    mock = AsyncMock(return_value=response)
    client._genai_client.aio.models.generate_content = mock
    return mock


def _make_api_error(code: int, status: str = "UNKNOWN") -> APIError:
    return APIError(
        code, {"error": {"code": code, "message": "boom", "status": status}}
    )


def _user_messages(text="hello"):
    return [(MessageRole.USER, [Content.from_text(text)])]


async def _call(client, **overrides):
    kwargs = dict(
        system_prompt=None,
        messages=_user_messages(),
        response_schema=_NestedSchema,
        response_schema_name="x",
        user_id="42",
    )
    kwargs.update(overrides)
    return await client.get_response(**kwargs)


# ─── Schema passing — суть рефакторинга ──────────────────────────────────────


class TestSchemaPassing:
    async def test_smoke_returns_response_text(self):
        client = _make_client()
        _stub_generate(client, response_text='{"ok": true}')

        result = await _call(client)

        assert result == '{"ok": true}'

    async def test_schema_passed_as_raw_model_json_schema(self):
        """Сырой model_json_schema() уходит в response_json_schema= без преобразований."""
        client = _make_client()
        gen = _stub_generate(client)

        await _call(client, response_schema=_NestedSchema)

        config = gen.call_args.kwargs["config"]
        assert config.response_json_schema == _NestedSchema.model_json_schema()
        assert config.response_mime_type == "application/json"

    async def test_no_legacy_response_schema_field(self):
        """Старый параметр response_schema= не используется (был до рефакторинга)."""
        client = _make_client()
        gen = _stub_generate(client)

        await _call(client)

        config = gen.call_args.kwargs["config"]
        assert getattr(config, "response_schema", None) is None

    async def test_schema_keeps_defs_and_refs(self):
        """Вложенные модели остаются как $defs+$ref, не инлайнятся (раньше инлайнил кастомный конвертер)."""
        client = _make_client()
        gen = _stub_generate(client)

        await _call(client)

        schema = gen.call_args.kwargs["config"].response_json_schema
        assert "$defs" in schema
        assert "_Inner" in schema["$defs"]


# ─── Config wire-through ─────────────────────────────────────────────────────


class TestConfigWireThrough:
    async def test_system_prompt_passed(self):
        client = _make_client()
        gen = _stub_generate(client)

        await _call(client, system_prompt="be polite")

        assert gen.call_args.kwargs["config"].system_instruction == "be polite"

    async def test_system_prompt_none_passed_through(self):
        client = _make_client()
        gen = _stub_generate(client)

        await _call(client, system_prompt=None)

        assert gen.call_args.kwargs["config"].system_instruction is None

    async def test_timeout_converted_to_milliseconds(self):
        client = _make_client(timeout=45)
        gen = _stub_generate(client)

        await _call(client)

        assert gen.call_args.kwargs["config"].http_options.timeout == 45_000

    async def test_thinking_level_from_config(self):
        client = _make_client(thinking_level="high")
        gen = _stub_generate(client)

        await _call(client)

        level = gen.call_args.kwargs["config"].thinking_config.thinking_level
        assert str(level).lower().endswith("high")

    async def test_model_name_passed(self):
        client = _make_client(model="gemini-x")
        gen = _stub_generate(client)

        await _call(client)

        assert gen.call_args.kwargs["model"] == "gemini-x"


# ─── Translate messages — merge ролей, data URL парсинг ──────────────────────


class TestTranslateMessages:
    async def test_consecutive_user_messages_merged(self):
        """Два сообщения с одной ролью подряд → один contents-элемент с объединёнными parts."""
        client = _make_client()
        gen = _stub_generate(client)

        msgs = [
            (MessageRole.USER, [Content.from_text("first")]),
            (MessageRole.USER, [Content.from_text("second")]),
        ]
        await _call(client, messages=msgs)

        contents = gen.call_args.kwargs["contents"]
        assert len(contents) == 1
        assert contents[0]["role"] == "user"
        assert len(contents[0]["parts"]) == 2

    async def test_assistant_role_translated_to_model(self):
        client = _make_client()
        gen = _stub_generate(client)

        msgs = [
            (MessageRole.USER, [Content.from_text("hi")]),
            (MessageRole.ASSISTANT, [Content.output_text("hello")]),
        ]
        await _call(client, messages=msgs)

        contents = gen.call_args.kwargs["contents"]
        assert contents[0]["role"] == "user"
        assert contents[1]["role"] == "model"

    async def test_data_url_image_parsed(self):
        client = _make_client()
        gen = _stub_generate(client)

        img = Content.image("BASE64STR", detail="low")
        msgs = [(MessageRole.USER, [img])]
        await _call(client, messages=msgs)

        part = gen.call_args.kwargs["contents"][0]["parts"][0]
        assert part["inline_data"]["mime_type"] == "image/jpeg"
        assert part["inline_data"]["data"] == "BASE64STR"


# ─── Empty / malformed response → ValueError ─────────────────────────────────


class TestEmptyResponse:
    @pytest.mark.parametrize("text", [None, "", "   ", "\n\n"])
    async def test_empty_or_whitespace_raises_value_error(self, text):
        client = _make_client()
        _stub_generate(client, response_text=text)

        with pytest.raises(ValueError, match="Пустой ответ"):
            await _call(client)


# ─── Token metrics ───────────────────────────────────────────────────────────


class TestTokenMetrics:
    async def test_usage_metadata_increments_counters(self):
        client = _make_client()
        usage = MagicMock()
        usage.prompt_token_count = 100
        usage.candidates_token_count = 50
        usage.thoughts_token_count = 30
        usage.cached_content_token_count = 20
        _stub_generate(client, usage=usage)

        with patch("src.core.llm.gemini.client.counter_inc") as ci:
            await _call(client)

        calls = {
            tuple(sorted(c.kwargs["labels"].items())): c.kwargs["amount"]
            for c in ci.call_args_list
        }
        assert calls[(("provider", "gemini"), ("token_type", "input"))] == 100.0
        assert calls[(("provider", "gemini"), ("token_type", "output"))] == 50.0
        assert calls[(("provider", "gemini"), ("token_type", "thinking"))] == 30.0
        assert calls[(("provider", "gemini"), ("token_type", "cached"))] == 20.0

    async def test_no_usage_metadata_does_not_crash(self):
        client = _make_client()
        _stub_generate(client, usage=None)

        with patch("src.core.llm.gemini.client.counter_inc") as ci:
            result = await _call(client)

        assert result == '{"ok": true}'
        assert ci.call_count == 0

    async def test_zero_token_counts_not_recorded(self):
        client = _make_client()
        usage = MagicMock()
        usage.prompt_token_count = 0
        usage.candidates_token_count = 0
        usage.thoughts_token_count = 0
        usage.cached_content_token_count = 0
        _stub_generate(client, usage=usage)

        with patch("src.core.llm.gemini.client.counter_inc") as ci:
            await _call(client)

        assert ci.call_count == 0


# ─── Error mapping по HTTP code (google.genai.errors.APIError) ────────────────


class TestErrorMapping:
    """APIError(code, ...) маппится в LLM* по HTTP-коду."""

    @pytest.mark.parametrize(
        "code, expected_cls",
        [
            (429, LLMRateLimitError),
            (408, LLMConnectionError),
            (503, LLMConnectionError),
            (504, LLMConnectionError),
            (401, LLMAPIError),
            (403, LLMAPIError),
            (500, LLMAPIError),
            (502, LLMAPIError),
        ],
    )
    async def test_api_error_mapped_by_http_code(self, code, expected_cls):
        client = _make_client()
        client._genai_client.aio.models.generate_content = AsyncMock(
            side_effect=_make_api_error(code)
        )

        with pytest.raises(expected_cls):
            await _call(client)

    async def test_api_error_preserves_cause(self):
        client = _make_client()
        api_exc = _make_api_error(429, status="RESOURCE_EXHAUSTED")
        client._genai_client.aio.models.generate_content = AsyncMock(
            side_effect=api_exc
        )

        with pytest.raises(LLMRateLimitError) as exc_info:
            await _call(client)

        assert exc_info.value.__cause__ is api_exc

    async def test_non_api_exception_propagated(self):
        client = _make_client()
        client._genai_client.aio.models.generate_content = AsyncMock(
            side_effect=RuntimeError("foo")
        )

        with pytest.raises(RuntimeError):
            await _call(client)
