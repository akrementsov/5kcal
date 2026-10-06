"""Утилиты сборки сообщений для запросов к LLM."""

from typing import Optional

from src.core.llm.models import MessageRole, Content
from src.core.llm.local_prompts import render_food_info_context
from src.core.llm.two_call_models import FoodInfo

from ._types import HistoryEntry, HistoryRole


def _build_two_call_messages(
    base64_images: list[str],
    caption: str,
    history: list[HistoryEntry],
    extra_base64: list[str],
    user_text: Optional[str],
    food_info: Optional[FoodInfo] = None,
) -> list:
    """Собирает список сообщений для двухвызовной архитектуры."""
    first_content: list[Content] = []
    if food_info is not None:
        first_content.append(Content.from_text(render_food_info_context([food_info])))
    first_content += [Content.image(b64, detail="high") for b64 in base64_images]
    if caption and caption.strip():
        first_content.append(Content.from_text(caption))

    messages = [(MessageRole.USER, first_content)]

    for entry in history:
        role = entry.get("role")
        text = entry.get("text", "")
        if role == HistoryRole.ASSISTANT and text:
            messages.append((MessageRole.ASSISTANT, [Content.output_text(text)]))
        elif role == HistoryRole.USER:
            user_content: list[Content] = []
            for b64 in entry.get("extra_images", []):
                user_content.append(Content.image(b64, detail="high"))
            if text:
                user_content.append(Content.from_text(text))
            if user_content:
                messages.append((MessageRole.USER, user_content))

    if extra_base64 or (user_text and user_text.strip()):
        current_content: list[Content] = [
            Content.image(b64, detail="high") for b64 in extra_base64
        ]
        if user_text and user_text.strip():
            current_content.append(Content.from_text(user_text))
        messages.append((MessageRole.USER, current_content))

    return messages
