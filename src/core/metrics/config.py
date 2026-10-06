"""
Настройки сервера метрик.

Все значения можно переопределить через переменные окружения.
"""

import os

# Порт HTTP-сервера метрик (Prometheus scrape endpoint).
PORT: int = int(os.getenv("METRICS_PORT", "9090"))

# Адрес прослушивания. Внутри Docker достаточно 0.0.0.0.
HOST: str = os.getenv("METRICS_HOST", "0.0.0.0")
