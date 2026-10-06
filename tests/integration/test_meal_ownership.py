"""Проверка владельца блюда (anti-IDOR): meal_id приходит из callback data и
подделывается, поэтому CRUD-операции обязаны сверять user_id владельца."""

import pytest

from src.core.database import db as db_funcs
from src.core.ui.texts import Err
from tests.helpers import save_test_meal
from tests.mocks import MockBot, MockI18n, MockMessage, MockUser

OWNER = 1
ATTACKER = 2


class TestMealOwnershipDb:
    def test_get_meal_checks_owner(self, test_db):
        meal_id = save_test_meal(test_db, user_id=OWNER)
        with test_db.session() as session:
            assert db_funcs.get_meal(session, meal_id, user_id=ATTACKER) is None
            assert db_funcs.get_meal(session, meal_id, user_id=OWNER) is not None

    def test_delete_meal_checks_owner(self, test_db):
        meal_id = save_test_meal(test_db, user_id=OWNER)
        with test_db.session() as session:
            db_funcs.delete_meal(session, meal_id, user_id=ATTACKER)
        with test_db.session() as session:
            assert db_funcs.get_meal(session, meal_id) is not None

    def test_update_meal_count_checks_owner(self, test_db):
        meal_id = save_test_meal(test_db, user_id=OWNER, count=1)
        with test_db.session() as session:
            meal, changed = db_funcs.update_meal_count(
                session, meal_id, +1, user_id=ATTACKER
            )
            assert meal is None
            assert changed is False
        with test_db.session() as session:
            assert (db_funcs.get_meal(session, meal_id).count or 1) == 1

    def test_toggle_meal_excluded_checks_owner(self, test_db):
        meal_id = save_test_meal(test_db, user_id=OWNER)
        with test_db.session() as session:
            assert (
                db_funcs.toggle_meal_excluded(session, meal_id, user_id=ATTACKER)
                is None
            )
        with test_db.session() as session:
            assert db_funcs.get_meal(session, meal_id).excluded is False

    def test_copy_meal_checks_owner(self, test_db):
        """Повтор чужого блюда (копирование себе) должен быть невозможен."""
        meal_id = save_test_meal(test_db, user_id=OWNER)
        with test_db.session() as session:
            assert db_funcs.copy_meal(session, meal_id, user_id=ATTACKER) is None
            assert db_funcs.copy_meal(session, meal_id, user_id=OWNER) is not None

    def test_update_meal_date_checks_owner(self, test_db):
        from datetime import date

        meal_id = save_test_meal(test_db, user_id=OWNER)
        with test_db.session() as session:
            with pytest.raises(ValueError):
                db_funcs.update_meal_date(
                    session, meal_id, date(2026, 1, 1), user_id=ATTACKER
                )


class _FakeCallbackQuery:
    """Мок CallbackQuery: from_user.id — источник владельца для guard-ов."""

    def __init__(self, user_id: int, message_id: int, bot):
        self.bot = bot
        self.message = MockMessage(message_id=message_id, chat_id=user_id, bot=bot)
        self.from_user = MockUser(user_id)
        self._answer_text = None
        self._alert_text = None

    async def answer(self, text=None, show_alert=False):
        self._answer_text = text
        if show_alert:
            self._alert_text = text


class TestMealOwnershipHandlers:
    async def test_foreign_meal_count_plus_rejected(self, test_db):
        """Степпер порций на чужом meal_id → «не найдено», count не меняется."""
        from src.features.meals.card_actions import init_card_actions, meal_count_plus
        from src.features.meals.keyboards import MealCountPlusCb

        init_card_actions(test_db, None)
        meal_id = save_test_meal(test_db, user_id=OWNER)

        callback = _FakeCallbackQuery(
            user_id=ATTACKER, message_id=100, bot=MockBot()
        )
        await meal_count_plus(callback, MealCountPlusCb(meal_id=meal_id), MockI18n())

        assert callback._alert_text == Err.MEAL_NOT_FOUND
        with test_db.session() as session:
            assert (db_funcs.get_meal(session, meal_id).count or 1) == 1

    async def test_foreign_meal_delete_rejected(self, test_db, test_redis):
        """Удаление чужого блюда через подделанный callback — блюдо остаётся."""
        from src.features.meals.card_actions import (
            init_card_actions,
            delete_meal_callback,
        )
        from src.features.meals.keyboards import DeleteMealCb

        init_card_actions(test_db, None)
        meal_id = save_test_meal(test_db, user_id=OWNER)

        callback = _FakeCallbackQuery(
            user_id=ATTACKER, message_id=100, bot=MockBot()
        )
        await delete_meal_callback(
            callback, DeleteMealCb(meal_id=meal_id), MockI18n()
        )

        with test_db.session() as session:
            assert db_funcs.get_meal(session, meal_id) is not None
