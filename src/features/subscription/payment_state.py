"""
payment_state.py — Redis-backed состояние платежей.

Заменяет модульные dict/set в handlers.py. Все данные сохраняются в Redis
и переживают рестарт бота.
"""

import time
from typing import Optional

from redis.asyncio import Redis

from src.core.utils import get_logger

logger = get_logger()

# Redis ключи
_KEY_GLOBAL_DISABLED = "pay:disabled"
_KEY_DISABLED_USERS = "pay:disabled_users"
_KEY_ENABLED_USERS = "pay:enabled_users"
_KEY_PROMO_USERS = "pay:promo_users"
_KEY_PENDING_INVOICE = "pay:pending_invoice:{user_id}"
_KEY_ROBOKASSA_INV_COUNTER = "pay:robokassa:inv_counter"
_KEY_ROBOKASSA_PENDING = "pay:robokassa:{inv_id}"
_KEY_ROBOKASSA_TEST_MODE = "pay:robokassa:test_mode:{user_id}"

# Инвойс считается протухшим через 1 час
_PENDING_INVOICE_MAX_AGE = 3600
# Не сканировать чаще раза в минуту
_CLEANUP_MIN_INTERVAL = 60
_last_cleanup_ts: float = 0.0
# TTL в Redis — подстраховка на случай, если cleanup не отработает
_PENDING_INVOICE_TTL = 86400  # 24 часа

# TTL для Robokassa pending invoice — 1 час на оплату
_ROBOKASSA_PENDING_TTL = 3600

# ─── Module-level Redis client ───────────────────────────────────────────────

_redis: Optional[Redis] = None


def init_payment_state(redis: Redis) -> None:
    """Инициализирует Redis-клиент. Вызывается из main.py."""
    global _redis
    _redis = redis


def _get_redis() -> Redis:
    if _redis is None:
        raise RuntimeError(
            "PaymentState не инициализирован. Вызовите init_payment_state() перед использованием."
        )
    return _redis


# ─── Pending invoices ────────────────────────────────────────────────────────


async def add_pending_invoice(user_id: int, message_id: int) -> None:
    r = _get_redis()
    key = _KEY_PENDING_INVOICE.format(user_id=user_id)
    value = f"{message_id}:{int(time.time())}"
    await r.set(key, value, ex=_PENDING_INVOICE_TTL)


async def pop_pending_invoice(user_id: int) -> Optional[int]:
    r = _get_redis()
    key = _KEY_PENDING_INVOICE.format(user_id=user_id)
    raw = await r.getdel(key)
    if not raw:
        return None
    return int(raw.split(":")[0])


async def collect_stale_invoices() -> list[tuple[int, int]]:
    """Возвращает [(chat_id, message_id), ...] для инвойсов старше _PENDING_INVOICE_MAX_AGE
    и удаляет их ключи из Redis. Вызывающий код отвечает за удаление сообщений из Telegram.
    Вызовы чаще раза в минуту пропускаются.
    """
    global _last_cleanup_ts
    now = time.time()
    if now - _last_cleanup_ts < _CLEANUP_MIN_INTERVAL:
        return []
    _last_cleanup_ts = now

    r = _get_redis()
    now_i = int(now)
    stale: list[tuple[int, int]] = []
    keys_to_delete: list[str] = []

    async for key in r.scan_iter(match="pay:pending_invoice:*"):
        raw = await r.get(key)
        if not raw:
            continue
        try:
            parts = raw.split(":")
            message_id = int(parts[0])
            created_at = int(parts[1])
        except (ValueError, IndexError):
            keys_to_delete.append(key)
            continue

        if now_i - created_at >= _PENDING_INVOICE_MAX_AGE:
            # user_id из ключа pay:pending_invoice:{user_id}
            user_id = int(key.split(":")[-1])
            stale.append((user_id, message_id))
            keys_to_delete.append(key)

    if keys_to_delete:
        await r.delete(*keys_to_delete)

    return stale


# ─── Robokassa invoices ────────────────────────────────────────────────────


async def create_robokassa_invoice(
    user_id: int, period: int, amount: int, is_test: bool = False
) -> int:
    """Создаёт InvId через атомарный INCR, сохраняет данные в Redis с TTL."""
    import json

    r = _get_redis()
    inv_id = await r.incr(_KEY_ROBOKASSA_INV_COUNTER)
    key = _KEY_ROBOKASSA_PENDING.format(inv_id=inv_id)
    data = json.dumps(
        {
            "user_id": user_id,
            "period": period,
            "amount": amount,
            "is_test": is_test,
        }
    )
    await r.set(key, data, ex=_ROBOKASSA_PENDING_TTL)
    return inv_id


async def seed_robokassa_inv_counter(db) -> None:
    """Сидирует счётчик InvId из истории платежей, если ключа нет в Redis
    (флеш/переезд Redis без RDB/AOF). InvId уникален в рамках магазина —
    обнулённый счётчик заставит Robokassa отклонять новые инвойсы как дубли."""
    r = _get_redis()
    if await r.exists(_KEY_ROBOKASSA_INV_COUNTER):
        return
    from src.core.database import db as db_funcs

    with db.session() as session:
        max_inv = db_funcs.get_max_robokassa_inv_id(session)
    if max_inv:
        await r.set(_KEY_ROBOKASSA_INV_COUNTER, max_inv, nx=True)
        logger.info(
            "Счётчик Robokassa InvId сидирован из БД", extra={"max_inv": max_inv}
        )


async def get_robokassa_invoice(inv_id: int) -> Optional[dict]:
    """Читает инвойс БЕЗ удаления — для валидации перед завершением."""
    import json

    r = _get_redis()
    key = _KEY_ROBOKASSA_PENDING.format(inv_id=inv_id)
    raw = await r.get(key)
    if not raw:
        return None
    return json.loads(raw)


async def delete_robokassa_invoice(inv_id: int) -> None:
    """Удаляет инвойс после успешной обработки."""
    r = _get_redis()
    await r.delete(_KEY_ROBOKASSA_PENDING.format(inv_id=inv_id))


_KEY_ROBOKASSA_DONE = "pay:robokassa:done:{inv_id}"


# Done-ключ живёт дольше инвойса: ловит поздние дубли callback-ов
_ROBOKASSA_DONE_TTL = 86400


async def mark_robokassa_processed(inv_id: int) -> bool:
    """Атомарный idempotency guard (SETNX). True = первая обработка."""
    r = _get_redis()
    result = await r.set(
        _KEY_ROBOKASSA_DONE.format(inv_id=inv_id),
        "1",
        ex=_ROBOKASSA_DONE_TTL,
        nx=True,
    )
    return result is not None


async def unmark_robokassa_processed(inv_id: int) -> None:
    """Откатывает idempotency guard — при сбое активации, чтобы ретрай Robokassa
    смог обработать платёж заново."""
    r = _get_redis()
    await r.delete(_KEY_ROBOKASSA_DONE.format(inv_id=inv_id))


async def is_robokassa_processed(inv_id: int) -> bool:
    r = _get_redis()
    return bool(await r.exists(_KEY_ROBOKASSA_DONE.format(inv_id=inv_id)))


# ─── Robokassa test mode ──────────────────────────────────────────────────


# Забытый /pay_mode test не должен жить вечно
_ROBOKASSA_TEST_MODE_TTL = 86400


async def set_robokassa_test_mode(user_id: int, is_test: bool) -> None:
    r = _get_redis()
    key = _KEY_ROBOKASSA_TEST_MODE.format(user_id=user_id)
    if is_test:
        await r.set(key, "1", ex=_ROBOKASSA_TEST_MODE_TTL)
    else:
        await r.delete(key)


async def is_robokassa_test_mode(user_id: int) -> bool:
    r = _get_redis()
    key = _KEY_ROBOKASSA_TEST_MODE.format(user_id=user_id)
    return bool(await r.exists(key))


# ─── Global payments disable ────────────────────────────────────────────────


async def set_payments_disabled(disabled: bool) -> None:
    r = _get_redis()
    if disabled:
        await r.set(_KEY_GLOBAL_DISABLED, "1")
    else:
        pipe = r.pipeline()
        pipe.delete(_KEY_GLOBAL_DISABLED)
        pipe.delete(_KEY_DISABLED_USERS)
        pipe.delete(_KEY_ENABLED_USERS)
        await pipe.execute()


async def is_payments_disabled() -> bool:
    r = _get_redis()
    return bool(await r.exists(_KEY_GLOBAL_DISABLED))


# ─── Per-user payments disable ──────────────────────────────────────────────


async def set_user_payments_disabled(user_id: int, disabled: bool) -> None:
    r = _get_redis()
    uid = str(user_id)
    pipe = r.pipeline()
    if disabled:
        pipe.sadd(_KEY_DISABLED_USERS, uid)
        pipe.srem(_KEY_ENABLED_USERS, uid)
    else:
        pipe.srem(_KEY_DISABLED_USERS, uid)
        pipe.sadd(_KEY_ENABLED_USERS, uid)
    await pipe.execute()


async def is_user_payments_blocked(user_id: int) -> bool:
    r = _get_redis()
    uid = str(user_id)
    if await r.sismember(_KEY_DISABLED_USERS, uid):
        return True
    if await r.exists(_KEY_GLOBAL_DISABLED) and not await r.sismember(
        _KEY_ENABLED_USERS, uid
    ):
        return True
    return False


async def get_payments_status() -> dict:
    r = _get_redis()
    global_disabled = bool(await r.exists(_KEY_GLOBAL_DISABLED))
    disabled_raw = await r.smembers(_KEY_DISABLED_USERS)
    enabled_raw = await r.smembers(_KEY_ENABLED_USERS)
    disabled_users = {int(uid) for uid in disabled_raw}
    enabled_users = {int(uid) for uid in enabled_raw}
    return {
        "global_disabled": global_disabled,
        "disabled_users": disabled_users,
        "enabled_users": enabled_users,
    }


# ─── Promo ──────────────────────────────────────────────────────────────────


async def set_user_promo(user_id: int, active: bool) -> None:
    r = _get_redis()
    uid = str(user_id)
    if active:
        await r.sadd(_KEY_PROMO_USERS, uid)
    else:
        await r.srem(_KEY_PROMO_USERS, uid)


async def has_promo(user_id: int) -> bool:
    r = _get_redis()
    return bool(await r.sismember(_KEY_PROMO_USERS, str(user_id)))


async def get_promo_users() -> set[int]:
    r = _get_redis()
    raw = await r.smembers(_KEY_PROMO_USERS)
    return {int(uid) for uid in raw}
