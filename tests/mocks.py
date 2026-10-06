"""
Заглушки для внешних зависимостей: OpenAI, ImageProcessor.
Используются в fixtures conftest.py.
"""

import base64
import json
from typing import Any, Optional  # noqa: F401


_VISUAL_CLASSIFICATION_RESPONSE = json.dumps(
    {
        "reasoning": "кандидаты → признаки → выбран тестовый объект",
        "status": "ok",
        "primary_label": "тестовый объект",
        "category": "unknown",
        "confidence": "medium",
        "visible_signals": ["тестовый визуальный сигнал"],
        "contradicting_signals": [],
        "alternatives": [],
        "summary": "Тестовая классификация",
    }
)

# Дефолтные ответы для двухвызовной архитектуры (V2, компонентная схема)
_DEFAULT_IDENTIFICATION = json.dumps(
    {
        "status": "ok",
        "name": "Тестовое блюдо",
        "emoji": "🍽️",
        "components": [
            {
                "name": "Тестовый компонент",
                "description": "Тестовое блюдо средней плотности",
                "placement": "separate",
                "attached_to": "",
                "calories_per_100g": 166.7,
                "protein_per_100g": 8.3,
                "fat_per_100g": 5.0,
                "carbs_per_100g": 23.3,
            }
        ],
        "reasoning": "Определено по визуальным признакам",
        "verification": "",
        "error_code": "",
        "error": "",
    }
)

_DEFAULT_WEIGHT = json.dumps(
    {
        "status": "ok",
        "components": [
            {"name": "Тестовый компонент", "weight_g": 175.0},
        ],
        "total_weight_g": 175.0,
        "reasoning": "Оценено по визуальному размеру",
        "verification": "",
        "error_code": "",
        "error": "",
    }
)

_DEFAULT_MEAL = json.dumps(
    {
        "status": "ok",
        "meals": [
            {
                "name": "Тестовое блюдо",
                "emoji": "🍽️",
                "count": 1,
                "estimated_weight_g": {"min": 150, "max": 200},
                "calories_kcal": {"min": 200, "max": 300},
                "protein_g": {"min": 10, "max": 15},
                "fat_g": {"min": 5, "max": 10},
                "carbs_g": {"min": 30, "max": 40},
                "confidence": "medium",
                "confidence_reason": "Тестовый ответ",
            }
        ],
        "error": "",
        "question": "",
        "barcode": "",
    }
)


def _to_json(r) -> str:
    return json.dumps(r) if isinstance(r, dict) else r


class MockOpenAIClient:
    """Возвращает фиксированный ответ без обращения к OpenAI API.

    Поддерживает три режима:
    1. response=None — дефолтные ответы для всех типов вызовов
    2. response=dict/str — используется для meal_response (старый формат)
    3. Именованные параметры identification/weight — для двухвызовной архитектуры
    """

    def __init__(
        self,
        response: str | dict | None = None,
        *,
        identification: str | dict | None = None,
        weight: str | dict | None = None,
    ):
        self._meal = _to_json(response) if response is not None else _DEFAULT_MEAL
        self._identification = (
            _to_json(identification)
            if identification is not None
            else _DEFAULT_IDENTIFICATION
        )
        self._weight = _to_json(weight) if weight is not None else _DEFAULT_WEIGHT

    async def get_response(
        self,
        system_prompt=None,
        messages=None,
        response_schema=None,
        response_schema_name: str = "",
        user_id: str = "",
        prompt_cache_scope: Optional[str] = None,
        **kwargs,
    ) -> str:
        name = response_schema_name
        if name == "visual_classification":
            return _VISUAL_CLASSIFICATION_RESPONSE
        if name == "food_identification_response":
            return self._identification
        if name == "weight_estimation_response":
            return self._weight
        return self._meal

    async def close(self) -> None:
        pass


class SequentialMockOpenAIClient:
    """Возвращает ответы по очереди из списка, с учётом типа вызова.

    Поддерживает два режима:
    1. responses=[...] — последовательные ответы для meal_response (старый формат)
    2. Именованные параметры identification=[...], weight=[...] — для двухвызовной архитектуры.
       Каждый список продвигает свой индекс при вызове.
    """

    def __init__(
        self,
        responses: list[str | dict] | None = None,
        *,
        identification: list[str | dict] | None = None,
        weight: list[str | dict] | None = None,
    ):
        self._responses = [_to_json(r) for r in responses] if responses else []
        self._index = 0
        self._identification = (
            [_to_json(r) for r in identification] if identification else []
        )
        self._id_index = 0
        self._weight = [_to_json(r) for r in weight] if weight else []
        self._w_index = 0

    def _next(self, lst, attr):
        idx = getattr(self, attr)
        resp = lst[idx]
        setattr(self, attr, min(idx + 1, len(lst) - 1))
        return resp

    async def get_response(
        self,
        system_prompt=None,
        messages=None,
        response_schema=None,
        response_schema_name: str = "",
        user_id: str = "",
        prompt_cache_scope: Optional[str] = None,
        **kwargs,
    ) -> str:
        name = response_schema_name
        if name == "visual_classification":
            return _VISUAL_CLASSIFICATION_RESPONSE
        if name == "food_identification_response" and self._identification:
            return self._next(self._identification, "_id_index")
        if name == "weight_estimation_response" and self._weight:
            return self._next(self._weight, "_w_index")
        if self._responses:
            return self._next(self._responses, "_index")
        # Fallback для двухвызовной архитектуры без явных списков
        if name == "food_identification_response":
            return _DEFAULT_IDENTIFICATION
        if name == "weight_estimation_response":
            return _DEFAULT_WEIGHT
        return _DEFAULT_MEAL

    async def close(self) -> None:
        pass


# ─── Telegram Bot mocks ──────────────────────────────────────────────────────


class MockChat:
    def __init__(self, chat_id: int):
        self.id = chat_id


class MockUser:
    def __init__(self, user_id: int):
        self.id = user_id


class MockPhotoSize:
    def __init__(self, file_id: str):
        self.file_id = file_id


class MockMessage:
    """Мок aiogram Message — отслеживает edit_text, delete, answer."""

    def __init__(self, message_id: int, chat_id: int, text: str = "", bot=None):
        self.message_id = message_id
        self.chat = MockChat(chat_id)
        self.from_user = MockUser(1)
        self.text = text
        self.caption = None
        self.photo = None
        self.reply_markup = None
        self.bot = bot

    async def edit_text(self, text, **kwargs):
        if self.bot:
            self.bot.edited_texts.append((self.chat.id, self.message_id, text))
        self.text = text

    async def edit_reply_markup(self, reply_markup=None, **kwargs):
        self.reply_markup = reply_markup

    async def delete(self):
        if self.bot:
            self.bot.deleted_messages.append((self.chat.id, self.message_id))

    async def answer(self, text, **kwargs):
        return await self.bot.send_message(self.chat.id, text, **kwargs)


class MockBot:
    """Мок aiogram Bot — записывает все операции с сообщениями."""

    def __init__(self):
        self._msg_counter = 100  # start from 100 to avoid collision with test IDs
        self.sent_messages: list[MockMessage] = []
        self.deleted_messages: list[tuple[int, int]] = []  # (chat_id, message_id)
        self.edited_texts: list[tuple[int, int, str]] = []  # (chat_id, msg_id, text)
        self.edited_captions: list[tuple[int, int, str]] = []
        self.pinned: list[tuple[int, int]] = []  # (chat_id, message_id)
        self.unpinned: list[tuple[int, int]] = []

    def _next_msg(self, chat_id: int, text: str = "") -> MockMessage:
        self._msg_counter += 1
        msg = MockMessage(self._msg_counter, chat_id, text, bot=self)
        self.sent_messages.append(msg)
        return msg

    async def send_message(self, chat_id, text="", **kwargs):
        return self._next_msg(chat_id, text)

    async def send_photo(self, chat_id, photo, **kwargs):
        msg = self._next_msg(chat_id, kwargs.get("caption", ""))
        msg.caption = kwargs.get("caption", "")
        msg.photo = [MockPhotoSize(f"file_id_{msg.message_id}")]
        msg.sent_photo_arg = photo  # трекаем что передали в photo
        msg.reply_markup = kwargs.get("reply_markup")  # инлайн-кнопки на фото
        return msg

    async def send_media_group(self, chat_id, media, **kwargs):
        # Возвращает по сообщению на каждый элемент медиа-группы; у каждого — photo
        msgs = []
        for _ in media:
            m = self._next_msg(chat_id)
            m.photo = [MockPhotoSize(f"file_id_{m.message_id}")]
            msgs.append(m)
        return msgs

    async def delete_message(self, chat_id, message_id):
        self.deleted_messages.append((chat_id, message_id))

    async def edit_message_text(self, chat_id, message_id, text, **kwargs):
        self.edited_texts.append((chat_id, message_id, text))

    async def edit_message_caption(self, chat_id, message_id, caption, **kwargs):
        self.edited_captions.append((chat_id, message_id, caption))

    async def edit_message_reply_markup(self, chat_id, message_id, **kwargs):
        self.edited_markups = getattr(self, "edited_markups", [])
        self.edited_markups.append((chat_id, message_id, kwargs.get("reply_markup")))

    async def edit_message_media(self, chat_id, message_id, media, **kwargs):
        caption = getattr(media, "caption", "") or ""
        self.edited_captions.append((chat_id, message_id, caption))
        self.edited_media = getattr(self, "edited_media", [])
        self.edited_media.append((chat_id, message_id, media))

    async def pin_chat_message(self, chat_id, message_id, **kwargs):
        self.pinned.append((chat_id, message_id))

    async def unpin_chat_message(self, chat_id, message_id=None, **kwargs):
        self.unpinned.append((chat_id, message_id))

    async def send_invoice(self, chat_id, **kwargs):
        self.sent_invoices = getattr(self, "sent_invoices", [])
        self.sent_invoices.append({"chat_id": chat_id, **kwargs})
        return self._next_msg(chat_id, f"invoice:{kwargs.get('payload', '')}")

    def sent_texts(self) -> list[str]:
        """Тексты всех отправленных сообщений по порядку."""
        return [m.text for m in self.sent_messages]

    def deleted_msg_ids(self, chat_id: int) -> list[int]:
        """message_id всех удалённых сообщений для chat_id."""
        return [mid for cid, mid in self.deleted_messages if cid == chat_id]

    def edited_msg_ids(self, chat_id: int) -> list[int]:
        """message_id всех отредактированных сообщений для chat_id."""
        return [mid for cid, mid, _ in self.edited_texts if cid == chat_id]


class MockI18n:
    """Мок I18nContext — возвращает ключи как есть (с параметрами через |).

    Для LBL_MONTHS_GEN возвращает 12 месяцев (нужно formatter/date_picker).
    """

    _SPECIAL = {
        "lbl-months-gen": "янв фев мар апр май июн июл авг сен окт ноя дек",
        "msg-chart-months-short": "янв фев мар апр май июн июл авг сен окт ноя дек",
        "lbl-weekdays-short": "Пн Вт Ср Чт Пт Сб Вс",
        "lbl-weekdays-full": "Понедельник Вторник Среда Четверг Пятница Суббота Воскресенье",
    }

    def get(self, key, **kwargs):
        if key in self._SPECIAL:
            return self._SPECIAL[key]
        if kwargs:
            parts = [f"{k}={v}" for k, v in kwargs.items()]
            return f"{key}|{'|'.join(parts)}"
        return key

    @property
    def locale(self):
        return "ru"


class MockImageProcessor:
    """Возвращает fake base64 без реального ресайза."""

    async def process_images(self, images: list[bytes]) -> list[str]:
        return [base64.b64encode(img).decode() for img in images]

    def shutdown(self, wait: bool = False) -> None:
        pass
