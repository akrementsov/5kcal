"""Банлист пользователей: полный запрет пользоваться ботом.

Хранится в Redis-множестве, проверяется в BanMiddleware (outer) до любой
обработки апдейта и до LLM — забаненный не тратит ресурсы.

Отдельно держим ключ-троттл уведомления о бане (`ban:notified:{id}` с TTL),
чтобы не спамить забаненного сообщением на каждое его сообщение.
"""

from src.core.user_state import redis_storage as rs

_KEY_BANNED_USERS = "ban:users"
_KEY_BAN_NOTIFIED = "ban:notified:{user_id}"
_NOTIFY_TTL_SECONDS = 3600  # не чаще раза в час напоминаем о бане


async def ban_user(user_id: int) -> None:
    await rs.get_redis().sadd(_KEY_BANNED_USERS, str(user_id))


async def unban_user(user_id: int) -> None:
    r = rs.get_redis()
    pipe = r.pipeline()
    pipe.srem(_KEY_BANNED_USERS, str(user_id))
    pipe.delete(_KEY_BAN_NOTIFIED.format(user_id=user_id))
    await pipe.execute()


async def is_banned(user_id: int) -> bool:
    return bool(await rs.get_redis().sismember(_KEY_BANNED_USERS, str(user_id)))


async def get_banned_users() -> list[int]:
    raw = await rs.get_redis().smembers(_KEY_BANNED_USERS)
    return sorted(int(uid) for uid in raw)


async def claim_ban_notify(user_id: int) -> bool:
    """Резервирует окно уведомления: True — можно слать сообщение о бане сейчас.

    SET NX EX: первый вызов в окне TTL возвращает True, последующие — False.
    """
    was_set = await rs.get_redis().set(
        _KEY_BAN_NOTIFIED.format(user_id=user_id),
        "1",
        nx=True,
        ex=_NOTIFY_TTL_SECONDS,
    )
    return bool(was_set)
