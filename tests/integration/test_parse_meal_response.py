"""Тесты parse_food_identification_response / parse_weight_estimation_response (V2)."""

import json

import pytest

from src.core.llm.manager import (
    parse_food_identification_response,
    parse_weight_estimation_response,
)
from src.core.llm.two_call_models import (
    FoodItemOk,
    FoodItemError,
    WeightItemOk,
    WeightItemError,
)


def _component(**overrides) -> dict:
    data = {
        "name": "Паста тальятелле варёная",
        "description": "длинные ленты с соусом, пустоты заполнены",
        "placement": "separate",
        "attached_to": "",
        "calories_per_100g": 150.0,
        "protein_per_100g": 6.0,
        "fat_per_100g": 5.0,
        "carbs_per_100g": 20.0,
    }
    data.update(overrides)
    return data


def _make_food_ok_json(**overrides) -> str:
    data = {
        "status": "ok",
        "name": "Паста с фрикадельками",
        "emoji": "🍝",
        "components": [
            _component(),
            _component(
                name="Фрикадельки мясные (3 шт.)",
                description="округлые шарики ~4 см",
                calories_per_100g=230.0,
                protein_per_100g=15.0,
                fat_per_100g=17.0,
                carbs_per_100g=4.0,
            ),
        ],
        "reasoning": "визуальный анализ",
        "verification": "",
        "error_code": "",
        "error": "",
    }
    data.update(overrides)
    return json.dumps(data)


def _make_food_error_json(error_code: str = "meal_not_recognized") -> str:
    return json.dumps(
        {
            "status": "error",
            "name": "",
            "emoji": "",
            "components": [],
            "reasoning": "не еда",
            "verification": "",
            "error_code": error_code,
            "error": "нет еды на фото",
        }
    )


def _make_weight_ok_json(**overrides) -> str:
    data = {
        "status": "ok",
        "components": [
            {"name": "Паста тальятелле варёная", "weight_g": 180.0},
            {"name": "Фрикадельки мясные (3 шт.)", "weight_g": 90.0},
        ],
        "total_weight_g": 270.0,
        "reasoning": "тарелка 25см, паста 14x12x2.5",
        "verification": "",
        "error_code": "",
        "error": "",
    }
    data.update(overrides)
    return json.dumps(data)


class TestFoodIdentificationParsing:
    def test_ok_result(self):
        result = parse_food_identification_response(_make_food_ok_json())
        assert isinstance(result, FoodItemOk)
        assert result.name == "Паста с фрикадельками"
        assert len(result.components) == 2
        assert result.components[0].calories_per_100g == 150.0
        assert result.components[1].placement == "separate"

    def test_ok_with_topping_component(self):
        result = parse_food_identification_response(
            _make_food_ok_json(
                components=[
                    _component(name="Омлет", placement="separate"),
                    _component(
                        name="Сыр тёртый",
                        placement="topping",
                        attached_to="Омлет",
                    ),
                ]
            )
        )
        assert isinstance(result, FoodItemOk)
        assert result.components[1].placement == "topping"
        assert result.components[1].attached_to == "Омлет"

    def test_ok_with_empty_components_is_error(self):
        result = parse_food_identification_response(_make_food_ok_json(components=[]))
        assert isinstance(result, FoodItemError)
        assert result.error_code.value == "other"

    def test_error_meal_not_recognized(self):
        result = parse_food_identification_response(_make_food_error_json())
        assert isinstance(result, FoodItemError)
        assert result.error_code.value == "meal_not_recognized"

    def test_error_multiple_dishes(self):
        result = parse_food_identification_response(
            _make_food_error_json(error_code="multiple_dishes")
        )
        assert isinstance(result, FoodItemError)
        assert result.error_code.value == "multiple_dishes"

    def test_error_unknown_code_falls_back_to_other(self):
        result = parse_food_identification_response(
            _make_food_error_json(error_code="unknown_code_xyz")
        )
        assert isinstance(result, FoodItemError)
        assert result.error_code.value == "other"

    def test_invalid_json_raises(self):
        with pytest.raises(ValueError):
            parse_food_identification_response("not json")

    def test_malformed_payload_raises(self):
        with pytest.raises(ValueError):
            parse_food_identification_response(json.dumps({"status": "ok"}))


class TestWeightEstimationParsing:
    def test_ok_result(self):
        result = parse_weight_estimation_response(_make_weight_ok_json())
        assert isinstance(result, WeightItemOk)
        assert result.total_weight_g == 270.0
        assert len(result.components) == 2
        assert result.components[0].weight_g == 180.0

    def test_ok_with_empty_components_is_error(self):
        result = parse_weight_estimation_response(
            _make_weight_ok_json(components=[], total_weight_g=0.0)
        )
        assert isinstance(result, WeightItemError)
        assert result.error_code.value == "other"

    def test_error_result(self):
        result = parse_weight_estimation_response(
            json.dumps(
                {
                    "status": "error",
                    "components": [],
                    "total_weight_g": 0.0,
                    "reasoning": "нет еды",
                    "verification": "",
                    "error_code": "other",
                    "error": "не удалось оценить вес",
                }
            )
        )
        assert isinstance(result, WeightItemError)
        assert result.error == "не удалось оценить вес"

    def test_invalid_json_raises(self):
        with pytest.raises(ValueError):
            parse_weight_estimation_response("not json")

    def test_malformed_payload_raises(self):
        with pytest.raises(ValueError):
            parse_weight_estimation_response(json.dumps({"status": "ok"}))
