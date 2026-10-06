"""
Настройки модуля нотификаций.

Все значения можно переопределить через переменные окружения.
"""

import os

# Интервал проверки истекающих подписок (секунды). По умолчанию — каждый час.
NOTIFY_CHECK_INTERVAL: int = int(os.getenv("NOTIFY_CHECK_INTERVAL", "3600"))

# Час в timezone пользователя, начиная с которого отправляем уведомление.
NOTIFY_LOCAL_HOUR: int = int(os.getenv("NOTIFY_LOCAL_HOUR", "12"))

# За сколько дней до конца подписки отправлять уведомление.
# Формат в env: через запятую, например "3,1".
_raw = os.getenv("NOTIFY_DAYS_BEFORE", "3,1")
NOTIFY_DAYS_BEFORE: list[int] = [int(d.strip()) for d in _raw.split(",") if d.strip()]

# Задержка между отправками (секунды).
# 0.1 ≈ 10 сообщений/сек — чуть ниже лимита Telegram Bot API.
MESSAGE_DELAY: float = float(os.getenv("NOTIFY_MESSAGE_DELAY", "0.1"))
