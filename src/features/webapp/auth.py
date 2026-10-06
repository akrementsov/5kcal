"""Валидация Telegram Mini App initData для webapp API.

Фронтенд шлёт заголовок `Authorization: tma <initData>` (конвенция Mini Apps).
Подпись проверяется по алгоритму Telegram через aiogram.
Дополнительно отбрасываются данные старше 24 часов (защита от replay-атак).
"""

from datetime import datetime, timedelta, timezone

from aiogram.utils.web_app import WebAppInitData, safe_parse_webapp_init_data

from config.bot import config

_SCHEME = "tma "
_MAX_AGE = timedelta(hours=24)


def parse_auth_header(auth_header: str | None) -> WebAppInitData | None:
    """Возвращает распарсенный initData при валидной подписи и свежем auth_date.

    Возвращает None если:
    - заголовок отсутствует или не начинается со схемы «tma »;
    - подпись невалидна;
    - auth_date старше 24 часов (защита от replay-атак).
    """
    if not auth_header or not auth_header.startswith(_SCHEME):
        return None
    init_data = auth_header[len(_SCHEME):]
    try:
        parsed = safe_parse_webapp_init_data(token=config.token, init_data=init_data)
    except ValueError:
        return None
    auth_date: datetime = parsed.auth_date
    # aiogram возвращает aware-UTC datetime; на случай naive нормализуем
    if auth_date.tzinfo is None:
        auth_date = auth_date.replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) - auth_date > _MAX_AGE:
        return None
    return parsed
