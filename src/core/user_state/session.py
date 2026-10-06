"""
Модель сессии анализа блюд.

Единая структура для двух режимов многораундового диалога с ИИ:
  CREATE — новый анализ (фото/текст + возможные уточнения)
  UPDATE — редактирование существующего блюда

Хранится в Redis по ключу session:{chat_id}.
Быстрый режим (без JSON-парсинга) доступен через session_mode:{chat_id}.
"""

from enum import StrEnum
from pydantic import BaseModel


class SessionMode(StrEnum):
    CREATE = "create"
    UPDATE = "update"


class CallPhase(StrEnum):
    IDENTIFICATION = "identification"
    WEIGHT = "weight"


class AnalysisSession(BaseModel):
    mode: SessionMode
    caption: str = ""
    base64_images: list[str] = []
    history: list[dict] = []
    round: int = 0
    messages_to_delete: list[int] = []
    telegram_file_ids: list[str] = []  # оригинальные file_id фото пользователя
    # Только для mode=UPDATE (редактирование):
    meal_id: int | None = None
    meal_card_msg_id: int | None = None
    loading_msg_id: int | None = None
    # Двухвызовная архитектура (CREATE/UPDATE mode):
    call_phase: CallPhase | None = None
    food_info: dict | None = (
        None  # сериализованный FoodInfo, нужен при call_phase=WEIGHT
    )
    # Clarification (V2): черновик Call 2, ждущий подтверждения веса
    weight_info: dict | None = None
    # Исходные фото-сообщения пользователя (для показа карточки после ответа)
    original_msg_ids: list[int] = []
