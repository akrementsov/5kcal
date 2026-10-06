"""
redis_storage.py — backward-compatible shim.

Все вызовы делегируются к инстансу RedisStorage, который инициализируется
из main.py через init_storage(). В тестах вызывается conftest.py.
"""

from src.core.user_state.storage import get_storage
from . import config as _state_cfg

# ─── Публичные константы (импортируются в других модулях) ─────────────────────

EDITING_REDIS_TTL = _state_cfg.EDITING_TTL
CLARIFICATION_CTX_TTL = _state_cfg.CLARIFICATION_CTX_TTL
CLARIFICATION_TIMEOUT = _state_cfg.CLARIFICATION_TIMEOUT
EDITING_WAIT_SECONDS = _state_cfg.EDITING_WAIT_SECONDS
SESSION_TTL = max(EDITING_REDIS_TTL, CLARIFICATION_CTX_TTL)


def get_redis():
    """Прямой доступ к redis-клиенту (для dedup-операций и тп)."""
    return get_storage()._redis


# ─── Session ──────────────────────────────────────────────────────────────────


async def get_session(chat_id):
    return await get_storage().get_session(chat_id)


async def get_session_mode(chat_id):
    return await get_storage().get_session_mode(chat_id)


async def save_session(chat_id, session):
    return await get_storage().save_session(chat_id, session)


async def update_session(chat_id, **kwargs):
    return await get_storage().update_session(chat_id, **kwargs)


async def clear_session(chat_id):
    return await get_storage().clear_session(chat_id)


async def append_message_to_delete(chat_id, message_id):
    return await get_storage().append_message_to_delete(chat_id, message_id)


# ─── Navigation stacks (multi-stack by stack_id) ────────────────────────────


async def nav_push_state(chat_id, stack_id, state_name):
    return await get_storage().nav_push_state(chat_id, stack_id, state_name)


async def nav_pop_state(chat_id, stack_id):
    return await get_storage().nav_pop_state(chat_id, stack_id)


async def nav_get_top_state(chat_id, stack_id):
    return await get_storage().nav_get_top_state(chat_id, stack_id)


async def nav_clear_stack(chat_id, stack_id):
    return await get_storage().nav_clear_stack(chat_id, stack_id)


async def nav_is_root(chat_id, stack_id):
    return await get_storage().nav_is_root(chat_id, stack_id)


async def nav_save_msg_id(chat_id, stack_id, message_id):
    return await get_storage().nav_save_msg_id(chat_id, stack_id, message_id)


async def nav_get_msg_id(chat_id, stack_id):
    return await get_storage().nav_get_msg_id(chat_id, stack_id)


async def nav_clear_msg_id(chat_id, stack_id):
    return await get_storage().nav_clear_msg_id(chat_id, stack_id)


async def nav_save_cmd_msg_id(chat_id, stack_id, message_id):
    return await get_storage().nav_save_cmd_msg_id(chat_id, stack_id, message_id)


async def nav_get_cmd_msg_id(chat_id, stack_id):
    return await get_storage().nav_get_cmd_msg_id(chat_id, stack_id)


async def nav_clear_cmd_msg_id(chat_id, stack_id):
    return await get_storage().nav_clear_cmd_msg_id(chat_id, stack_id)


async def nav_set_from_back(chat_id, stack_id, value):
    return await get_storage().nav_set_from_back(chat_id, stack_id, value)


async def nav_is_from_back(chat_id, stack_id):
    return await get_storage().nav_is_from_back(chat_id, stack_id)


# ─── Ephemeral message helpers ────────────────────────────────────────────────


async def save_lang_message(chat_id, message_id):
    return await get_storage().save_lang_message(chat_id, message_id)


async def get_lang_message(chat_id):
    return await get_storage().get_lang_message(chat_id)


async def clear_lang_message(chat_id):
    return await get_storage().clear_lang_message(chat_id)


async def save_lang_cmd_message(chat_id, message_id):
    return await get_storage().save_lang_cmd_message(chat_id, message_id)


async def get_lang_cmd_message(chat_id):
    return await get_storage().get_lang_cmd_message(chat_id)


async def clear_lang_cmd_message(chat_id):
    return await get_storage().clear_lang_cmd_message(chat_id)


async def save_lang_saved_message(chat_id, message_id):
    return await get_storage().save_lang_saved_message(chat_id, message_id)


async def get_lang_saved_message(chat_id):
    return await get_storage().get_lang_saved_message(chat_id)


async def clear_lang_saved_message(chat_id):
    return await get_storage().clear_lang_saved_message(chat_id)


async def save_howto_message(chat_id, message_id):
    return await get_storage().save_howto_message(chat_id, message_id)


async def get_howto_message(chat_id):
    return await get_storage().get_howto_message(chat_id)


async def clear_howto_message(chat_id):
    return await get_storage().clear_howto_message(chat_id)


async def save_howto_cmd_message(chat_id, message_id):
    return await get_storage().save_howto_cmd_message(chat_id, message_id)


async def get_howto_cmd_message(chat_id):
    return await get_storage().get_howto_cmd_message(chat_id)


async def clear_howto_cmd_message(chat_id):
    return await get_storage().clear_howto_cmd_message(chat_id)


async def save_info_message(chat_id, message_id):
    return await get_storage().save_info_message(chat_id, message_id)


async def get_info_message(chat_id):
    return await get_storage().get_info_message(chat_id)


async def clear_info_message(chat_id):
    return await get_storage().clear_info_message(chat_id)


async def save_tz_prompt_message(chat_id, message_id):
    return await get_storage().save_tz_prompt_message(chat_id, message_id)


async def get_tz_prompt_message(chat_id):
    return await get_storage().get_tz_prompt_message(chat_id)


async def clear_tz_prompt_message(chat_id):
    return await get_storage().clear_tz_prompt_message(chat_id)


async def save_greeting_message(chat_id, message_id):
    return await get_storage().save_greeting_message(chat_id, message_id)


async def get_greeting_message(chat_id):
    return await get_storage().get_greeting_message(chat_id)


async def clear_greeting_message(chat_id):
    return await get_storage().clear_greeting_message(chat_id)


async def save_demo_message(chat_id, message_id):
    return await get_storage().save_demo_message(chat_id, message_id)


async def get_demo_message(chat_id):
    return await get_storage().get_demo_message(chat_id)


async def clear_demo_message(chat_id):
    return await get_storage().clear_demo_message(chat_id)


async def save_demo_album(chat_id, ids):
    return await get_storage().save_demo_album(chat_id, ids)


async def get_demo_album(chat_id):
    return await get_storage().get_demo_album(chat_id)


async def clear_demo_album(chat_id):
    return await get_storage().clear_demo_album(chat_id)


# ─── Analyzing flag ───────────────────────────────────────────────────────────


async def try_set_analyzing(chat_id):
    return await get_storage().try_set_analyzing(chat_id)


async def set_analyzing(chat_id):
    return await get_storage().set_analyzing(chat_id)


async def clear_analyzing(chat_id):
    return await get_storage().clear_analyzing(chat_id)


async def is_analyzing(chat_id):
    return await get_storage().is_analyzing(chat_id)
