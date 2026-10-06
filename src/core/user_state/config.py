"""
Настройки модуля user_state.

Все значения можно переопределить через переменные окружения.
По умолчанию разумные производственные значения.
"""

import os

# ── Redis TTL (секунды) ────────────────────────────────────────────────────────

# Страховочный TTL флага редактирования.
# Если UI-таймер не сработал, ключ всё равно протухнет.
EDITING_TTL: int = int(os.getenv("REDIS_EDITING_TTL", "300"))  # 5 мин

# TTL контекста уточнения и оригинальных сообщений альбома.
CLARIFICATION_CTX_TTL: int = int(os.getenv("REDIS_CLARIFICATION_TTL", "300"))  # 5 мин

# Страховочный TTL флага «идёт анализ».
# Реальный анализ не должен длиться дольше — страхует от вечной блокировки.
ANALYZING_TTL: int = int(os.getenv("REDIS_ANALYZING_TTL", "180"))  # 3 мин

# ── UI-таймауты (секунды) ──────────────────────────────────────────────────────

# Сколько ждать ответа пользователя на уточняющий вопрос AI.
CLARIFICATION_TIMEOUT: int = int(os.getenv("CLARIFICATION_TIMEOUT_SECONDS", "60"))

# Сколько ждать текста или фото при редактировании блюда.
EDITING_WAIT_SECONDS: int = int(os.getenv("EDITING_TIMEOUT_SECONDS", "60"))

# Киллсвитч уточняющих вопросов: 0 — гипотеза принимается молча, без вопроса
CLARIFICATION_ENABLED: bool = os.getenv("CLARIFICATION_ENABLED", "1") == "1"
