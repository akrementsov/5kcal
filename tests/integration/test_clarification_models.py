"""Схемы clarification: вопрос + черновая гипотеза в одном ответе (V2)."""

import pytest

from src.core.llm.two_call_models import (
    Component,
    FoodIdentificationItem,
    FoodItemClarification,
    WeightComponent,
    WeightEstimationItem,
    WeightItemClarification,
    parse_food_identification,
    parse_weight_estimation,
)


def _component(name: str = "Творог 5%") -> Component:
    return Component(
        name=name,
        description="мягкая творожная масса",
        placement="separate",
        attached_to="",
        calories_per_100g=121.0,
        protein_per_100g=17.0,
        fat_per_100g=5.0,
        carbs_per_100g=1.8,
    )


def _food_item(**overrides) -> FoodIdentificationItem:
    data = dict(
        reasoning="r",
        verification="v",
        status="clarification",
        name="Творог",
        emoji="🥛",
        components=[_component()],
        error_code="",
        error="",
        question="Похоже на творог 5%. Верно?",
    )
    data.update(overrides)
    return FoodIdentificationItem(**data)


def _weight_item(**overrides) -> WeightEstimationItem:
    data = dict(
        reasoning="r",
        verification="v",
        status="clarification",
        components=[WeightComponent(name="Творог 5%", weight_g=180.0)],
        total_weight_g=180.0,
        error_code="",
        error="",
        question="На вид ~180 г. Верно?",
    )
    data.update(overrides)
    return WeightEstimationItem(**data)


class TestFoodClarification:
    def test_valid_clarification_parsed(self):
        result = parse_food_identification(_food_item())
        assert isinstance(result, FoodItemClarification)
        assert result.question == "Похоже на творог 5%. Верно?"
        assert result.name == "Творог"
        assert len(result.components) == 1

    def test_empty_question_raises(self):
        with pytest.raises(ValueError):
            parse_food_identification(_food_item(question=""))

    def test_empty_hypothesis_raises(self):
        """clarification без гипотезы (нет компонентов) — parse-error."""
        with pytest.raises(ValueError):
            parse_food_identification(_food_item(components=[]))
        with pytest.raises(ValueError):
            parse_food_identification(_food_item(name=""))

    def test_ok_status_unaffected(self):
        from src.core.llm.two_call_models import FoodItemOk

        result = parse_food_identification(_food_item(status="ok", question=""))
        assert isinstance(result, FoodItemOk)

        # status="ok" с НЕПУСТЫМ question — question игнорируется, парсится в Ok
        result_with_q = parse_food_identification(
            _food_item(status="ok", question="Это творог?")
        )
        assert isinstance(result_with_q, FoodItemOk)


class TestWeightClarification:
    def test_valid_clarification_parsed(self):
        result = parse_weight_estimation(_weight_item())
        assert isinstance(result, WeightItemClarification)
        assert result.total_weight_g == 180.0

    def test_empty_question_raises(self):
        with pytest.raises(ValueError):
            parse_weight_estimation(_weight_item(question=""))

    def test_zero_total_without_components_valid(self):
        """Закрытая упаковка: гипотезы веса нет — это валидный clarification."""
        result = parse_weight_estimation(
            _weight_item(components=[], total_weight_g=0.0)
        )
        assert isinstance(result, WeightItemClarification)
        assert result.total_weight_g == 0.0

    def test_positive_total_requires_components(self):
        with pytest.raises(ValueError):
            parse_weight_estimation(_weight_item(components=[], total_weight_g=180.0))


class TestAnalysisResultInvariant:
    """Инвариант: clarification НЕ входит в формулу ok.

    Возврат clarification в ok молча сломает barcode-путь
    (`precheck.result.ok and precheck.result.meals`). Ветвление отображения
    всегда: if clarification → elif not ok → else display.
    """

    def test_clarification_result_is_ok_with_no_meals(self):
        from src.features.meals._types import AnalysisResult

        r = AnalysisResult(
            clarification="Похоже на творог 5%. Верно?",
            clarification_call="identification",
        )
        assert r.ok is True
        assert r.meals == []
        assert r.clarification_call == "identification"


class TestAssembleMealResult:
    def test_assembles_without_llm(self):
        from src.core.llm.two_call_models import FoodInfo, WeightComponent, WeightItemOk
        from src.features.meals._analysis_mixin import _assemble_meal_result

        food_info = FoodInfo(
            name="Творог",
            emoji="🥛",
            components=[{
                "name": "Творог 5%", "description": "", "placement": "separate",
                "attached_to": "", "calories_per_100g": 121.0,
                "protein_per_100g": 17.0, "fat_per_100g": 5.0,
                "carbs_per_100g": 1.8,
            }],
        )
        w_ok = WeightItemOk(
            components=[WeightComponent(name="Творог 5%", weight_g=200.0)],
            total_weight_g=200.0, reasoning="", verification="",
        )
        result = _assemble_meal_result(1, "творог", food_info, w_ok)
        assert result.ok and len(result.meals) == 1
        meal = result.meals[0]
        assert meal.estimated_weight_g == 200.0
        assert meal.calories_kcal == 242.0  # 200 г × 121 ккал/100г
