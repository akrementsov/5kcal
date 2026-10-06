from datetime import datetime, date, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

_UTC = timezone.utc


def _get_tz(tz_name: str) -> ZoneInfo | timezone:
    try:
        return ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, KeyError):
        return _UTC


def today_for_tz(tz_name: str) -> date:
    """Сегодняшняя дата в timezone пользователя."""
    return datetime.now(_get_tz(tz_name)).date()


def utc_now_naive() -> datetime:
    """Текущее время в UTC без tzinfo для хранения в существующей схеме БД."""
    return datetime.now(_UTC).replace(tzinfo=None)


def date_in_tz(dt: datetime, tz_name: str) -> date:
    """Конвертирует naive-UTC datetime из БД в дату в timezone пользователя."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_UTC)
    return dt.astimezone(_get_tz(tz_name)).date()


def local_date_to_utc_naive(
    d: date,
    tz_name: str,
    hour: int = 12,
    minute: int = 0,
    second: int = 0,
) -> datetime:
    """Локальная дата/время пользователя -> naive UTC для записи в БД."""
    local_dt = datetime(
        d.year, d.month, d.day, hour, minute, second, tzinfo=_get_tz(tz_name)
    )
    return local_dt.astimezone(_UTC).replace(tzinfo=None)


def end_of_day_utc(d: date, tz_name: str) -> datetime:
    """Конец дня d (23:59:59) в timezone пользователя → naive UTC для записи в БД."""
    return local_date_to_utc_naive(d, tz_name, hour=23, minute=59, second=59)


def current_hour_in_tz(tz_name: str) -> int:
    """Текущий час в timezone пользователя (0-23)."""
    return datetime.now(_get_tz(tz_name)).hour


def day_bounds_utc(d: date, tz_name: str) -> tuple[datetime, datetime]:
    """Начало и конец дня (naive UTC) для даты d в timezone пользователя.
    Используется для фильтрации по created_at в БД."""
    tz = _get_tz(tz_name)
    start = datetime(d.year, d.month, d.day, tzinfo=tz)
    end = start + timedelta(days=1)
    return start.astimezone(_UTC).replace(tzinfo=None), end.astimezone(_UTC).replace(
        tzinfo=None
    )
