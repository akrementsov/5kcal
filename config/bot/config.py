from dataclasses import dataclass
from environs import Env
import logging


@dataclass
class RedisConfig:
    host: str
    port: int
    db: int
    password: str | None
    ttl: int


@dataclass
class Config:
    token: str
    log_level: int
    timezone: str
    redis: RedisConfig
    llm_provider: str
    openai_api_key: str
    gemini_api_key: str | None
    database_url: str
    admin_ids: list[int]
    alert_bot_token: str | None
    alert_chat_id: int | None
    fatsecret_key: str | None
    fatsecret_secret: str | None
    dietagram_api_key: str | None
    barcode_lookup_api_key: str | None
    robokassa_merchant_login: str | None
    robokassa_password1: str | None
    robokassa_password2: str | None
    robokassa_password1_test: str | None
    robokassa_password2_test: str | None
    # Mini App «Статистика»: базовый URL (https://app.5kcal.app).
    # Если не задан — web_app-кнопка «Графики» в меню не показывается.
    webapp_url: str | None = None
    # Анти-абьюз: суточный бюджет LLM-расходов на пользователя (копейки).
    # 800 коп = 8₽ ≈ дневная стоимость самого дешёвого тарифа.
    llm_daily_budget_kop: int = 800
    # Повышенный бюджет в первый календарный день юзера (== день активации
    # триала): даёт новичку наиграться, не упираясь в лимит сразу. 1600 = 16₽.
    llm_first_day_budget_kop: int = 1600
    # Прайс модели, копейки за 1M токенов (gemini-3.5-flash-lite,
    # $0.30/$2.50/$0.03 за 1M при курсе ~95₽/$). Смена модели = правка этих цен.
    llm_price_kop_per_1m_input: int = 2850
    llm_price_kop_per_1m_output: int = 23750
    llm_price_kop_per_1m_cached: int = 285
    # Ансамбль оценки веса: сколько независимых Call 2 усреднять покомпонентно
    # (1 = выкл). На gemini-3.5-flash-lite одиночный вызов уже точен
    # (бенчмарк MAPE ~22%, ±50% 10/11), ансамбль-костыль под слабую модель снят.
    weight_ensemble_samples: int = 1


def load_config() -> Config:
    env = Env()
    env.read_env()

    log_level_str = env.str("LOG_LEVEL", "INFO").upper()
    log_level = getattr(logging, log_level_str, logging.INFO)

    return Config(
        token=env.str("BOT_TOKEN"),
        log_level=log_level,
        timezone=env.str("TIMEZONE"),
        redis=RedisConfig(
            host=env.str("REDIS_HOST"),
            port=env.int("REDIS_PORT"),
            db=env.int("REDIS_DB"),
            password=env.str("REDIS_PASSWORD"),
            ttl=env.int("REDIS_TTL"),  # 7 дней
        ),
        llm_provider=env.str("LLM_PROVIDER", "openai"),
        openai_api_key=env.str("OPENAI_API_KEY", ""),
        gemini_api_key=env.str("GEMINI_API_KEY", "") or None,
        database_url=env.str("DATABASE_URL", "sqlite:///db.sqlite3"),
        admin_ids=[int(x) for x in env.str("ADMIN_IDS", "").split(",") if x.strip()],
        alert_bot_token=env.str("ALERT_BOT_TOKEN", "") or None,
        alert_chat_id=(
            int(env.str("ALERT_CHAT_ID", "")) if env.str("ALERT_CHAT_ID", "") else None
        ),
        fatsecret_key=env.str("FATSECRET_KEY", "") or None,
        fatsecret_secret=env.str("FATSECRET_SECRET", "") or None,
        dietagram_api_key=env.str("DIETAGRAM_API_KEY", "") or None,
        barcode_lookup_api_key=env.str("BARCODE_LOOKUP_API_KEY", "") or None,
        robokassa_merchant_login=env.str("ROBOKASSA_MERCHANT_LOGIN", "") or None,
        robokassa_password1=env.str("ROBOKASSA_PASSWORD1", "") or None,
        robokassa_password2=env.str("ROBOKASSA_PASSWORD2", "") or None,
        robokassa_password1_test=env.str("ROBOKASSA_PASSWORD1_TEST", "") or None,
        robokassa_password2_test=env.str("ROBOKASSA_PASSWORD2_TEST", "") or None,
        webapp_url=env.str("WEBAPP_URL", "") or None,
        llm_daily_budget_kop=env.int("LLM_DAILY_BUDGET_KOP", 800),
        llm_first_day_budget_kop=env.int("LLM_FIRST_DAY_BUDGET_KOP", 1600),
        llm_price_kop_per_1m_input=env.int("LLM_PRICE_KOP_PER_1M_INPUT", 2850),
        llm_price_kop_per_1m_output=env.int("LLM_PRICE_KOP_PER_1M_OUTPUT", 23750),
        llm_price_kop_per_1m_cached=env.int("LLM_PRICE_KOP_PER_1M_CACHED", 285),
        weight_ensemble_samples=env.int("WEIGHT_ENSEMBLE_SAMPLES", 1),
    )


class _LazyConfig:
    """Lazy proxy: load_config() вызывается при первом обращении к атрибуту.

    В тестах вместо загрузки из env можно подменить конфиг через _override():
        from config.bot.config import config
        config._override(Config(token="test:token", ...))
    """

    _real: "Config | None" = None

    def _load(self) -> Config:
        if self._real is None:
            self._real = load_config()
        return self._real

    def __getattr__(self, name: str):
        return getattr(self._load(), name)

    def _override(self, cfg: Config) -> None:
        """Только для тестов — подменить конфиг вместо загрузки из env."""
        self._real = cfg

    def _reset(self) -> None:
        """Только для тестов — сбросить кэш, чтобы следующий доступ перечитал env."""
        self._real = None


config = _LazyConfig()
