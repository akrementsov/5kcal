"""Сервисные уведомления в админ-чат через alert-бот (💰 продажи и т.п.).

Использует тот же ALERT_BOT_TOKEN/ALERT_CHAT_ID, что и WARNING-логи с алертами.
Без настроенного алерт-чата все вызовы — no-op; ошибки отправки не пробрасываются
(уведомление не должно ломать платёжный поток).
"""

from config.bot import config
from src.core.utils.logger import get_logger

logger = get_logger()

_bot = None


def _get_bot():
    global _bot
    if _bot is None and config.alert_bot_token:
        from aiogram import Bot

        _bot = Bot(token=config.alert_bot_token)
    return _bot


def format_sale(
    user_id: int, days: int, amount: int, currency: str | None, provider: str | None
) -> str:
    """Текст уведомления о продаже. Валюты не смешиваются: XTR → ⭐, остальное → ₽."""
    symbol = "⭐" if currency == "XTR" else "₽"
    provider_str = f" [{provider}]" if provider else ""
    return f"💰 Оплата: user {user_id} — {days} дн, {amount}{symbol}{provider_str}"


async def notify_admin(text: str) -> None:
    """Шлёт сообщение в админ-чат. No-op без конфигурации, ошибки — в лог."""
    if not config.alert_chat_id:
        return
    bot = _get_bot()
    if bot is None:
        return
    try:
        await bot.send_message(config.alert_chat_id, text, parse_mode="HTML")
    except Exception as e:
        logger.warning(
            "Не удалось отправить уведомление в админ-чат", extra={"error": str(e)}
        )
