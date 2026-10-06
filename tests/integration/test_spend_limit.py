"""Тесты суточного бюджета LLM-расходов (анти-абьюз)."""

import pytest

from src.features.meals import spend_limit
from src.features.meals.spend_limit import (
    add_spend,
    call_cost_kop,
    get_spent_kop,
    init_spend_limit,
    is_over_budget,
    mark_limit_alerted,
)


@pytest.fixture(autouse=True)
def _clear_tz_cache():
    """Кэш tz — модульный синглтон; чистим между тестами, чтобы не текла
    таймзона одного user_id из предыдущего теста."""
    spend_limit._tz_cache.clear()
    spend_limit._created_at_cache.clear()
    yield
    spend_limit._tz_cache.clear()
    spend_limit._created_at_cache.clear()


def _usage(inp=5000, out=2000, cached=0):
    return {
        "provider": "gemini",
        "model": "gemini-3.1-flash-lite-preview",
        "input_tokens": inp,
        "output_tokens": out,
        "cached_tokens": cached,
    }


def _backdate_created_at(test_db, user_id: int, days: int) -> None:
    """Сдвигает created_at юзера в прошлое — делает его «не первым днём»."""
    from datetime import timedelta

    from src.core.database.models import User
    from src.core.utils.tz import utc_now_naive

    with test_db.session() as session:
        session.query(User).filter(User.user_id == user_id).update(
            {User.created_at: utc_now_naive() - timedelta(days=days)}
        )


class TestCallCost:
    def test_cost_from_prices(self):
        # 5000 in * 2850коп/1M + 2000 out * 23750коп/1M = 14.25 + 47.5 → ceil = 62 коп
        assert call_cost_kop(_usage()) == 62

    def test_cached_tokens_cheaper(self):
        # cached вычитаются из input и считаются по своей цене
        full = call_cost_kop(_usage(inp=100_000, cached=0))
        with_cache = call_cost_kop(_usage(inp=100_000, cached=90_000))
        assert with_cache < full

    def test_zero_usage_zero_cost(self):
        assert call_cost_kop(_usage(inp=0, out=0)) == 0


class TestSpendCounter:
    async def test_add_and_get(self, test_db, test_redis, user_service):
        user_service.get_or_create(user_id=100)
        init_spend_limit(test_db)

        assert await get_spent_kop(100) == 0
        await add_spend(100, 300)
        await add_spend(100, 200)
        assert await get_spent_kop(100) == 500

    async def test_over_budget(self, test_db, test_redis, user_service):
        user_service.get_or_create(user_id=100)
        _backdate_created_at(test_db, 100, days=2)  # обычный день → планка 800
        init_spend_limit(test_db)

        assert await is_over_budget(100) is False
        await add_spend(100, 800)  # бюджет по умолчанию 800 коп
        assert await is_over_budget(100) is True

    async def test_honest_user_stays_under(self, test_db, test_redis, user_service):
        """5 анализов по типичной цене (~13 коп) — далеко до лимита."""
        user_service.get_or_create(user_id=100)
        init_spend_limit(test_db)

        for _ in range(5):
            await add_spend(100, call_cost_kop(_usage()))
        assert await is_over_budget(100) is False

    async def test_users_isolated(self, test_db, test_redis, user_service):
        user_service.get_or_create(user_id=100)
        user_service.get_or_create(user_id=200)
        init_spend_limit(test_db)

        await add_spend(100, 800)
        assert await is_over_budget(200) is False

    async def test_key_date_uses_user_timezone(self, test_db, test_redis, user_service):
        """Дата в ключе — по таймзоне пользователя, а не UTC."""
        from src.core.utils.tz import today_for_tz

        user_service.get_or_create(user_id=100)
        user_service.update_timezone(100, "Pacific/Auckland")
        init_spend_limit(test_db)

        key = spend_limit._spend_key(100)
        assert key.endswith(today_for_tz("Pacific/Auckland").isoformat())


class TestAlertFlag:
    async def test_first_time_true_then_false(self, test_db, test_redis, user_service):
        user_service.get_or_create(user_id=100)
        init_spend_limit(test_db)

        assert await mark_limit_alerted(100) is True
        assert await mark_limit_alerted(100) is False


class TestBudgetGuard:
    """Guard в meals/handler: при превышении бюджета анализ не стартует."""

    async def test_photo_blocked_over_budget(self, test_db, test_redis, user_service):
        from src.features.meals.handler import _handle_photo_input, init_meal_handler
        from tests.mocks import MockBot, MockI18n

        user_service.get_or_create(user_id=100)
        _backdate_created_at(test_db, 100, days=2)  # обычный день → планка 800
        init_spend_limit(test_db)
        init_meal_handler(meal_service=None, subscription_service=None)
        await add_spend(100, 800)

        bot = MockBot()
        await _handle_photo_input(
            bot,
            photos_bytes=[b"img"],
            caption="",
            original_ids=[1],
            user_id=100,
            chat_id=100,
            i18n=MockI18n(),
        )

        # анализ не начался: сообщение о лимите, analyzing-флаг не выставлен
        assert any(
            "msg-daily-limit-reached" in (m.text or "") for m in bot.sent_messages
        )
        from src.core.user_state import redis_storage as rs

        assert await rs.is_analyzing(100) is False

    async def test_photo_passes_under_budget(
        self, test_db, test_redis, user_service, monkeypatch
    ):
        """Под бюджетом guard пропускает до try_set_analyzing (дальше мокаем)."""
        from unittest.mock import AsyncMock

        from src.features.barcode.handler import BarcodePrecheck
        from src.features.meals import handler as meal_handler
        from tests.mocks import MockBot, MockI18n

        user_service.get_or_create(user_id=100)
        init_spend_limit(test_db)
        meal_handler.init_meal_handler(meal_service=None, subscription_service=None)

        run_analysis = AsyncMock()
        monkeypatch.setattr(meal_handler, "_process_and_display", run_analysis)

        async def fake_barcode(*args, **kwargs):
            return BarcodePrecheck()

        monkeypatch.setattr(meal_handler, "try_get_barcode_result", fake_barcode)

        bot = MockBot()
        await meal_handler._handle_photo_input(
            bot,
            photos_bytes=[b"img"],
            caption="",
            original_ids=[1],
            user_id=100,
            chat_id=100,
            i18n=MockI18n(),
        )

        assert run_analysis.await_count == 1
        assert not any(
            "msg-daily-limit-reached" in (m.text or "") for m in bot.sent_messages
        )

    async def test_edit_reply_blocked_over_budget(
        self, test_db, test_redis, user_service
    ):
        """process_edit_reply при исчерпанном бюджете возвращает лимит-сообщение,
        не запуская LLM-анализ."""
        from src.core.user_state.session import AnalysisSession, SessionMode
        from src.features.meals import editing
        from tests.mocks import MockBot, MockI18n

        user_service.get_or_create(user_id=100)
        _backdate_created_at(test_db, 100, days=2)  # обычный день → планка 800
        init_spend_limit(test_db)
        editing._meal_service = None
        editing._db = test_db

        # ставим сессию UPDATE — иначе process_edit_reply уйдёт раньше guard'а
        await test_redis.save_session(
            100,
            AnalysisSession(
                mode=SessionMode.UPDATE,
                meal_id=999,
                meal_card_msg_id=50,
                messages_to_delete=[],
            ),
        )
        await add_spend(100, 800)  # бюджет исчерпан

        bot = MockBot()
        await editing.process_edit_reply(
            bot, 100, 100, "обнови блюдо", None, MockI18n()
        )

        assert any(
            "msg-daily-limit-reached" in (m.text or "") for m in bot.sent_messages
        ), "Должно быть отправлено сообщение об исчерпанном лимите"
        # Не должно быть сообщения «Обрабатываю…» — LLM не запускался
        assert not any(
            "msg-loading-step-1" in (m.text or "") for m in bot.sent_messages
        ), "LLM-анализ не должен начинаться при исчерпанном бюджете"


class TestResetSpend:
    """Сброс дневного лимита (админ-команда)."""

    async def test_reset_unblocks_user(self, test_db, test_redis, user_service):
        from src.features.meals.spend_limit import reset_spend

        user_service.get_or_create(user_id=100)
        _backdate_created_at(test_db, 100, days=2)  # обычный день → планка 800
        init_spend_limit(test_db)

        await add_spend(100, 800)
        assert await is_over_budget(100) is True

        await reset_spend(100)

        assert await get_spent_kop(100) == 0
        assert await is_over_budget(100) is False

    async def test_reset_clears_alert_flag(self, test_db, test_redis, user_service):
        """После сброса алерт при повторном срабатывании придёт снова."""
        from src.features.meals.spend_limit import reset_spend

        user_service.get_or_create(user_id=100)
        init_spend_limit(test_db)

        assert await mark_limit_alerted(100) is True
        await reset_spend(100)
        assert await mark_limit_alerted(100) is True  # флаг очищен


class TestLimitAlert:
    async def test_alert_sent_once_per_day(
        self, test_db, test_redis, user_service, monkeypatch
    ):
        from unittest.mock import AsyncMock

        user_service.get_or_create(user_id=100)
        init_spend_limit(test_db)
        await add_spend(100, 800)

        notify = AsyncMock()
        monkeypatch.setattr("src.features.meals.spend_limit.notify_admin", notify)

        await spend_limit.alert_if_first(100)
        await spend_limit.alert_if_first(100)  # второй раз — без алерта

        assert notify.await_count == 1
        assert "100" in notify.await_args.args[0]
        assert "лимит" in notify.await_args.args[0]


class TestRecordCall:
    async def test_record_call_increments(self, test_db, test_redis, user_service):
        """record_call — sync fire-and-forget: инкремент виден после тика loop."""
        import asyncio

        user_service.get_or_create(user_id=100)
        init_spend_limit(test_db)

        spend_limit.record_call(100, _usage())
        await asyncio.sleep(0)  # даём созданной таске выполниться
        assert await get_spent_kop(100) == 62

    async def test_redis_error_does_not_raise(
        self, test_db, test_redis, user_service, monkeypatch
    ):
        """Ошибка Redis при инкременте не пробрасывается (не ломает анализ)."""
        user_service.get_or_create(user_id=100)
        init_spend_limit(test_db)

        async def boom(*a, **k):
            raise ConnectionError("redis down")

        monkeypatch.setattr(spend_limit.rs.get_redis(), "incrby", boom, raising=False)
        await add_spend(100, 10)  # no exception


class TestFirstDayBudget:
    """Первый календарный день юзера (== день активации триала) даёт 2× бюджет."""

    async def test_first_day_not_over_below_elevated_budget(
        self, test_db, test_redis, user_service
    ):
        """created_at по умолчанию = сейчас → первый день: 1500 коп ещё не лимит."""
        user_service.get_or_create(user_id=100)
        init_spend_limit(test_db)

        await add_spend(100, 1500)  # выше обычных 800, но ниже first-day 1600
        assert await is_over_budget(100) is False

    async def test_first_day_over_at_elevated_budget(
        self, test_db, test_redis, user_service
    ):
        user_service.get_or_create(user_id=100)
        init_spend_limit(test_db)

        await add_spend(100, 1600)
        assert await is_over_budget(100) is True

    async def test_second_day_uses_normal_budget(
        self, test_db, test_redis, user_service
    ):
        """Юзер, зарегистрированный не сегодня, упирается в обычные 800."""
        user_service.get_or_create(user_id=100)
        _backdate_created_at(test_db, 100, days=2)
        init_spend_limit(test_db)

        await add_spend(100, 800)
        assert await is_over_budget(100) is True

    async def test_missing_created_at_falls_back_to_normal_budget(
        self, test_db, test_redis, user_service, monkeypatch
    ):
        """Fail-safe: нет created_at → обычная планка 800, не повышенная."""
        user_service.get_or_create(user_id=100)
        init_spend_limit(test_db)
        monkeypatch.setattr(spend_limit, "_user_created_at", lambda uid: None)

        await add_spend(100, 800)
        assert await is_over_budget(100) is True

    async def test_db_error_reading_created_at_does_not_raise(
        self, test_db, test_redis, user_service, monkeypatch
    ):
        """Сбой чтения created_at не роняет is_over_budget (учёт не ломает анализ)."""
        user_service.get_or_create(user_id=100)
        init_spend_limit(test_db)

        def boom(uid):
            raise RuntimeError("db gone")

        monkeypatch.setattr(spend_limit, "_user_created_at", boom)

        assert await is_over_budget(100) is False  # не бросает, планка обычная


class TestGetUserCreatedAt:
    def test_returns_created_at_for_existing_user(self, test_db, user_service):
        from src.core.database import db as db_funcs

        user_service.get_or_create(user_id=100)
        with test_db.session() as session:
            assert db_funcs.get_user_created_at(session, 100) is not None

    def test_returns_none_for_missing_user(self, test_db):
        from src.core.database import db as db_funcs

        with test_db.session() as session:
            assert db_funcs.get_user_created_at(session, 999) is None


class TestTimezoneCaching:
    """tz для ключа расхода не должен дёргать БД на каждый спенд-вызов
    (блокирующий запрос в event loop). Кэшируется на короткий TTL."""

    async def test_spend_key_caches_timezone(
        self, test_db, test_redis, user_service, monkeypatch
    ):
        user_service.get_or_create(user_id=100)
        init_spend_limit(test_db)
        spend_limit._tz_cache.clear()

        calls = {"n": 0}
        real = spend_limit._user_tz

        def counting(user_id):
            calls["n"] += 1
            return real(user_id)

        monkeypatch.setattr(spend_limit, "_user_tz", counting)

        # Много спенд-операций подряд — tz из БД читается один раз
        await add_spend(100, 10)
        await add_spend(100, 10)
        await get_spent_kop(100)
        await is_over_budget(100)

        assert calls["n"] == 1
