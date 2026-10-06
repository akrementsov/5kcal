"""Тесты OpenAILLMClient — config wire-through, prompt cache, токены."""

import os
from typing import Literal, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import openai
import pytest
from pydantic import BaseModel

from src.core.llm.errors import LLMAPIError, LLMConnectionError, LLMRateLimitError
from src.core.llm.models import Content, MessageRole
from src.core.llm.openai.client import OpenAILLMClient


class _Schema(BaseModel):
    name: str
    count: int


def _make_client(*, model="test-model", max_tokens=1000, reasoning="medium", timeout=30):
    with patch("openai.AsyncOpenAI") as ctor:
        ctor.return_value = MagicMock()
        client = OpenAILLMClient(api_key="test-key")
    client._model = model
    client._max_output_tokens = max_tokens
    client._reasoning_effort = reasoning
    client._timeout = timeout
    # Принудительно фиксируем поддержку prompt_cache для предсказуемости
    client._supports_prompt_cache_key = True
    return client


def _stub_create(client, output_text='{"ok": true}', usage=None):
    response = MagicMock()
    response.output_text = output_text
    response.id = "resp_123"
    response.usage = usage
    mock = AsyncMock(return_value=response)
    client._client.responses.create = mock
    return mock


def _user_messages(text="hello"):
    return [(MessageRole.USER, [Content.from_text(text)])]


async def _call(client, **overrides):
    kwargs = dict(
        system_prompt=None,
        messages=_user_messages(),
        response_schema=_Schema,
        response_schema_name="schema_x",
        user_id="42",
    )
    kwargs.update(overrides)
    return await client.get_response(**kwargs)


# ─── Smoke + базовый wire-through ────────────────────────────────────────────


class TestSmoke:
    async def test_returns_output_text(self):
        client = _make_client()
        _stub_create(client, output_text='{"ok": true}')

        result = await _call(client)

        assert result == '{"ok": true}'

    @pytest.mark.parametrize("text", [None, "", "   ", "\n\n"])
    async def test_empty_response_raises_value_error(self, text):
        client = _make_client()
        _stub_create(client, output_text=text)

        with pytest.raises(ValueError, match="Пустой ответ"):
            await _call(client)


# ─── Config wire-through ─────────────────────────────────────────────────────


class TestConfigWireThrough:
    async def test_model_passed_to_request(self):
        client = _make_client(model="gpt-foo")
        create = _stub_create(client)

        await _call(client)

        assert create.call_args.kwargs["model"] == "gpt-foo"

    async def test_max_output_tokens_from_config(self):
        client = _make_client(max_tokens=2048)
        create = _stub_create(client)

        await _call(client)

        assert create.call_args.kwargs["max_output_tokens"] == 2048

    async def test_reasoning_effort_from_config(self):
        client = _make_client(reasoning="high")
        create = _stub_create(client)

        await _call(client)

        assert create.call_args.kwargs["reasoning"] == {"effort": "high"}

    async def test_timeout_passed(self):
        client = _make_client(timeout=45)
        create = _stub_create(client)

        await _call(client)

        assert create.call_args.kwargs["timeout"] == 45

    async def test_user_id_passed(self):
        client = _make_client()
        create = _stub_create(client)

        await _call(client, user_id="user_abc")

        assert create.call_args.kwargs["user"] == "user_abc"

    async def test_response_format_uses_strict_json_schema(self):
        client = _make_client()
        create = _stub_create(client)

        await _call(client, response_schema=_Schema, response_schema_name="my_schema")

        fmt = create.call_args.kwargs["text"]["format"]
        assert fmt["type"] == "json_schema"
        assert fmt["name"] == "my_schema"
        assert fmt["strict"] is True
        assert fmt["schema"] == _Schema.model_json_schema()


# ─── Translate messages — system_prompt as developer role ────────────────────


class TestTranslateMessages:
    async def test_system_prompt_added_as_developer_role(self):
        client = _make_client()
        create = _stub_create(client)

        await _call(client, system_prompt="be precise")

        payload = create.call_args.kwargs["input"]
        assert payload[0]["role"] == MessageRole.DEVELOPER
        # Content.from_text strips whitespace и кладёт в text
        assert any(c.get("text") == "be precise" for c in payload[0]["content"])

    async def test_system_prompt_none_not_added(self):
        client = _make_client()
        create = _stub_create(client)

        await _call(client, system_prompt=None)

        payload = create.call_args.kwargs["input"]
        # Первое сообщение — user, не developer
        assert payload[0]["role"] == MessageRole.USER


# ─── Prompt cache key — условный wire-through ────────────────────────────────


class TestPromptCacheKey:
    async def test_not_passed_when_scope_is_none(self):
        client = _make_client()
        create = _stub_create(client)

        await _call(client, prompt_cache_scope=None)

        assert "prompt_cache_key" not in create.call_args.kwargs

    async def test_passed_with_scope_when_supported(self):
        client = _make_client()
        client._supports_prompt_cache_key = True
        create = _stub_create(client)

        await _call(client, prompt_cache_scope="meals:weight")

        assert create.call_args.kwargs["prompt_cache_key"] == "prompt:meals:weight"

    async def test_not_passed_when_client_does_not_support(self):
        client = _make_client()
        client._supports_prompt_cache_key = False
        create = _stub_create(client)

        await _call(client, prompt_cache_scope="meals:weight")

        assert "prompt_cache_key" not in create.call_args.kwargs

    async def test_disabled_via_env_var(self, monkeypatch):
        client = _make_client()
        client._supports_prompt_cache_key = True
        create = _stub_create(client)
        monkeypatch.setenv("OPENAI_DISABLE_PROMPT_CACHE", "1")

        await _call(client, prompt_cache_scope="meals:weight")

        assert "prompt_cache_key" not in create.call_args.kwargs


# ─── Token metrics — input/output/cached ─────────────────────────────────────


class TestTokenMetrics:
    async def test_counts_all_three_token_types(self):
        client = _make_client()
        usage = MagicMock()
        usage.input_tokens = 100
        usage.output_tokens = 50
        usage.input_tokens_details.cached_tokens = 30
        _stub_create(client, usage=usage)

        with patch("src.core.llm.openai.client.counter_inc") as ci:
            await _call(client)

        calls = {
            tuple(sorted(c.kwargs["labels"].items())): c.kwargs["amount"]
            for c in ci.call_args_list
        }
        assert calls[(("provider", "openai"), ("token_type", "input"))] == 100.0
        assert calls[(("provider", "openai"), ("token_type", "output"))] == 50.0
        assert calls[(("provider", "openai"), ("token_type", "cached"))] == 30.0

    async def test_no_usage_no_metrics(self):
        client = _make_client()
        _stub_create(client, usage=None)

        with patch("src.core.llm.openai.client.counter_inc") as ci:
            await _call(client)

        assert ci.call_count == 0

    async def test_zero_cached_tokens_not_recorded(self):
        client = _make_client()
        usage = MagicMock()
        usage.input_tokens = 100
        usage.output_tokens = 50
        usage.input_tokens_details.cached_tokens = 0
        _stub_create(client, usage=usage)

        with patch("src.core.llm.openai.client.counter_inc") as ci:
            await _call(client)

        token_types_called = {
            c.kwargs["labels"]["token_type"] for c in ci.call_args_list
        }
        assert "cached" not in token_types_called


# ─── Error mapping (openai exceptions → LLM*) ─────────────────────────────────


def _make_openai_error(cls, message="boom"):
    """Конструктор для openai exceptions — обходим разнообразие сигнатур."""
    err = cls.__new__(cls)
    Exception.__init__(err, message)
    return err


class TestErrorMapping:
    @pytest.mark.parametrize(
        "exc_cls, expected",
        [
            (openai.APIConnectionError, LLMConnectionError),
            (openai.RateLimitError, LLMRateLimitError),
            (openai.InternalServerError, LLMConnectionError),
            (openai.APIError, LLMAPIError),
        ],
    )
    async def test_openai_exception_mapped(self, exc_cls, expected):
        client = _make_client()
        client._client.responses.create = AsyncMock(
            side_effect=_make_openai_error(exc_cls)
        )

        with pytest.raises(expected):
            await _call(client)

    async def test_non_openai_exception_propagated(self):
        client = _make_client()
        client._client.responses.create = AsyncMock(side_effect=RuntimeError("foo"))

        with pytest.raises(RuntimeError):
            await _call(client)
