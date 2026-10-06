"""
Модели для двухвызовной архитектуры анализа блюд (V2, компонентная).

Call 1: идентификация блюда — раскладывает блюдо на компоненты
        (FoodIdentificationItem → FoodItemOk | FoodItemError | FoodItemClarification)
Call 2: оценка веса — per-component volumetric
        (WeightEstimationItem → WeightItemOk | WeightItemError | WeightItemClarification)

Каждый *Item — единая схема для strict JSON (все поля обязательны).
Типизированные результаты (Ok/Error/Clarification) возвращаются после parse_*.
FoodInfo — промежуточный dataclass между Call 1 и Call 2 (сериализуется в Redis).

Вариант A clarification: модель задаёт уточняющий вопрос + предварительную гипотезу
(компоненты с калориями для Call 1, веса для Call 2). Гипотеза передаётся в Chat,
а ответ пользователя (подтверждение/отказ) обсчитывается финальным LLM-вызовом.

Confidence-проценты удалены: диапазоны для UI строятся от фиксированного
display-процента (см. features/meals).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict


# ── Call 1: схема для strict JSON ────────────────────────────────────────────


class FoodIdentificationErrorCode(StrEnum):
    PROMPT_INJECTION = "prompt_injection"
    MEAL_NOT_RECOGNIZED = "meal_not_recognized"
    MULTIPLE_DISHES = "multiple_dishes"
    OTHER = "other"


class Component(BaseModel):
    """Компонент блюда: продуктовая единица или сервируемая порция."""

    name: str
    description: str  # текстура/структура — для оценки плотности в Call 2
    placement: Literal["separate", "mixed", "topping"]  # как измерим на фото
    attached_to: str  # для topping — имя компонента-основы; иначе ""
    calories_per_100g: float
    protein_per_100g: float
    fat_per_100g: float
    carbs_per_100g: float

    model_config = ConfigDict(extra="forbid")


class FoodIdentificationItem(BaseModel):
    """Единая схема ответа Call 1. Все поля обязательны для strict-режима."""

    # Поля рассуждений идут первыми — модель "думает" до генерации ответа
    reasoning: str
    verification: str
    status: Literal["ok", "error", "clarification"]
    name: str  # название блюда целиком
    emoji: str
    components: list[Component]
    error_code: Literal["", "prompt_injection", "meal_not_recognized", "multiple_dishes", "other"]
    error: str
    question: str  # уточняющий вопрос пользователю (пусто для ok/error)

    model_config = ConfigDict(extra="forbid")


# ── Call 1: типизированные результаты после parse ────────────────────────────


class FoodItemOk(BaseModel):
    name: str
    emoji: str
    components: list[Component]
    reasoning: str
    verification: str


class FoodItemError(BaseModel):
    error_code: FoodIdentificationErrorCode
    error: str  # fallback-текст для пользователя при error_code="other"


class FoodItemClarification(BaseModel):
    """Вопрос пользователю + черновая гипотеза (как FoodItemOk)."""

    name: str
    emoji: str
    components: list[Component]
    reasoning: str
    verification: str
    question: str


def _parse_food_error_code(raw_code: str) -> FoodIdentificationErrorCode:
    try:
        return FoodIdentificationErrorCode(raw_code)
    except ValueError:
        return FoodIdentificationErrorCode.OTHER


def parse_food_identification(
    item: FoodIdentificationItem,
) -> FoodItemOk | FoodItemError | FoodItemClarification:
    if item.status == "clarification":
        if not item.question.strip():
            raise ValueError("clarification без вопроса")
        if not item.name or not item.components:
            raise ValueError("clarification без гипотезы (name/components)")
        return FoodItemClarification(
            name=item.name,
            emoji=item.emoji,
            components=item.components,
            reasoning=item.reasoning,
            verification=item.verification,
            question=item.question,
        )
    if item.status == "ok":
        if not item.components:
            return FoodItemError(
                error_code=FoodIdentificationErrorCode.OTHER,
                error="",
            )
        return FoodItemOk(
            name=item.name,
            emoji=item.emoji,
            components=item.components,
            reasoning=item.reasoning,
            verification=item.verification,
        )
    return FoodItemError(
        error_code=_parse_food_error_code(item.error_code),
        error=item.error,
    )


# ── Промежуточный объект между Call 1 и Call 2 ──────────────────────────────


@dataclass
class FoodInfo:
    name: str
    emoji: str
    components: list[dict] = field(default_factory=list)  # сериализованные Component
    reasoning: str = ""
    verification: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> FoodInfo:
        return cls(
            name=data["name"],
            emoji=data.get("emoji", ""),
            components=data.get("components", []),
            reasoning=data.get("reasoning", ""),
            verification=data.get("verification", ""),
        )

    @classmethod
    def from_ok(cls, item: FoodItemOk) -> FoodInfo:
        return cls(
            name=item.name,
            emoji=item.emoji,
            components=[c.model_dump() for c in item.components],
            reasoning=item.reasoning,
            verification=item.verification,
        )


def build_range(central: float, pct: int) -> tuple[float, float]:
    """Вычисляет диапазон (min, max) по центральному значению и погрешности в %."""
    factor = pct / 100
    return central * (1 - factor), central * (1 + factor)


# ── Call 2: схема для strict JSON ────────────────────────────────────────────


class WeightEstimationErrorCode(StrEnum):
    PROMPT_INJECTION = "prompt_injection"
    OTHER = "other"


class WeightComponent(BaseModel):
    """Вес одного компонента из объёмного измерения по фото."""

    name: str  # точно как в FOOD_INFO
    weight_g: float

    model_config = ConfigDict(extra="forbid")


class WeightEstimationItem(BaseModel):
    """Единая схема ответа Call 2. Все поля обязательны для strict-режима."""

    # Поля рассуждений идут первыми — модель "думает" до генерации ответа
    reasoning: str
    verification: str
    status: Literal["ok", "error", "clarification"]
    components: list[WeightComponent]
    total_weight_g: float  # = Σ weight_g компонентов
    error_code: Literal["", "prompt_injection", "other"]
    error: str
    question: str  # уточняющий вопрос пользователю (пусто для ok/error)

    model_config = ConfigDict(extra="forbid")


# ── Call 2: типизированные результаты после parse ────────────────────────────


class WeightItemOk(BaseModel):
    components: list[WeightComponent]
    total_weight_g: float
    reasoning: str
    verification: str


class WeightItemError(BaseModel):
    error_code: WeightEstimationErrorCode
    error: str  # текст для пользователя


class WeightItemClarification(BaseModel):
    """Вопрос пользователю + черновой вес (total_weight_g=0 — гипотезы нет)."""

    components: list[WeightComponent]
    total_weight_g: float
    question: str


def _parse_weight_error_code(raw_code: str) -> WeightEstimationErrorCode:
    try:
        return WeightEstimationErrorCode(raw_code)
    except ValueError:
        return WeightEstimationErrorCode.OTHER


def parse_weight_estimation(
    item: WeightEstimationItem,
) -> WeightItemOk | WeightItemError | WeightItemClarification:
    if item.status == "clarification":
        if not item.question.strip():
            raise ValueError("clarification без вопроса")
        if item.total_weight_g > 0 and not item.components:
            raise ValueError("clarification с весом, но без компонентов")
        return WeightItemClarification(
            components=item.components,
            total_weight_g=item.total_weight_g,
            question=item.question,
        )
    if item.status == "ok":
        if not item.components or item.total_weight_g <= 0:
            return WeightItemError(
                error_code=WeightEstimationErrorCode.OTHER,
                error="",
            )
        return WeightItemOk(
            components=item.components,
            total_weight_g=item.total_weight_g,
            reasoning=item.reasoning,
            verification=item.verification,
        )
    return WeightItemError(
        error_code=_parse_weight_error_code(item.error_code),
        error=item.error,
    )
