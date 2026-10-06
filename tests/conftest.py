"""
conftest.py — базовые fixtures для интеграционных тестов.

Критически важный порядок:
  1. config._override() вызывается на УРОВНЕ МОДУЛЯ, до любых импортов из src/.
     Иначе первый же import src/... вызовет get_logger() → config.alert_bot_token →
     load_config() → читает .env → падает.
  2. test_db (function) — чистая SQLite in-memory БД для каждого теста.
  3. test_redis (function) — fakeredis + init_storage() для каждого теста.
  4. mock_openai_client, mock_image_processor — заглушки внешних зависимостей.
  5. Fixtures сервисов — собирают зависимости вместе.
"""

import logging

# ─── 1. Config override — ДОЛЖЕН БЫТЬ ПЕРВЫМ ─────────────────────────────────
# Выполняется до любых импортов из src/, чтобы get_logger() и другие
# module-level-вызовы уже видели тестовый конфиг.

from config.bot.config import config, Config, RedisConfig

config._override(
    Config(
        token="test:token",
        log_level=logging.DEBUG,
        timezone="UTC",
        redis=RedisConfig(host="localhost", port=6379, db=0, password=None, ttl=300),
        llm_provider="openai",
        openai_api_key="test-api-key",
        gemini_api_key=None,
        database_url="sqlite:///:memory:",
        admin_ids=[],
        alert_bot_token=None,
        alert_chat_id=None,
        fatsecret_key=None,
        fatsecret_secret=None,
        dietagram_api_key=None,
        barcode_lookup_api_key=None,
        robokassa_merchant_login=None,
        robokassa_password1=None,
        robokassa_password2=None,
        robokassa_password1_test=None,
        robokassa_password2_test=None,
    )
)

# ─── Остальные импорты после override ─────────────────────────────────────────

import fakeredis
import pytest

from src.core.database.database import Database
from src.core.user_state.storage import RedisStorage, init_storage
from tests.mocks import MockImageProcessor, MockOpenAIClient, SequentialMockOpenAIClient


# ─── 2. Database ──────────────────────────────────────────────────────────────


@pytest.fixture
def test_db() -> Database:
    """Чистая SQLite in-memory БД на каждый тест.

    Использует init_tables() — Alembic не нужен.
    """
    db = Database("sqlite:///:memory:")
    db.init_tables()
    yield db
    db.dispose()


# ─── 3. Redis ─────────────────────────────────────────────────────────────────


@pytest.fixture
async def fake_redis():
    """Голый FakeAsyncRedis для тестов, использующих Redis напрямую (payment_state и т.п.)."""
    redis_client = fakeredis.FakeAsyncRedis(decode_responses=True)
    yield redis_client
    await redis_client.aclose()


@pytest.fixture
async def test_redis(fake_redis) -> RedisStorage:
    """fakeredis + init_storage() для шим-слоя redis_storage.

    Каждый тест получает чистый in-memory Redis.
    init_storage() обновляет модульный синглтон, которым пользуется redis_storage.py.
    """
    storage = RedisStorage(fake_redis, ttl=300)
    init_storage(storage)
    yield storage


# ─── 4. Mocks ─────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_openai_client() -> MockOpenAIClient:
    return MockOpenAIClient()


@pytest.fixture
def mock_image_processor() -> MockImageProcessor:
    return MockImageProcessor()


# ─── 5. Services ─────────────────────────────────────────────────────────────


@pytest.fixture
def user_service(test_db: Database):
    from src.features.user.service import UserService

    return UserService(test_db, default_timezone="UTC")


@pytest.fixture
def subscription_service(test_db: Database):
    from src.features.subscription.service import SubscriptionService

    return SubscriptionService(test_db)


@pytest.fixture
async def meal_service(
    test_db: Database,
    test_redis: RedisStorage,
    mock_openai_client: MockOpenAIClient,
    mock_image_processor: MockImageProcessor,
):
    from src.features.meals.service import MealService

    return MealService(test_db, test_redis, mock_openai_client, mock_image_processor)


@pytest.fixture
def history_service(test_db: Database):
    from src.features.history.service import HistoryService

    return HistoryService(test_db)


@pytest.fixture
def chart_service(test_db: Database):
    from src.features.charts.service import ChartService

    return ChartService(test_db)


# ─── 6. Factories ───────────────────────────────────────────────────────────


@pytest.fixture
def meal_service_factory(
    test_db: Database,
    test_redis: RedisStorage,
    mock_image_processor: MockImageProcessor,
):
    """Создаёт MealService с произвольным OpenAI-моком."""

    def _create(openai_client):
        from src.features.meals.service import MealService

        return MealService(test_db, test_redis, openai_client, mock_image_processor)

    return _create
