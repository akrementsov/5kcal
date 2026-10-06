"""
RedisStorage — инфраструктурный класс для навигационного стека и сессий анализа.

Заменяет модульные синглтоны redis_storage.py.
Инстанциируется один раз в main.py, передаётся в сервисы и хендлеры через DI.
"""

from typing import Optional, Dict, Any
import json

from redis.asyncio import Redis
from redis.exceptions import WatchError

from src.core.utils import get_logger
from src.core.user_state.session import AnalysisSession, SessionMode
from src.core.user_state import config as _state_cfg

logger = get_logger()

# TTL-константы из конфига (читаются из env, не из глобального config-синглтона)
_SESSION_TTL = max(_state_cfg.EDITING_TTL, _state_cfg.CLARIFICATION_CTX_TTL)
_ANALYZING_TTL = _state_cfg.ANALYZING_TTL

# Ключи в chat_state hash
# Navigation stacks (по stack_id)
_NAV_STACK_FMT = "nav:{stack_id}:stack"
_NAV_MSG_ID_FMT = "nav:{stack_id}:msg_id"
_NAV_CMD_MSG_ID_FMT = "nav:{stack_id}:cmd_msg_id"
_NAV_FROM_BACK_FMT = "nav:{stack_id}:from_back"
# Ephemeral messages
_LANG_MSG_ID_KEY = "lang_msg_id"
_LANG_CMD_MSG_ID_KEY = "lang_cmd_msg_id"
_LANG_SAVED_MSG_ID_KEY = "lang_saved_msg_id"
_HOWTO_MSG_ID_KEY = "howto_msg_id"
_HOWTO_CMD_MSG_ID_KEY = "howto_cmd_msg_id"
_INFO_MSG_ID_KEY = "info_msg_id"
_TZ_PROMPT_MSG_ID_KEY = "tz_prompt_msg_id"
_GREETING_MSG_ID_KEY = "greeting_msg_id"
_DEMO_MSG_ID_KEY = "demo_msg_id"
_DEMO_ALBUM_IDS_KEY = "demo_album_ids"


# ─── Module-level instance (set once at startup via init_storage) ──────────────

_instance: Optional["RedisStorage"] = None


def init_storage(s: "RedisStorage") -> None:
    """Инициализирует модульный инстанс. Вызывается один раз из main.py и из conftest."""
    global _instance
    _instance = s


def get_storage() -> "RedisStorage":
    """Возвращает инициализированный инстанс. Используется в redis_storage-шиме."""
    if _instance is None:
        raise RuntimeError(
            "RedisStorage не инициализирован. Вызовите init_storage() перед использованием."
        )
    return _instance


class RedisStorage:
    """Обёртка над Redis для хранения состояния навигации и сессий анализа."""

    def __init__(self, redis: Redis, ttl: int):
        """
        Args:
            redis: Подключённый Redis (asyncio) клиент.
            ttl: TTL в секундах для chat_state ключей (из config.redis.ttl).
        """
        self._redis = redis
        self._ttl = ttl

    async def close(self) -> None:
        await self._redis.aclose()

    # ─── Ключи ────────────────────────────────────────────────────────────────

    @staticmethod
    def _session_key(chat_id: int) -> str:
        return f"session:{chat_id}"

    @staticmethod
    def _session_mode_key(chat_id: int) -> str:
        return f"session_mode:{chat_id}"

    @staticmethod
    def _chat_key(chat_id: int) -> str:
        return f"chat_state:{chat_id}"

    @staticmethod
    def _analyzing_key(chat_id: int) -> str:
        return f"analyzing:{chat_id}"

    # ─── Session: CREATE/UPDATE analysis session ───────────────────────────────

    async def get_session(self, chat_id: int) -> Optional[AnalysisSession]:
        """Получить сессию анализа. Возвращает None если сессии нет."""
        raw = await self._redis.get(self._session_key(chat_id))
        if not raw:
            return None
        try:
            return AnalysisSession.model_validate_json(raw)
        except Exception as e:
            logger.warning(
                "Ошибка парсинга сессии из Redis — ключ удалён",
                extra={"chat_id": chat_id, "error": str(e)},
            )
            await self._redis.delete(
                self._session_key(chat_id), self._session_mode_key(chat_id)
            )
            return None

    async def get_session_mode(self, chat_id: int) -> Optional[SessionMode]:
        """Быстрая проверка режима сессии без JSON-парсинга (O(1))."""
        raw = await self._redis.get(self._session_mode_key(chat_id))
        if not raw:
            return None
        try:
            return SessionMode(raw)
        except ValueError:
            return None

    async def save_session(self, chat_id: int, session: AnalysisSession) -> None:
        """Атомарно пишет оба ключа (session: и session_mode:)."""
        pipe = self._redis.pipeline()
        pipe.set(self._session_key(chat_id), session.model_dump_json(), ex=_SESSION_TTL)
        pipe.set(self._session_mode_key(chat_id), session.mode.value, ex=_SESSION_TTL)
        await pipe.execute()

    async def _atomic_session_update(self, chat_id: int, updater) -> None:
        """Атомарно обновляет сессию через WATCH/MULTI (optimistic locking)."""
        key = self._session_key(chat_id)
        mode_key = self._session_mode_key(chat_id)
        for _ in range(3):
            try:
                async with self._redis.pipeline(transaction=True) as pipe:
                    await pipe.watch(key)
                    raw = await pipe.get(key)
                    if not raw:
                        await pipe.unwatch()
                        return
                    try:
                        session = AnalysisSession.model_validate_json(raw)
                    except Exception:
                        await pipe.unwatch()
                        return
                    updated = updater(session)
                    if updated is None:
                        await pipe.unwatch()
                        return
                    pipe.multi()
                    pipe.set(key, updated.model_dump_json(), ex=_SESSION_TTL)
                    pipe.set(mode_key, updated.mode.value, ex=_SESSION_TTL)
                    await pipe.execute()
                    return
            except WatchError:
                continue
        logger.warning(
            "Не удалось атомарно обновить сессию после 3 попыток",
            extra={"chat_id": chat_id},
        )

    async def update_session(self, chat_id: int, **kwargs) -> None:
        """Обновить отдельные поля сессии (merge patch)."""
        await self._atomic_session_update(
            chat_id, lambda s: s.model_copy(update=kwargs)
        )

    async def clear_session(self, chat_id: int) -> None:
        """Удалить сессию (оба ключа атомарно)."""
        await self._redis.delete(
            self._session_key(chat_id), self._session_mode_key(chat_id)
        )

    async def append_message_to_delete(self, chat_id: int, message_id: int) -> None:
        """Добавить message_id в список сообщений для удаления (атомарно)."""

        def _append(session):
            if message_id in session.messages_to_delete:
                return None
            return session.model_copy(
                update={"messages_to_delete": session.messages_to_delete + [message_id]}
            )

        await self._atomic_session_update(chat_id, _append)

    # ─── Chat-scoped navigation state ─────────────────────────────────────────

    async def _read_chat_data(self, chat_id: int) -> Dict[str, Any]:
        raw = await self._redis.get(self._chat_key(chat_id))
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except json.JSONDecodeError as e:
            logger.warning(
                "Ошибка парсинга данных чата из Redis — ключ удалён",
                extra={"chat_id": chat_id, "error": str(e)},
            )
            await self._redis.delete(self._chat_key(chat_id))
            return {}

    async def _write_chat_data(self, chat_id: int, data: Dict[str, Any]) -> None:
        await self._redis.set(self._chat_key(chat_id), json.dumps(data), ex=self._ttl)

    async def update_chat_data(self, chat_id: int, **kwargs: Any) -> None:
        """Атомарно обновляет chat_data через WATCH/MULTI."""
        redis_key = self._chat_key(chat_id)
        for _ in range(3):
            try:
                async with self._redis.pipeline(transaction=True) as pipe:
                    await pipe.watch(redis_key)
                    raw = await pipe.get(redis_key)
                    data = json.loads(raw) if raw else {}
                    data.update(kwargs)
                    pipe.multi()
                    pipe.set(redis_key, json.dumps(data), ex=self._ttl)
                    await pipe.execute()
                    return
            except WatchError:
                continue
        logger.warning(
            "update_chat_data: 3 retries exhausted", extra={"chat_id": chat_id}
        )

    async def get_chat_data(self, chat_id: int) -> Dict[str, Any]:
        return await self._read_chat_data(chat_id)

    async def clear_chat_data(self, chat_id: int) -> None:
        await self._redis.delete(self._chat_key(chat_id))

    async def _remove_chat_data_key(self, chat_id: int, key_name: str) -> None:
        """Атомарно удаляет ключ из chat_data через WATCH/MULTI."""
        redis_key = self._chat_key(chat_id)
        for _ in range(3):
            try:
                async with self._redis.pipeline(transaction=True) as pipe:
                    await pipe.watch(redis_key)
                    raw = await pipe.get(redis_key)
                    if not raw:
                        await pipe.unwatch()
                        return
                    try:
                        data = json.loads(raw)
                    except json.JSONDecodeError:
                        await pipe.unwatch()
                        return
                    if key_name not in data:
                        await pipe.unwatch()
                        return
                    del data[key_name]
                    pipe.multi()
                    pipe.set(redis_key, json.dumps(data), ex=self._ttl)
                    await pipe.execute()
                    return
            except WatchError:
                continue
        logger.warning(
            "_remove_chat_data_key: 3 retries exhausted",
            extra={"chat_id": chat_id, "key": key_name},
        )

    # ─── Navigation stacks (multi-stack by stack_id) ─────────────────────────

    def _stack_key(self, stack_id: str) -> str:
        return _NAV_STACK_FMT.format(stack_id=stack_id)

    def _msg_id_key(self, stack_id: str) -> str:
        return _NAV_MSG_ID_FMT.format(stack_id=stack_id)

    def _cmd_msg_id_key(self, stack_id: str) -> str:
        return _NAV_CMD_MSG_ID_FMT.format(stack_id=stack_id)

    def _from_back_key(self, stack_id: str) -> str:
        return _NAV_FROM_BACK_FMT.format(stack_id=stack_id)

    async def nav_push_state(
        self, chat_id: int, stack_id: str, state_name: str
    ) -> None:
        key_name = self._stack_key(stack_id)
        redis_key = self._chat_key(chat_id)
        for _ in range(3):
            try:
                async with self._redis.pipeline(transaction=True) as pipe:
                    await pipe.watch(redis_key)
                    raw = await pipe.get(redis_key)
                    data = json.loads(raw) if raw else {}
                    stack = data.get(key_name, [])
                    stack.append(state_name)
                    data[key_name] = stack
                    pipe.multi()
                    pipe.set(redis_key, json.dumps(data), ex=self._ttl)
                    await pipe.execute()
                    return
            except WatchError:
                continue

    async def nav_pop_state(self, chat_id: int, stack_id: str) -> None:
        key_name = self._stack_key(stack_id)
        redis_key = self._chat_key(chat_id)
        for _ in range(3):
            try:
                async with self._redis.pipeline(transaction=True) as pipe:
                    await pipe.watch(redis_key)
                    raw = await pipe.get(redis_key)
                    data = json.loads(raw) if raw else {}
                    stack = data.get(key_name, [])
                    if not stack:
                        await pipe.unwatch()
                        return
                    stack.pop()
                    data[key_name] = stack
                    pipe.multi()
                    pipe.set(redis_key, json.dumps(data), ex=self._ttl)
                    await pipe.execute()
                    return
            except WatchError:
                continue

    async def nav_get_top_state(self, chat_id: int, stack_id: str) -> Optional[str]:
        data = await self._read_chat_data(chat_id)
        stack = data.get(self._stack_key(stack_id), [])
        return stack[-1] if stack else None

    async def nav_clear_stack(self, chat_id: int, stack_id: str) -> None:
        """Полностью очистить стек и сбросить from_back."""
        await self.update_chat_data(
            chat_id,
            **{self._stack_key(stack_id): [], self._from_back_key(stack_id): False},
        )

    async def nav_is_root(self, chat_id: int, stack_id: str) -> bool:
        data = await self._read_chat_data(chat_id)
        stack = data.get(self._stack_key(stack_id), [])
        return len(stack) <= 1

    async def nav_save_msg_id(
        self, chat_id: int, stack_id: str, message_id: int
    ) -> None:
        await self.update_chat_data(chat_id, **{self._msg_id_key(stack_id): message_id})

    async def nav_get_msg_id(self, chat_id: int, stack_id: str) -> Optional[int]:
        data = await self._read_chat_data(chat_id)
        return data.get(self._msg_id_key(stack_id))

    async def nav_clear_msg_id(self, chat_id: int, stack_id: str) -> None:
        await self._remove_chat_data_key(chat_id, self._msg_id_key(stack_id))

    async def nav_save_cmd_msg_id(
        self, chat_id: int, stack_id: str, message_id: int
    ) -> None:
        await self.update_chat_data(
            chat_id, **{self._cmd_msg_id_key(stack_id): message_id}
        )

    async def nav_get_cmd_msg_id(self, chat_id: int, stack_id: str) -> Optional[int]:
        data = await self._read_chat_data(chat_id)
        return data.get(self._cmd_msg_id_key(stack_id))

    async def nav_clear_cmd_msg_id(self, chat_id: int, stack_id: str) -> None:
        await self._remove_chat_data_key(chat_id, self._cmd_msg_id_key(stack_id))

    async def nav_set_from_back(self, chat_id: int, stack_id: str, value: bool) -> None:
        await self.update_chat_data(chat_id, **{self._from_back_key(stack_id): value})

    async def nav_is_from_back(self, chat_id: int, stack_id: str) -> bool:
        data = await self._read_chat_data(chat_id)
        return data.get(self._from_back_key(stack_id), False)

    # ─── Ephemeral message helpers ─────────────────────────────────────────────

    async def save_lang_message(self, chat_id: int, message_id: int) -> None:
        await self.update_chat_data(chat_id, **{_LANG_MSG_ID_KEY: message_id})

    async def get_lang_message(self, chat_id: int) -> Optional[int]:
        data = await self._read_chat_data(chat_id)
        return data.get(_LANG_MSG_ID_KEY)

    async def clear_lang_message(self, chat_id: int) -> None:
        await self._remove_chat_data_key(chat_id, _LANG_MSG_ID_KEY)

    async def save_lang_cmd_message(self, chat_id: int, message_id: int) -> None:
        await self.update_chat_data(chat_id, **{_LANG_CMD_MSG_ID_KEY: message_id})

    async def get_lang_cmd_message(self, chat_id: int) -> Optional[int]:
        data = await self._read_chat_data(chat_id)
        return data.get(_LANG_CMD_MSG_ID_KEY)

    async def clear_lang_cmd_message(self, chat_id: int) -> None:
        await self._remove_chat_data_key(chat_id, _LANG_CMD_MSG_ID_KEY)

    async def save_lang_saved_message(self, chat_id: int, message_id: int) -> None:
        await self.update_chat_data(chat_id, **{_LANG_SAVED_MSG_ID_KEY: message_id})

    async def get_lang_saved_message(self, chat_id: int) -> Optional[int]:
        data = await self._read_chat_data(chat_id)
        return data.get(_LANG_SAVED_MSG_ID_KEY)

    async def clear_lang_saved_message(self, chat_id: int) -> None:
        await self._remove_chat_data_key(chat_id, _LANG_SAVED_MSG_ID_KEY)

    async def save_howto_message(self, chat_id: int, message_id: int) -> None:
        await self.update_chat_data(chat_id, **{_HOWTO_MSG_ID_KEY: message_id})

    async def get_howto_message(self, chat_id: int) -> Optional[int]:
        data = await self._read_chat_data(chat_id)
        return data.get(_HOWTO_MSG_ID_KEY)

    async def clear_howto_message(self, chat_id: int) -> None:
        await self._remove_chat_data_key(chat_id, _HOWTO_MSG_ID_KEY)

    async def save_howto_cmd_message(self, chat_id: int, message_id: int) -> None:
        await self.update_chat_data(chat_id, **{_HOWTO_CMD_MSG_ID_KEY: message_id})

    async def get_howto_cmd_message(self, chat_id: int) -> Optional[int]:
        data = await self._read_chat_data(chat_id)
        return data.get(_HOWTO_CMD_MSG_ID_KEY)

    async def clear_howto_cmd_message(self, chat_id: int) -> None:
        await self._remove_chat_data_key(chat_id, _HOWTO_CMD_MSG_ID_KEY)

    async def save_info_message(self, chat_id: int, message_id: int) -> None:
        await self.update_chat_data(chat_id, **{_INFO_MSG_ID_KEY: message_id})

    async def get_info_message(self, chat_id: int) -> Optional[int]:
        data = await self._read_chat_data(chat_id)
        return data.get(_INFO_MSG_ID_KEY)

    async def clear_info_message(self, chat_id: int) -> None:
        await self._remove_chat_data_key(chat_id, _INFO_MSG_ID_KEY)

    async def save_tz_prompt_message(self, chat_id: int, message_id: int) -> None:
        await self.update_chat_data(chat_id, **{_TZ_PROMPT_MSG_ID_KEY: message_id})

    async def get_tz_prompt_message(self, chat_id: int) -> Optional[int]:
        data = await self._read_chat_data(chat_id)
        return data.get(_TZ_PROMPT_MSG_ID_KEY)

    async def clear_tz_prompt_message(self, chat_id: int) -> None:
        await self._remove_chat_data_key(chat_id, _TZ_PROMPT_MSG_ID_KEY)

    async def save_greeting_message(self, chat_id: int, message_id: int) -> None:
        await self.update_chat_data(chat_id, **{_GREETING_MSG_ID_KEY: message_id})

    async def get_greeting_message(self, chat_id: int) -> Optional[int]:
        data = await self._read_chat_data(chat_id)
        return data.get(_GREETING_MSG_ID_KEY)

    async def clear_greeting_message(self, chat_id: int) -> None:
        await self._remove_chat_data_key(chat_id, _GREETING_MSG_ID_KEY)

    async def save_demo_message(self, chat_id: int, message_id: int) -> None:
        await self.update_chat_data(chat_id, **{_DEMO_MSG_ID_KEY: message_id})

    async def get_demo_message(self, chat_id: int) -> Optional[int]:
        data = await self._read_chat_data(chat_id)
        return data.get(_DEMO_MSG_ID_KEY)

    async def clear_demo_message(self, chat_id: int) -> None:
        await self._remove_chat_data_key(chat_id, _DEMO_MSG_ID_KEY)

    async def save_demo_album(self, chat_id: int, ids: list[int]) -> None:
        await self.update_chat_data(chat_id, **{_DEMO_ALBUM_IDS_KEY: list(ids)})

    async def get_demo_album(self, chat_id: int) -> list[int]:
        data = await self._read_chat_data(chat_id)
        return list(data.get(_DEMO_ALBUM_IDS_KEY) or [])

    async def clear_demo_album(self, chat_id: int) -> None:
        await self._remove_chat_data_key(chat_id, _DEMO_ALBUM_IDS_KEY)

    # ─── Analyzing flag ────────────────────────────────────────────────────────

    async def try_set_analyzing(self, chat_id: int) -> bool:
        """Атомарно устанавливает флаг анализа (SETNX). Возвращает True если удалось."""
        result = await self._redis.set(
            self._analyzing_key(chat_id), "1", ex=_ANALYZING_TTL, nx=True
        )
        return result is not None

    async def set_analyzing(self, chat_id: int) -> None:
        await self._redis.set(self._analyzing_key(chat_id), "1", ex=_ANALYZING_TTL)

    async def clear_analyzing(self, chat_id: int) -> None:
        await self._redis.delete(self._analyzing_key(chat_id))

    async def is_analyzing(self, chat_id: int) -> bool:
        return bool(await self._redis.exists(self._analyzing_key(chat_id)))
