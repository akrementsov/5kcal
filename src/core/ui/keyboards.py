from typing import Sequence, NamedTuple, Optional, Union

from aiogram.types import InlineKeyboardMarkup, WebAppInfo
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.filters.callback_data import CallbackData

CbType = Union[str, CallbackData, None]


class Button(NamedTuple):
    text: str
    callback: CbType
    url: Optional[str] = None
    web_app: Optional[str] = None

    @classmethod
    def create(cls, text: str, cb: CbType, url: Optional[str] = None):
        return cls(text, cb, url)

    @classmethod
    def redirect(cls, text: str, url: str):
        return cls(text, None, url)

    @classmethod
    def webapp(cls, text: str, url: str):
        """Кнопка, открывающая Telegram Mini App."""
        return cls(text, None, None, url)


def keyboard(rows: Sequence[Sequence[Button]]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    if rows and isinstance(rows[0], Button):
        rows = [rows]

    for row in rows:
        if not row:
            continue
        for button in row:
            if button.web_app:
                builder.button(text=button.text, web_app=WebAppInfo(url=button.web_app))
            elif button.url:
                builder.button(text=button.text, url=button.url)
            elif isinstance(button.callback, str):
                builder.button(text=button.text, callback_data=button.callback)
            elif isinstance(button.callback, CallbackData):
                builder.button(text=button.text, callback_data=button.callback.pack())

    builder.adjust(*[len(r) for r in rows])
    return builder.as_markup()
