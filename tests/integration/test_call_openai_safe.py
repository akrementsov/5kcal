"""Тесты retry-логики call_identification / call_weight_estimation."""

from unittest.mock import AsyncMock, patch

import pytest

from src.i18n import DEFAULT_LOCALE
from src.core.ui.texts import ErrSvc
from src.core.llm.errors import LLMConnectionError, LLMRateLimitError, LLMAPIError
from src.core.llm.two_call_models import (
    Component,
    FoodItemOk,
    WeightComponent,
    WeightItemOk,
)
from src.features.meals._llm_calls import call_identification, call_weight_estimation
from src.features.meals._types import AnalysisResult
from config.bot import config as bot_config


# ─── Хелперы ─────────────────────────────────────────────────────────────────

_DUMMY_MESSAGES = []
_DUMMY_FILENAMES = ["test.jpg"]

_FOOD_OK = FoodItemOk(
    name="Тест",
    emoji="🍽️",
    components=[
        Component(
            name="Тестовый компонент",
            description="тестовое блюдо",
            placement="separate",
            attached_to="",
            calories_per_100g=200,
            protein_per_100g=10,
            fat_per_100g=5,
            carbs_per_100g=30,
        )
    ],
    reasoning="test",
    verification="test",
)

_WEIGHT_OK = WeightItemOk(
    components=[WeightComponent(name="Тестовый компонент", weight_g=150)],
    total_weight_g=150,
    reasoning="test",
    verification="test",
)


def _make_side_effects(exception: Exception, fail_count: int, success_result):
    return [exception] * fail_count + [success_result]


async def _call_id(client=None, on_retry=None):
    return await call_identification(
        llm_client=client or AsyncMock(),
        user_id=1,
        messages=_DUMMY_MESSAGES,
        chat_id=123,
        locale=DEFAULT_LOCALE,
        on_retry=on_retry,
    )


async def _call_weight(client=None, on_retry=None):
    return await call_weight_estimation(
        llm_client=client or AsyncMock(),
        user_id=1,
        messages=_DUMMY_MESSAGES,
        chat_id=123,
        locale=DEFAULT_LOCALE,
        on_retry=on_retry,
    )


# ─── Call 1: ValueError retry ───────────────────────────────────────────────


class TestIdentificationValueErrorRetry:
    @patch("src.features.meals._llm_calls.get_food_identification_data")
    async def test_recovers_on_second_attempt(self, mock):
        mock.side_effect = _make_side_effects(
            ValueError("Некорректный результат"), 1, _FOOD_OK
        )
        result = await _call_id()

        assert isinstance(result, FoodItemOk)
        assert mock.call_count == 2

    @patch("src.features.meals._llm_calls.get_food_identification_data")
    async def test_exhausted_returns_parse_error(self, mock):
        mock.side_effect = ValueError("Некорректный результат")
        result = await _call_id()

        assert isinstance(result, AnalysisResult)
        assert result.error == ErrSvc.LLM_PARSE
        assert mock.call_count == 3

    @patch("src.features.meals._llm_calls.get_food_identification_data")
    async def test_calls_on_retry_callback(self, mock):
        mock.side_effect = _make_side_effects(
            ValueError("Некорректный результат"), 2, _FOOD_OK
        )
        retry_count = 0

        async def on_retry():
            nonlocal retry_count
            retry_count += 1

        await _call_id(on_retry=on_retry)
        assert retry_count == 2


# ─── Call 1: Connection error retry ─────────────────────────────────────────


class TestIdentificationConnectionErrorRetry:
    @patch("src.features.meals._llm_calls.get_food_identification_data")
    async def test_recovers_after_one_failure(self, mock):
        mock.side_effect = _make_side_effects(
            LLMConnectionError("connection failed"), 1, _FOOD_OK
        )
        result = await _call_id()

        assert isinstance(result, FoodItemOk)
        assert mock.call_count == 2

    @patch("src.features.meals._llm_calls.get_food_identification_data")
    async def test_exhausted_returns_connection_error(self, mock):
        mock.side_effect = LLMConnectionError("connection failed")
        result = await _call_id()

        assert isinstance(result, AnalysisResult)
        assert result.error == ErrSvc.LLM_CONNECTION
        assert mock.call_count == 3


# ─── Call 1: API error (не ретраится) ────────────────────────────────────────


class TestIdentificationAPIErrorNoRetry:
    @patch("src.features.meals._llm_calls.get_food_identification_data")
    async def test_returns_immediately(self, mock):
        mock.side_effect = LLMAPIError("Server error")
        result = await _call_id()

        assert isinstance(result, AnalysisResult)
        assert result.error == ErrSvc.LLM_API
        assert mock.call_count == 1


# ─── Call 1: Rate limit retry ───────────────────────────────────────────────


class TestIdentificationRateLimitRetry:
    @patch("src.features.meals._llm_calls.get_food_identification_data")
    async def test_recovers_after_rate_limit(self, mock):
        mock.side_effect = _make_side_effects(
            LLMRateLimitError("Rate limited"),
            1,
            _FOOD_OK,
        )
        result = await _call_id()

        assert isinstance(result, FoodItemOk)
        assert mock.call_count == 2

    @patch("src.features.meals._llm_calls.get_food_identification_data")
    async def test_exhausted_returns_unavailable(self, mock):
        mock.side_effect = LLMRateLimitError("Rate limited")
        result = await _call_id()

        assert isinstance(result, AnalysisResult)
        assert result.error == ErrSvc.LLM_UNAVAILABLE
        assert mock.call_count == 3


# ─── Call 2: retry ──────────────────────────────────────────────────────────


class TestWeightEstimationRetry:
    # Эти тесты про retry ОДИНОЧНОГО вызова; ансамбль веса тестируется отдельно
    # в test_weight_ensemble.py. Пиним 1 сэмпл, иначе call_weight_estimation
    # запускает N параллельных вызовов и call_count/side_effect ломаются.
    @pytest.fixture(autouse=True)
    def _single_sample(self, monkeypatch):
        monkeypatch.setattr(bot_config, "weight_ensemble_samples", 1)

    @patch("src.features.meals._llm_calls.get_weight_estimation_data")
    async def test_recovers_on_second_attempt(self, mock):
        mock.side_effect = _make_side_effects(
            ValueError("Некорректный результат"), 1, _WEIGHT_OK
        )
        result = await _call_weight()

        assert isinstance(result, WeightItemOk)
        assert mock.call_count == 2

    @patch("src.features.meals._llm_calls.get_weight_estimation_data")
    async def test_exhausted_returns_parse_error(self, mock):
        mock.side_effect = ValueError("Некорректный результат")
        result = await _call_weight()

        assert isinstance(result, AnalysisResult)
        assert result.error == ErrSvc.LLM_PARSE
        assert mock.call_count == 3

    @patch("src.features.meals._llm_calls.get_weight_estimation_data")
    async def test_api_error_no_retry(self, mock):
        mock.side_effect = LLMAPIError("Server error")
        result = await _call_weight()

        assert isinstance(result, AnalysisResult)
        assert result.error == ErrSvc.LLM_API
        assert mock.call_count == 1


# ─── Success (без ошибок) ────────────────────────────────────────────────────


class TestSuccess:
    @pytest.fixture(autouse=True)
    def _single_sample(self, monkeypatch):
        # см. комментарий в TestWeightEstimationRetry
        monkeypatch.setattr(bot_config, "weight_ensemble_samples", 1)

    @patch("src.features.meals._llm_calls.get_food_identification_data")
    async def test_identification_returns_on_first_try(self, mock):
        mock.return_value = _FOOD_OK
        result = await _call_id()

        assert isinstance(result, FoodItemOk)
        assert mock.call_count == 1

    @patch("src.features.meals._llm_calls.get_weight_estimation_data")
    async def test_weight_returns_on_first_try(self, mock):
        mock.return_value = _WEIGHT_OK
        result = await _call_weight()

        assert isinstance(result, WeightItemOk)
        assert mock.call_count == 1
