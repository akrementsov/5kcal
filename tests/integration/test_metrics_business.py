"""Тесты бизнес-метрик: gauge'и из БД (business.py) и счётчики платежей."""

from datetime import timedelta

import pytest

from src.core.database import db as db_funcs
from src.core.database.models import (
    Meal,
    Subscription,
    SubscriptionStatus,
    SubscriptionType,
    User,
)
from src.core.metrics.business import update_business_gauges
from src.core.metrics.registry import render_metrics
from src.core.utils.tz import utc_now_naive


@pytest.fixture(autouse=True)
def _reset_registry():
    from src.core.metrics import registry as r

    r._counters.clear()
    r._gauges.clear()
    r._histograms.clear()
    r._meta.clear()
    yield
    r._counters.clear()
    r._gauges.clear()
    r._histograms.clear()
    r._meta.clear()


def _add_user(session, user_id: int) -> None:
    session.add(User(user_id=user_id))
    session.flush()


def _add_subscription(session, user_id: int, sub_type, status, ended_at) -> None:
    session.add(
        Subscription(user_id=user_id, type=sub_type, status=status, ended_at=ended_at)
    )
    session.flush()


class TestBusinessGauges:
    def test_counts_users_meals_and_dau(self, test_db):
        now = utc_now_naive()
        with test_db.session() as session:
            _add_user(session, 1)
            _add_user(session, 2)
            _add_user(session, 3)
            # user 1: свежий приём пищи (DAU), user 2: старый (не DAU)
            session.add(Meal(user_id=1, created_at=now - timedelta(hours=1)))
            session.add(Meal(user_id=1, created_at=now - timedelta(hours=2)))
            session.add(Meal(user_id=2, created_at=now - timedelta(days=3)))
            session.flush()

        update_business_gauges(test_db)

        text = render_metrics()
        assert "fivekcal_users_total 3" in text
        assert "fivekcal_meals_total 3" in text
        assert "fivekcal_users_active_24h 1" in text

    def test_counts_active_subscriptions_by_type(self, test_db):
        now = utc_now_naive()
        future = now + timedelta(days=10)
        past = now - timedelta(days=1)
        with test_db.session() as session:
            for uid in (1, 2, 3, 4):
                _add_user(session, uid)
            _add_subscription(session, 1, SubscriptionType.PAID, SubscriptionStatus.ACTIVE, future)
            _add_subscription(session, 2, SubscriptionType.PAID, SubscriptionStatus.ACTIVE, past)  # истекла
            _add_subscription(session, 3, SubscriptionType.TRIAL, SubscriptionStatus.ACTIVE, future)
            _add_subscription(session, 4, SubscriptionType.UNLIMITED, SubscriptionStatus.ACTIVE, past)  # не истекает

        update_business_gauges(test_db)

        text = render_metrics()
        assert 'fivekcal_subscriptions_active{type="paid"} 1' in text
        assert 'fivekcal_subscriptions_active{type="trial"} 1' in text
        assert 'fivekcal_subscriptions_active{type="unlimited"} 1' in text

    def test_zero_gauges_on_empty_db(self, test_db):
        update_business_gauges(test_db)

        text = render_metrics()
        assert "fivekcal_users_total 0" in text
        assert 'fivekcal_subscriptions_active{type="paid"} 0' in text


class TestPaymentCounters:
    def test_paid_payment_increments_records_and_amount(self, test_db):
        with test_db.session() as session:
            _add_user(session, 1)
            db_funcs.add_payment(
                session, 1, days=30, total_amount=199,
                currency="RUB", provider="robokassa",
            )

        text = render_metrics()
        assert 'fivekcal_payment_records_total{kind="paid",provider="robokassa"} 1' in text
        assert 'fivekcal_payment_amount_total{currency="RUB",provider="robokassa"} 199' in text

    def test_trial_counted_without_amount(self, test_db):
        with test_db.session() as session:
            _add_user(session, 1)
            db_funcs.add_payment(session, 1, days=7, total_amount=0)

        text = render_metrics()
        assert 'fivekcal_payment_records_total{kind="trial",provider="none"} 1' in text
        assert "fivekcal_payment_amount_total" not in text

    def test_refund_goes_to_separate_monotonic_counter(self, test_db):
        with test_db.session() as session:
            _add_user(session, 1)
            db_funcs.add_payment(
                session, 1, days=-30, total_amount=-199,
                currency="RUB", provider="robokassa",
            )

        text = render_metrics()
        assert 'fivekcal_payment_records_total{kind="refund",provider="robokassa"} 1' in text
        assert 'fivekcal_refund_amount_total{currency="RUB",provider="robokassa"} 199' in text
        assert 'fivekcal_payment_amount_total{currency="RUB",provider="robokassa"}' not in text
