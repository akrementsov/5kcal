import asyncio
from enum import StrEnum
from pathlib import Path
from typing import Any

from aiogram import types
from aiogram_i18n import I18nMiddleware
from aiogram_i18n.cores import FluentRuntimeCore
from aiogram_i18n.managers import BaseManager

from src.core.database import db as db_funcs
from src.core.database.database import Database

LOCALES_DIR = Path(__file__).parent.parent / "locales"


class Locale(StrEnum):
    RU = "ru"
    EN = "en"


DEFAULT_LOCALE = Locale.RU
SUPPORTED_LOCALES = list(Locale)


class DbManager(BaseManager):
    """Менеджер локали, читающий и сохраняющий язык в БД."""

    def __init__(self, db: Database, default_locale: str):
        super().__init__(default_locale=default_locale)
        self._db = db

    def _get_lang_sync(self, user_id: int) -> str | None:
        with self._db.session() as session:
            return db_funcs.get_user_language(session, user_id)

    async def get_locale(
        self, event_from_user: types.User | None = None, **kwargs: Any
    ) -> str:
        if not event_from_user:
            return self.default_locale
        loop = asyncio.get_running_loop()
        lang = await loop.run_in_executor(None, self._get_lang_sync, event_from_user.id)
        if lang in SUPPORTED_LOCALES:
            return lang
        # Язык не задан вручную — определяем по клиенту Telegram
        client_lang = getattr(event_from_user, "language_code", None)
        if client_lang and client_lang in SUPPORTED_LOCALES:
            return client_lang
        return self.default_locale

    async def set_locale(self, locale: str, **kwargs: Any) -> None:
        # Сохранение в БД делается явно в language_handler до вызова i18n.set_locale().
        pass


_core: FluentRuntimeCore | None = None


def get_i18n_core() -> FluentRuntimeCore:
    if _core is None:
        raise RuntimeError("i18n core not initialized")
    return _core


def build_i18n_middleware(db: Database) -> I18nMiddleware:
    global _core
    _core = FluentRuntimeCore(
        path=str(LOCALES_DIR / "{locale}" / "LC_MESSAGES"),
        default_locale=DEFAULT_LOCALE,
    )
    manager = DbManager(db=db, default_locale=DEFAULT_LOCALE)
    return I18nMiddleware(core=_core, manager=manager)
