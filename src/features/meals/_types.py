from dataclasses import dataclass, field
from enum import StrEnum
from typing import Optional, TypedDict

from src.core.llm.meal_model import Meal


class HistoryRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


class HistoryEntry(TypedDict, total=False):
    role: str
    text: str
    has_photos: bool
    extra_images: list[str]


@dataclass
class AnalysisResult:
    """Результат анализа фотографий.

    При успехе содержит список блюд (pydantic-модели) и метаданные фото.
    Сохранение в БД — ответственность хендлера (после отправки карточки в Telegram).
    """

    meals: list[Meal] = field(default_factory=list)
    caption: str = ""
    error: Optional[str] = None
    error_text: Optional[str] = None
    # Уточняющий вопрос от модели (V2 clarification). НЕ входит в ok:
    # ветвление отображения — if clarification → elif not ok → display.
    clarification: Optional[str] = None
    clarification_call: Optional[str] = None  # "identification" | "weight"
    source: str = "ai"  # "ai" | "barcode" — источник для meal.saved.source

    @property
    def ok(self) -> bool:
        return self.error is None and not self.error_text
