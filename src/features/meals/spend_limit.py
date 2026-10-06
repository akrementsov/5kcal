"""Суточный бюджет LLM-расходов на пользователя (анти-абьюз).

Спека: docs/superpowers/specs/2026-07-06-llm-spend-limit-design.md.
Стоимость каждого LLM-вызова (по прайсу из конфига) копится в Redis-ключе
llm_spend:{user_id}:{YYYY-MM-DD} — дата по таймзоне пользователя, значение
в копейках. Guard в meals/handler блокирует новый анализ при превышении
config.llm_daily_budget_kop. Ошибки учёта не ломают анализ.
"""

import asyncio
import math
import time

from config.bot import config
from src.core.database import db as db_funcs
from src.core.user_state import redis_storage as rs
from src.core.utils import get_logger
from src.core.utils.admin_notify import notify_admin
from src.core.utils.tz import date_in_tz, today_for_tz

logger = get_logger()

_SPEND_TTL_S = 48 * 3600  # ключ живёт двое суток — переживает смену дня

_bg_tasks: set = set()
_db = None

# Кэш таймзоны пользователя: убирает 3-4 блокирующих запроса к БД на анализ
# (is_over_budget + add_spend на каждый LLM-вызов). tz меняется редко.
_tz_cache: dict[int, tuple[str, float]] = {}
_TZ_CACHE_TTL_S = 300

# Кэш даты регистрации (created_at иммутабелен): нужен для «первого дня»,
# читается в is_over_budget на каждый анализ — без кэша был бы лишний запрос к БД.
_created_at_cache: dict[int, tuple[object, float]] = {}


def init_spend_limit(db) -> None:
    """Вызывается из main.py после создания Database (паттерн init_*)."""
    global _db
    _db = db


def call_cost_kop(usage: dict) -> int:
    """Стоимость LLM-вызова в копейках по прайсу из конфига.

    cached-токены — часть input по сниженной цене: (input−cached) по полной.
    """
    inp = usage.get("input_tokens") or 0
    out = usage.get("output_tokens") or 0
    cached = usage.get("cached_tokens") or 0
    fresh_in = max(inp - cached, 0)
    cost = (
        fresh_in * config.llm_price_kop_per_1m_input
        + cached * config.llm_price_kop_per_1m_cached
        + out * config.llm_price_kop_per_1m_output
    ) / 1_000_000
    return math.ceil(cost)


def _user_tz(user_id: int) -> str:
    if _db is None:
        return "UTC"
    with _db.session() as session:
        tz, _ = db_funcs.get_user_timezone(session, user_id)
    return tz


def _user_tz_cached(user_id: int) -> str:
    """Таймзона пользователя из кэша; при промахе — один запрос к БД.

    Кэш убирает 3-4 повторных запроса одной и той же tz за анализ. tz меняется
    редко, поэтому короткий TTL безопасен."""
    now = time.monotonic()
    cached = _tz_cache.get(user_id)
    if cached and now - cached[1] < _TZ_CACHE_TTL_S:
        return cached[0]
    tz = _user_tz(user_id)
    _tz_cache[user_id] = (tz, now)
    return tz


def _user_created_at(user_id: int):
    """Дата регистрации (naive UTC) или None. None → трактуем как не первый день.

    Ошибки БД не пробрасываем — учёт лимита не должен ронять анализ (см. docstring
    модуля). При сбое возвращаем None → обычный бюджет (fail-safe)."""
    if _db is None:
        return None
    try:
        with _db.session() as session:
            return db_funcs.get_user_created_at(session, user_id)
    except Exception as e:
        logger.warning(
            "Не удалось прочитать дату регистрации",
            extra={"chat_id": user_id, "error": str(e)},
        )
        return None


def _user_created_at_cached(user_id: int):
    now = time.monotonic()
    cached = _created_at_cache.get(user_id)
    if cached and now - cached[1] < _TZ_CACHE_TTL_S:
        return cached[0]
    created = _user_created_at(user_id)
    _created_at_cache[user_id] = (created, now)
    return created


def _is_first_day(user_id: int) -> bool:
    """Сегодня (в tz юзера) == дата его регистрации. Триал авто-стартует на
    /start вместе с созданием юзера, поэтому это же и первый день триала.

    Любой сбой (нет created_at, битый tz) → False: обычный бюджет, не блокируем."""
    try:
        created = _user_created_at_cached(user_id)
        if created is None:
            return False
        tz = _user_tz_cached(user_id)
        return today_for_tz(tz) == date_in_tz(created, tz)
    except Exception:
        return False


def _applicable_budget_kop(user_id: int) -> int:
    """Планка бюджета: повышенная в первый день, обычная дальше."""
    if _is_first_day(user_id):
        return config.llm_first_day_budget_kop
    return config.llm_daily_budget_kop


def _spend_key(user_id: int) -> str:
    return f"llm_spend:{user_id}:{today_for_tz(_user_tz_cached(user_id)).isoformat()}"


def record_call(user_id: int, usage: dict) -> None:
    """Sync-обёртка для usage-sink: планирует инкремент, ничего не ждёт."""
    cost = call_cost_kop(usage)
    if cost <= 0:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return  # вне event loop (не боевой сценарий) — просто не учитываем
    task = loop.create_task(add_spend(user_id, cost))
    _bg_tasks.add(task)
    task.add_done_callback(_bg_tasks.discard)


async def add_spend(user_id: int, cost_kop: int) -> None:
    """Инкремент суточного счётчика. Ошибки — warning, не пробрасываются."""
    try:
        key = _spend_key(user_id)
        redis = rs.get_redis()
        await redis.incrby(key, cost_kop)
        await redis.expire(key, _SPEND_TTL_S)
    except Exception as e:
        logger.warning(
            "Не удалось записать LLM-расход",
            extra={"chat_id": user_id, "error": str(e)},
        )


async def get_spent_kop(user_id: int) -> int:
    try:
        value = await rs.get_redis().get(_spend_key(user_id))
        return int(value) if value else 0
    except Exception as e:
        logger.warning(
            "Не удалось прочитать LLM-расход",
            extra={"chat_id": user_id, "error": str(e)},
        )
        return 0  # при недоступном Redis не блокируем пользователей


async def is_over_budget(user_id: int) -> bool:
    return await get_spent_kop(user_id) >= _applicable_budget_kop(user_id)


async def alert_if_first(user_id: int) -> None:
    """Алерт в админ-чат при первом за день срабатывании лимита."""
    try:
        if not await mark_limit_alerted(user_id):
            return
        spent = await get_spent_kop(user_id)
        await notify_admin(
            f"⚠️ user {user_id} упёрся в дневной лимит LLM "
            f"(потрачено {spent / 100:.2f}₽)"
        )
    except Exception as e:
        logger.warning(
            "Не удалось отправить алерт о лимите",
            extra={"chat_id": user_id, "error": str(e)},
        )


async def reset_spend(user_id: int) -> None:
    """Сброс дневного счётчика и флага алерта (админ-команда /limit_reset).

    В отличие от остальных функций модуля ошибки пробрасываются — команду
    вызывает админ и должен увидеть сбой, а не молчаливый «успех».
    """
    key = _spend_key(user_id)
    await rs.get_redis().delete(key, f"{key}:alerted")


async def mark_limit_alerted(user_id: int) -> bool:
    """SETNX-флаг «алерт за сегодня уже был». True — если это первый раз."""
    try:
        key = f"{_spend_key(user_id)}:alerted"
        redis = rs.get_redis()
        first = await redis.setnx(key, "1")
        if first:
            await redis.expire(key, _SPEND_TTL_S)
        return bool(first)
    except Exception as e:
        logger.warning(
            "Не удалось выставить флаг алерта лимита",
            extra={"chat_id": user_id, "error": str(e)},
        )
        return False
