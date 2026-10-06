"""
Утилиты для тестов: фабрики ответов OpenAI, хелпер записи блюда в БД.
"""

from datetime import datetime
from typing import Optional

from src.core.database.database import Database
from src.core.database import db as db_funcs
from src.core.llm.meal_model import Meal


def make_meal_dict(
    name: str = "Тестовое блюдо",
    emoji: str = "🍽️",
    count: int = 1,
    calories_min: float = 200,
    calories_max: float = 300,
    protein_min: float = 10,
    protein_max: float = 15,
    fat_min: float = 5,
    fat_max: float = 10,
    carbs_min: float = 30,
    carbs_max: float = 40,
    weight_min: float = 150,
    weight_max: float = 200,
    confidence: int = 10,
    confidence_reason: str = "Тестовый ответ",
) -> dict:
    return {
        "name": name,
        "emoji": emoji,
        "count": count,
        "estimated_weight_g": {"min": weight_min, "max": weight_max},
        "calories_kcal": {"min": calories_min, "max": calories_max},
        "protein_g": {"min": protein_min, "max": protein_max},
        "fat_g": {"min": fat_min, "max": fat_max},
        "carbs_g": {"min": carbs_min, "max": carbs_max},
        "confidence": confidence,
        "confidence_reason": confidence_reason,
    }


def make_success_response(
    meals: Optional[list[dict]] = None, barcode: str = ""
) -> dict:
    return {
        "status": "ok",
        "meals": meals if meals is not None else [make_meal_dict()],
        "error": "",
        "question": "",
        "barcode": barcode,
    }


def make_error_response(error: str) -> dict:
    return {
        "status": "error",
        "meals": [],
        "error": error,
        "question": "",
        "barcode": "",
    }


def make_barcode_response(barcode: str) -> dict:
    return {
        "status": "barcode",
        "meals": [],
        "error": "",
        "question": "",
        "barcode": barcode,
    }


def make_new_meal_response(meals: Optional[list[dict]] = None) -> dict:
    return {
        "status": "new_meal",
        "meals": meals if meals is not None else [make_meal_dict()],
        "error": "",
        "question": "",
        "barcode": "",
    }


# ─── Two-call architecture helpers ─────────────────────────────────────────


def make_component(
    name: str = "Тестовый компонент",
    description: str = "Тестовое блюдо средней плотности",
    placement: str = "separate",
    attached_to: str = "",
    calories_per_100g: float = 166.7,
    protein_per_100g: float = 8.3,
    fat_per_100g: float = 5.0,
    carbs_per_100g: float = 23.3,
) -> dict:
    """Компонент блюда для V2-ответа Call 1."""
    return {
        "name": name,
        "description": description,
        "placement": placement,
        "attached_to": attached_to,
        "calories_per_100g": calories_per_100g,
        "protein_per_100g": protein_per_100g,
        "fat_per_100g": fat_per_100g,
        "carbs_per_100g": carbs_per_100g,
    }


def make_identification_response(
    name: str = "Тестовое блюдо",
    emoji: str = "🍽️",
    components: Optional[list[dict]] = None,
    reasoning: str = "Определено по визуальным признакам",
    verification: str = "",
    status: str = "ok",
    error_code: str = "",
    error: str = "",
    question: str = "",
) -> dict:
    """V2-ответ Call 1: блюдо с массивом компонентов."""
    if components is None:
        components = [make_component()]
    return {
        "status": status,
        "name": name,
        "emoji": emoji,
        "components": components,
        "reasoning": reasoning,
        "verification": verification,
        "error_code": error_code,
        "error": error,
        "question": question,
    }


def make_identification_error(
    error: str, error_code: str = "meal_not_recognized"
) -> dict:
    return make_identification_response(
        status="error",
        name="",
        emoji="",
        components=[],
        reasoning="",
        error_code=error_code,
        error=error,
    )


def make_weight_response(
    components: Optional[list[dict]] = None,
    total_weight_g: float = 175.0,
    reasoning: str = "Оценено по визуальному размеру",
    verification: str = "",
    status: str = "ok",
    error_code: str = "",
    error: str = "",
    question: str = "",
) -> dict:
    """V2-ответ Call 2: веса компонентов + сумма."""
    if components is None:
        components = [{"name": "Тестовый компонент", "weight_g": total_weight_g}]
    return {
        "status": status,
        "components": components,
        "total_weight_g": total_weight_g,
        "reasoning": reasoning,
        "verification": verification,
        "error_code": error_code,
        "error": error,
        "question": question,
    }


def make_barcode_product(
    barcode: str = "4607062860031",
    name: str = "Молоко 3.2%",
    brand: Optional[str] = "Простоквашино",
    source: str = "open_food_facts",
    nutrition_raw: str = "58 ккал/100г, белки 2.9г, жиры 3.2г, углеводы 4.7г",
):
    from src.features.barcode.models import BarcodeProduct

    return BarcodeProduct(
        barcode=barcode,
        name=name,
        brand=brand,
        source=source,
        nutrition_raw=nutrition_raw,
    )


def _make_pydantic_meal(
    name: str = "Тестовое блюдо",
    calories_min: float = 200,
    calories_max: float = 300,
    protein_min: float = 10,
    protein_max: float = 15,
    fat_min: float = 5,
    fat_max: float = 10,
    carbs_min: float = 30,
    carbs_max: float = 40,
    weight_min: float = 150,
    weight_max: float = 200,
    **kwargs,
) -> Meal:
    """_min/_max — вспомогательные границы, из них берётся точечное значение
    (среднее). Если нужно точное точечное значение — передайте _min == _max."""
    return Meal(
        name=name,
        emoji=kwargs.get("emoji", "🍽️"),
        count=kwargs.get("count", 1),
        estimated_weight_g=(weight_min + weight_max) / 2,
        calories_kcal=(calories_min + calories_max) / 2,
        protein_g=(protein_min + protein_max) / 2,
        fat_g=(fat_min + fat_max) / 2,
        carbs_g=(carbs_min + carbs_max) / 2,
        confidence=kwargs.get("confidence", 10),
        confidence_reason=kwargs.get("confidence_reason", "Тестовый ответ"),
    )


def save_test_meal(
    db: Database,
    user_id: int,
    created_at: Optional[datetime] = None,
    name: str = "Тестовое блюдо",
    calories_min: float = 200,
    calories_max: float = 300,
    protein_min: float = 10,
    protein_max: float = 15,
    fat_min: float = 5,
    fat_max: float = 10,
    carbs_min: float = 30,
    carbs_max: float = 40,
    weight_min: float = 150,
    weight_max: float = 200,
    **kwargs,
) -> int:
    """Сохраняет блюдо в БД и возвращает meal.id."""
    meal_model = _make_pydantic_meal(
        name=name,
        calories_min=calories_min,
        calories_max=calories_max,
        protein_min=protein_min,
        protein_max=protein_max,
        fat_min=fat_min,
        fat_max=fat_max,
        carbs_min=carbs_min,
        carbs_max=carbs_max,
        weight_min=weight_min,
        weight_max=weight_max,
        **kwargs,
    )
    with db.session() as session:
        meal = db_funcs.save_meal_data(
            session,
            user_id=user_id,
            meal_model=meal_model,
            caption=kwargs.get("caption", ""),
            message_id=kwargs.get("message_id", 1),
            timezone=kwargs.get("timezone", "UTC"),
            telegram_file_id=kwargs.get("telegram_file_id"),
        )
        if created_at is not None:
            meal.created_at = created_at
            session.flush()
        meal_id = meal.id
    return meal_id
