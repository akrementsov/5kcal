"""Тесты записи LLM usage в meal_analysis_logs (рейтинг токенов по пользователям)."""

import pytest

from src.core.database import db as db_funcs
from src.core.database.models import MealAnalysisLog, User
from src.core.llm import usage as usage_mod
from src.core.llm.usage import (
    init_usage_sink,
    pop_last_usage,
    record_usage,
    set_last_usage,
)


@pytest.fixture(autouse=True)
def _reset_usage_state():
    usage_mod._sink = None
    usage_mod._last_usage.set(None)
    yield
    usage_mod._sink = None
    usage_mod._last_usage.set(None)


def _db_sink(db):
    def sink(user_id: int, call_type: str, usage: dict, duration_ms: int):
        with db.session() as session:
            db_funcs.add_meal_analysis_log(
                session,
                user_id,
                call_type,
                model=usage["model"],
                input_tokens=usage["input_tokens"],
                output_tokens=usage["output_tokens"],
                cached_tokens=usage["cached_tokens"],
                duration_ms=duration_ms,
            )

    return sink


class TestUsageContextvar:
    def test_set_then_pop_returns_usage_once(self):
        set_last_usage("gemini", "gemini-test", 100, 20, 30)

        usage = pop_last_usage()
        assert usage == {
            "provider": "gemini",
            "model": "gemini-test",
            "input_tokens": 100,
            "output_tokens": 20,
            "cached_tokens": 30,
        }
        assert pop_last_usage() is None


class TestRecordUsage:
    def test_persists_log_row(self, test_db):
        with test_db.session() as session:
            session.add(User(user_id=42))
            session.flush()
        init_usage_sink(_db_sink(test_db))

        set_last_usage("gemini", "gemini-test", 1000, 200, 300)
        record_usage(user_id=42, call_type="identification", duration_ms=2500)

        with test_db.session() as session:
            row = session.query(MealAnalysisLog).one()
            assert row.user_id == 42
            assert row.call_type == "identification"
            assert row.model == "gemini-test"
            assert row.input_tokens == 1000
            assert row.output_tokens == 200
            assert row.cached_tokens == 300
            assert row.duration_ms == 2500

    def test_noop_without_sink(self):
        set_last_usage("gemini", "gemini-test", 1, 1, 1)
        record_usage(user_id=1, call_type="weight", duration_ms=10)  # не падает

    def test_noop_without_usage(self, test_db):
        init_usage_sink(_db_sink(test_db))
        record_usage(user_id=1, call_type="weight", duration_ms=10)

        with test_db.session() as session:
            assert session.query(MealAnalysisLog).count() == 0

    def test_sink_error_does_not_raise(self):
        def broken_sink(*args):
            raise RuntimeError("db down")

        init_usage_sink(broken_sink)
        set_last_usage("openai", "gpt-test", 1, 1, 1)
        record_usage(user_id=1, call_type="identification", duration_ms=10)


class TestMealLinkage:
    def test_save_meal_links_recent_usage_logs(self, test_db):
        from tests.helpers import save_test_meal

        with test_db.session() as session:
            session.add(User(user_id=42))
            session.flush()
            db_funcs.add_meal_analysis_log(session, 42, "identification")
            db_funcs.add_meal_analysis_log(session, 42, "weight")

        meal_id = save_test_meal(test_db, user_id=42)

        with test_db.session() as session:
            rows = session.query(MealAnalysisLog).all()
            assert [r.meal_id for r in rows] == [meal_id, meal_id]


class TestUsageOnParseError:
    """Регрессия: при parse-error токены уже потрачены, но usage не записывался —
    спенд-лимит и meal_analysis_logs недосчитывали до 3 вызовов."""

    async def test_parse_error_records_usage(self, test_db):
        from src.features.meals._llm_calls import _retry_llm_call

        with test_db.session() as session:
            session.add(User(user_id=42))
            session.flush()
        init_usage_sink(_db_sink(test_db))

        async def failing_call(client, user_id, messages, locale):
            # Клиент успел получить ответ и записать usage, парсинг падает
            set_last_usage("gemini", "gemini-test", 500, 100, 50)
            raise ValueError("невалидный JSON от модели")

        class _Client:
            provider = "gemini"

        result = await _retry_llm_call(
            call_fn=failing_call,
            call_name="identification",
            llm_client=_Client(),
            user_id=42,
            messages=[],
            chat_id=42,
        )

        # Терминальная ошибка после ретраев
        assert result.error is not None

        # Каждая из 3 неудачных попыток записала usage (токены потрачены)
        with test_db.session() as session:
            rows = session.query(MealAnalysisLog).filter_by(user_id=42).all()
            assert len(rows) == 3
            assert all(r.input_tokens == 500 for r in rows)
            assert all("identification" in r.call_type for r in rows)
