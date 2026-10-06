"""Тесты core/llm/manager — _inject_user_context, parse_*_response."""

import json

import pytest

from src.core.llm.manager import (
    PromptId,
    _build_user_context,
    _inject_user_context,
    parse_food_identification_response,
    parse_weight_estimation_response,
)
from src.core.llm.models import Content, MessageRole


class TestInjectUserContext:
    def test_adds_context_to_first_user_message(self):
        messages = [
            (MessageRole.USER, [Content.from_text("hello")]),
        ]

        result = _inject_user_context(messages, locale="en")

        assert len(result) == 1
        contents = result[0][1]
        assert len(contents) == 2
        # Контекст — последний элемент
        assert contents[-1].type == "input_text"
        assert "en" in contents[-1].text

    def test_locale_included_in_context_text(self):
        messages = [(MessageRole.USER, [Content.from_text("hi")])]

        result_ru = _inject_user_context(messages, locale="ru")
        result_en = _inject_user_context(messages, locale="en")

        ctx_ru = result_ru[0][1][-1].text
        ctx_en = result_en[0][1][-1].text
        assert "language=ru" in ctx_ru
        assert "language=en" in ctx_en
        assert ctx_ru != ctx_en

    def test_does_not_mutate_input_messages(self):
        original_contents = [Content.from_text("hi")]
        messages = [(MessageRole.USER, original_contents)]

        _inject_user_context(messages, locale="ru")

        # Оригинальный список не изменён
        assert len(original_contents) == 1
        assert len(messages[0][1]) == 1

    def test_empty_messages_returns_empty(self):
        assert _inject_user_context([], locale="en") == []

    def test_no_user_role_returns_unchanged(self):
        """Если нет USER-сообщений, контекст не добавляется."""
        messages = [
            (MessageRole.ASSISTANT, [Content.output_text("hello")]),
        ]

        result = _inject_user_context(messages, locale="en")

        # Результат — копия исходного списка с тем же количеством сообщений
        assert len(result) == 1
        assert result[0][0] == MessageRole.ASSISTANT
        assert len(result[0][1]) == 1  # контекст не добавлен

    def test_only_first_user_message_gets_context(self):
        """Несколько USER сообщений — контекст идёт только в первое."""
        messages = [
            (MessageRole.USER, [Content.from_text("first")]),
            (MessageRole.ASSISTANT, [Content.output_text("ack")]),
            (MessageRole.USER, [Content.from_text("second")]),
        ]

        result = _inject_user_context(messages, locale="en")

        assert len(result[0][1]) == 2  # first user — с контекстом
        assert len(result[1][1]) == 1  # assistant — без
        assert len(result[2][1]) == 1  # second user — без

    def test_repeated_calls_double_inject(self):
        """Документируем поведение: повторный вызов добавляет контекст ВТОРОЙ раз.

        Текущая реализация не идемпотентна — это известно. Тест фиксирует факт,
        чтобы случайное добавление протекции не сломало callers, ожидающих
        текущее поведение.
        """
        messages = [(MessageRole.USER, [Content.from_text("hi")])]

        once = _inject_user_context(messages, locale="en")
        twice = _inject_user_context(once, locale="en")

        # Дважды вызванная инъекция добавляет два контекста
        assert len(twice[0][1]) == 3


class TestBuildUserContext:
    def test_returns_content_with_text_type(self):
        ctx = _build_user_context("ru")

        assert ctx.type == "input_text"
        assert "USER_CONTEXT" in ctx.text
        assert "language=ru" in ctx.text


class TestPromptId:
    def test_enum_values(self):
        assert PromptId.FOOD_IDENTIFICATION.value == "food_identification"
        assert PromptId.WEIGHT_ESTIMATION.value == "weight_estimation"


class TestParseResponses:
    """Базовые тесты парсинга — happy path. Полное покрытие в test_parse_meal_response.py."""

    def test_parse_food_invalid_json_raises_value_error(self):
        with pytest.raises(ValueError, match="идентификации"):
            parse_food_identification_response("not-a-json{")

    def test_parse_weight_invalid_json_raises_value_error(self):
        with pytest.raises(ValueError, match="оценки веса"):
            parse_weight_estimation_response("garbage")

    def test_parse_food_normalizes_unknown_error_code(self):
        """Неизвестный error_code приводится к 'other' перед валидацией Pydantic."""
        payload = json.dumps(
            {
                "status": "error",
                "name": "",
                "emoji": "",
                "components": [],
                "reasoning": "",
                "verification": "",
                "error_code": "FUTURE_UNKNOWN_CODE",
                "error": "some error",
            }
        )

        # Не должно падать на Literal validation — error_code нормализован
        result = parse_food_identification_response(payload)
        assert result is not None

    def test_parse_food_clarification_via_json(self):
        """Сырой JSON со status=clarification проходит полный путь manager.py
        (json.loads → нормализация → Pydantic → parse) и даёт FoodItemClarification."""
        from src.core.llm.two_call_models import FoodItemClarification

        payload = json.dumps(
            {
                "status": "clarification",
                "name": "Творог",
                "emoji": "🥛",
                "components": [
                    {
                        "name": "Творог 5%",
                        "description": "мягкая творожная масса",
                        "placement": "separate",
                        "attached_to": "",
                        "calories_per_100g": 121.0,
                        "protein_per_100g": 17.0,
                        "fat_per_100g": 5.0,
                        "carbs_per_100g": 1.8,
                    }
                ],
                "reasoning": "похоже на творог",
                "verification": "",
                "error_code": "",
                "error": "",
                "question": "Это творог 5%? Верно?",
            }
        )

        result = parse_food_identification_response(payload)

        assert isinstance(result, FoodItemClarification)
        assert result.question == "Это творог 5%? Верно?"
        assert result.name == "Творог"
        assert len(result.components) == 1

    def test_parse_weight_clarification_via_json(self):
        """Сырой JSON Call 2 со status=clarification → WeightItemClarification."""
        from src.core.llm.two_call_models import WeightItemClarification

        payload = json.dumps(
            {
                "status": "clarification",
                "components": [{"name": "Творог 5%", "weight_g": 180.0}],
                "total_weight_g": 180.0,
                "reasoning": "",
                "verification": "",
                "error_code": "",
                "error": "",
                "question": "На вид ~180 г. Верно?",
            }
        )

        result = parse_weight_estimation_response(payload)

        assert isinstance(result, WeightItemClarification)
        assert result.total_weight_g == 180.0
        assert result.question == "На вид ~180 г. Верно?"
