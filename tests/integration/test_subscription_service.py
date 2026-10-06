"""Тесты SubscriptionService — подписки, триал, продление, пауза, отмена."""

from datetime import datetime, timedelta

from src.core.database import db as db_funcs, SubscriptionType, SubscriptionStatus
from src.core.utils.tz import date_in_tz, end_of_day_utc, today_for_tz


class TestGetInfo:
    def test_no_subscription(self, user_service, subscription_service):
        user_service.get_or_create(user_id=1)

        info = subscription_service.get_info(1)

        assert info.can_trial is True
        assert info.is_active is False
        assert info.is_trial is False
        assert info.is_unlimited is False
        assert info.sub_type is None
        assert info.ended_at is None

    def test_active_paid(self, user_service, subscription_service):
        user_service.get_or_create(user_id=1)
        subscription_service.extend(1, days=30, total_amount=29900)

        info = subscription_service.get_info(1)

        assert info.is_active is True
        assert info.is_trial is False
        assert info.sub_type == SubscriptionType.PAID
        assert info.can_trial is True  # триал не использовался

    def test_expired(self, user_service, subscription_service, test_db):
        user_service.get_or_create(user_id=1)
        subscription_service.activate_trial(1)

        with test_db.session() as session:
            sub = db_funcs.get_user_subscription(session, 1)
            sub.ended_at = datetime.now() - timedelta(days=1)
            session.flush()

        info = subscription_service.get_info(1)

        assert info.is_active is False
        assert info.can_trial is False  # триал уже использован

    def test_unlimited(self, user_service, subscription_service):
        user_service.get_or_create(user_id=1)
        subscription_service.grant_unlimited(1)

        info = subscription_service.get_info(1)

        assert info.is_active is True
        assert info.is_unlimited is True
        assert info.is_ending is False
        assert info.is_trial is False

    def test_is_ending(self, user_service, subscription_service):
        user_service.get_or_create(user_id=1)
        subscription_service.extend(1, 2, 29900)

        info = subscription_service.get_info(1)

        assert info.is_ending is True  # ≤ 3 дней
        assert info.is_active is True

    def test_not_ending(self, user_service, subscription_service):
        user_service.get_or_create(user_id=1)
        subscription_service.extend(1, 30, 29900)

        info = subscription_service.get_info(1)

        assert info.is_ending is False
        assert info.is_active is True

    def test_is_ending_boundary_at_3_days(self, user_service, subscription_service):
        user_service.get_or_create(user_id=1)
        subscription_service.extend(1, 3, 29900)

        info = subscription_service.get_info(1)

        assert info.is_ending is True

    def test_is_ending_just_past_boundary(self, user_service, subscription_service):
        user_service.get_or_create(user_id=1)
        subscription_service.extend(1, 4, 29900)

        info = subscription_service.get_info(1)

        assert info.is_ending is False


class TestActivateTrial:
    def test_activate_trial(self, user_service, subscription_service):
        user_service.get_or_create(user_id=1)

        assert subscription_service.activate_trial(1) is True

        info = subscription_service.get_info(1)
        assert info.is_active is True
        assert info.is_trial is True
        assert info.sub_type == SubscriptionType.TRIAL
        assert info.can_trial is False
        expected_end = today_for_tz("UTC") + timedelta(days=5)
        assert info.ended_at.date() == expected_end

    def test_activate_trial_double(self, user_service, subscription_service):
        user_service.get_or_create(user_id=1)
        subscription_service.activate_trial(1)

        assert subscription_service.activate_trial(1) is False

    def test_can_activate_trial_before_after(self, user_service, subscription_service):
        user_service.get_or_create(user_id=1)

        assert subscription_service.can_activate_trial(1) is True
        subscription_service.activate_trial(1)
        assert subscription_service.can_activate_trial(1) is False

    def test_activate_trial_keeps_local_end_date_for_far_ahead_timezone(self, test_db):
        from src.features.user.service import UserService
        from src.features.subscription.service import SubscriptionService

        user_service = UserService(test_db, default_timezone="UTC")
        subscription_service = SubscriptionService(test_db)

        user_service.get_or_create(user_id=1)
        user_service.update_timezone(1, "Pacific/Kiritimati")

        assert (
            subscription_service.activate_trial(1, user_tz="Pacific/Kiritimati") is True
        )

        info = subscription_service.get_info(1)
        expected_end = today_for_tz("Pacific/Kiritimati") + timedelta(days=5)
        assert info.ended_on == expected_end


class TestExtend:
    def test_extend_adds_to_existing(self, user_service, subscription_service):
        user_service.get_or_create(user_id=1)
        subscription_service.extend(1, 30, 29900)
        ended_at_1 = subscription_service.get_active_ended_at(1)

        subscription_service.extend(1, 30, 29900)

        ended_at_2 = subscription_service.get_active_ended_at(1)
        delta = (ended_at_2 - ended_at_1).days
        assert delta == 30

    def test_extend_from_expired(self, user_service, subscription_service, test_db):
        user_service.get_or_create(user_id=1)
        subscription_service.activate_trial(1)

        with test_db.session() as session:
            sub = db_funcs.get_user_subscription(session, 1)
            sub.ended_at = datetime.now() - timedelta(days=10)
            session.flush()

        subscription_service.extend(1, 30, 29900)

        ended_at = subscription_service.get_active_ended_at(1)
        expected = today_for_tz("UTC") + timedelta(days=30)
        assert ended_at.date() == expected
        assert subscription_service.get_active_type(1) == SubscriptionType.PAID


class TestGetActiveType:
    def test_none_without_subscription(self, user_service, subscription_service):
        user_service.get_or_create(user_id=1)

        assert subscription_service.get_active_type(1) is None

    def test_expired_returns_none(self, user_service, subscription_service, test_db):
        user_service.get_or_create(user_id=1)
        subscription_service.activate_trial(1)

        with test_db.session() as session:
            sub = db_funcs.get_user_subscription(session, 1)
            sub.ended_at = datetime.now() - timedelta(days=1)
            session.flush()

        assert subscription_service.get_active_type(1) is None

    def test_unlimited(self, user_service, subscription_service):
        user_service.get_or_create(user_id=1)
        subscription_service.grant_unlimited(1)

        assert subscription_service.get_active_type(1) == SubscriptionType.UNLIMITED


class TestGetActiveEndedAt:
    def test_paid_returns_datetime(self, user_service, subscription_service):
        user_service.get_or_create(user_id=1)
        subscription_service.extend(1, 30, 29900)

        ended_at = subscription_service.get_active_ended_at(1)

        assert isinstance(ended_at, datetime)
        assert ended_at > datetime.now()

    def test_unlimited_returns_none(self, user_service, subscription_service):
        user_service.get_or_create(user_id=1)
        subscription_service.grant_unlimited(1)

        assert subscription_service.get_active_ended_at(1) is None


class TestCancel:
    def test_cancel_paid(self, user_service, subscription_service):
        user_service.get_or_create(user_id=1)
        subscription_service.extend(1, 30, 29900)

        assert subscription_service.cancel(1) is True

        info = subscription_service.get_info(1)
        assert info.is_active is False
        assert subscription_service.get_active_type(1) is None

    def test_cancel_unlimited(self, user_service, subscription_service):
        user_service.get_or_create(user_id=1)
        subscription_service.grant_unlimited(1)

        assert subscription_service.cancel(1) is True

        info = subscription_service.get_info(1)
        assert info.is_active is False
        assert subscription_service.get_active_type(1) is None

    def test_cancel_no_subscription(self, user_service, subscription_service):
        user_service.get_or_create(user_id=1)

        assert subscription_service.cancel(1) is False


class TestGrantUnlimited:
    def test_grant_new_user(self, user_service, subscription_service):
        user_service.get_or_create(user_id=1)

        subscription_service.grant_unlimited(1)

        info = subscription_service.get_info(1)
        assert info.is_active is True
        assert info.is_unlimited is True

    def test_grant_replaces_paid(self, user_service, subscription_service):
        user_service.get_or_create(user_id=1)
        subscription_service.extend(1, 30, 29900)

        subscription_service.grant_unlimited(1)

        info = subscription_service.get_info(1)
        assert info.is_active is True
        assert info.is_unlimited is True

    def test_grant_uncancels(self, user_service, subscription_service):
        user_service.get_or_create(user_id=1)
        subscription_service.extend(1, 30, 29900)
        subscription_service.cancel(1)

        subscription_service.grant_unlimited(1)

        info = subscription_service.get_info(1)
        assert info.is_active is True
        assert info.is_unlimited is True


class TestExpiringSubscriptions:
    def test_expiring_in_uses_user_local_date_even_if_utc_date_differs(self, test_db):
        from src.features.user.service import UserService
        from src.features.subscription.service import SubscriptionService

        user_service = UserService(test_db, default_timezone="UTC")
        subscription_service = SubscriptionService(test_db)

        user_service.get_or_create(user_id=1)
        user_service.update_timezone(1, "Pacific/Kiritimati")
        subscription_service.extend(1, 3, 29900, user_tz="Pacific/Kiritimati")

        expiring = subscription_service.get_subscriptions_expiring_in(3)

        assert [sub.user_id for sub in expiring] == [1]


class TestEndedAtIsEndOfDay:
    """ended_at хранит 23:59:59 последнего дня в timezone пользователя (в UTC)."""

    def test_trial_ended_at_is_end_of_day_utc(
        self, user_service, subscription_service, test_db
    ):
        user_service.get_or_create(user_id=1)
        subscription_service.activate_trial(1, user_tz="UTC")

        with test_db.session() as session:
            sub = db_funcs.get_user_subscription(session, 1)
            end_date = today_for_tz("UTC") + timedelta(days=5)
            expected = end_of_day_utc(end_date, "UTC")
            assert sub.ended_at == expected

    def test_trial_ended_at_is_end_of_day_far_ahead_tz(self, test_db):
        from src.features.user.service import UserService
        from src.features.subscription.service import SubscriptionService

        user_service = UserService(test_db, default_timezone="UTC")
        subscription_service = SubscriptionService(test_db)

        user_service.get_or_create(user_id=1)
        user_service.update_timezone(1, "Pacific/Kiritimati")
        subscription_service.activate_trial(1, user_tz="Pacific/Kiritimati")

        with test_db.session() as session:
            sub = db_funcs.get_user_subscription(session, 1)
            end_date = today_for_tz("Pacific/Kiritimati") + timedelta(days=5)
            expected = end_of_day_utc(end_date, "Pacific/Kiritimati")
            assert sub.ended_at == expected

    def test_extend_ended_at_is_end_of_day(
        self, user_service, subscription_service, test_db
    ):
        user_service.get_or_create(user_id=1)
        subscription_service.extend(1, 30, 29900, user_tz="UTC")

        with test_db.session() as session:
            sub = db_funcs.get_user_subscription(session, 1)
            end_date = today_for_tz("UTC") + timedelta(days=30)
            expected = end_of_day_utc(end_date, "UTC")
            assert sub.ended_at == expected

    def test_extend_different_tz(self, test_db):
        from src.features.user.service import UserService
        from src.features.subscription.service import SubscriptionService

        user_service = UserService(test_db, default_timezone="UTC")
        subscription_service = SubscriptionService(test_db)

        user_service.get_or_create(user_id=1)
        user_service.update_timezone(1, "Asia/Tokyo")
        subscription_service.extend(1, 30, 29900, user_tz="Asia/Tokyo")

        with test_db.session() as session:
            sub = db_funcs.get_user_subscription(session, 1)
            end_date = today_for_tz("Asia/Tokyo") + timedelta(days=30)
            expected = end_of_day_utc(end_date, "Asia/Tokyo")
            assert sub.ended_at == expected

    def test_ended_at_roundtrips_to_correct_date(
        self, user_service, subscription_service, test_db
    ):
        """date_in_tz(ended_at) == дата окончания для любой timezone."""
        user_service.get_or_create(user_id=1)
        subscription_service.extend(1, 10, 29900, user_tz="UTC")

        with test_db.session() as session:
            sub = db_funcs.get_user_subscription(session, 1)
            expected_date = today_for_tz("UTC") + timedelta(days=10)
            assert date_in_tz(sub.ended_at, "UTC") == expected_date

    def test_subscription_valid_through_entire_last_day(
        self, user_service, subscription_service, test_db
    ):
        """Подписка активна весь последний день (23:59:59), а не только до полудня."""
        user_service.get_or_create(user_id=1)
        subscription_service.extend(1, 5, 29900, user_tz="UTC")

        with test_db.session() as session:
            sub = db_funcs.get_user_subscription(session, 1)
            last_day = today_for_tz("UTC") + timedelta(days=5)
            # 23:00 последнего дня — подписка ещё активна
            late_evening = datetime(
                last_day.year, last_day.month, last_day.day, 23, 0, 0
            )
            assert sub.ended_at > late_evening

    def test_grant_unlimited_uses_end_of_day(
        self, user_service, subscription_service, test_db
    ):
        user_service.get_or_create(user_id=1)
        subscription_service.grant_unlimited(1)

        with test_db.session() as session:
            sub = db_funcs.get_user_subscription(session, 1)
            assert sub.ended_at == datetime(2099, 12, 31, 23, 59, 59)

    def test_refund_ended_at_is_end_of_day(
        self, user_service, subscription_service, test_db
    ):
        user_service.get_or_create(user_id=1)
        subscription_service.extend(1, 30, 29900)
        subscription_service.extend(1, 10, 10000)

        with test_db.session() as session:
            payments = db_funcs.get_user_payments(session, 1)
            last_payment_id = payments[0].id

        ok, _ = subscription_service.refund_payment(1, last_payment_id)
        assert ok is True

        with test_db.session() as session:
            sub = db_funcs.get_user_subscription(session, 1)
            # ended_at — конец 30-го дня (минус 10 рефанд — осталось 30)
            assert sub.ended_at.second == 59
            assert sub.ended_at.minute == 59
            assert sub.ended_at.hour == 23  # UTC timezone → 23:59:59 UTC


class TestCancelSetsTypeNone:
    """Проверяем что отмена ставит type=NONE."""

    def test_cancel_paid_sets_none(self, user_service, subscription_service, test_db):
        user_service.get_or_create(user_id=1)
        subscription_service.extend(1, 30, 29900)

        subscription_service.cancel(1)

        with test_db.session() as session:
            sub = db_funcs.get_user_subscription(session, 1)
            assert sub.type == SubscriptionType.NONE
            assert sub.status == SubscriptionStatus.CANCELLED

    def test_cancel_unlimited_sets_none(
        self, user_service, subscription_service, test_db
    ):
        user_service.get_or_create(user_id=1)
        subscription_service.grant_unlimited(1)

        subscription_service.cancel(1)

        with test_db.session() as session:
            sub = db_funcs.get_user_subscription(session, 1)
            assert sub.type == SubscriptionType.NONE

    def test_cancel_trial_sets_none(self, user_service, subscription_service, test_db):
        user_service.get_or_create(user_id=1)
        subscription_service.activate_trial(1)

        subscription_service.cancel(1)

        with test_db.session() as session:
            sub = db_funcs.get_user_subscription(session, 1)
            assert sub.type == SubscriptionType.NONE

    def test_has_used_trial_still_works_after_cancel(
        self, user_service, subscription_service, test_db
    ):
        """has_used_trial проверяет payments (days > 0 AND total_amount == 0) — cancel не должен ломать."""
        user_service.get_or_create(user_id=1)
        subscription_service.activate_trial(1)
        subscription_service.cancel(1)

        assert subscription_service.can_activate_trial(1) is False


class TestReactivationAfterCancel:
    """Регрессия: set_subscription не сбрасывал status CANCELLED → ACTIVE,
    и оплата после отмены не возвращала доступ (деньги списаны, paywall остаётся)."""

    def test_extend_after_cancel_reactivates(self, user_service, subscription_service):
        """Оплата после отмены подписки снова делает её активной."""
        user_service.get_or_create(user_id=1)
        subscription_service.extend(1, days=30, total_amount=299)
        assert subscription_service.get_info(1).is_active is True

        subscription_service.cancel(1)
        assert subscription_service.get_info(1).is_active is False

        subscription_service.extend(1, days=30, total_amount=299)
        assert subscription_service.get_info(1).is_active is True

    def test_trial_after_cancel_reactivates(self, user_service, subscription_service):
        """Триал после отмены платной подписки тоже активирует доступ."""
        user_service.get_or_create(user_id=2)
        subscription_service.extend(2, days=30, total_amount=299)
        subscription_service.cancel(2)

        assert subscription_service.activate_trial(2) is True
        assert subscription_service.get_info(2).is_active is True


class TestTrialVsAdminGift:
    """Админ-подарок дней (/sub_extend: total_amount=0, provider='admin')
    не должен засчитываться как использованный триал."""

    def test_admin_gift_does_not_burn_trial(
        self, user_service, subscription_service, test_db
    ):
        user_service.get_or_create(user_id=1)
        with test_db.session() as session:
            db_funcs.add_payment(
                session, 1, days=7, total_amount=0, provider="admin"
            )

        assert subscription_service.can_activate_trial(1) is True
        assert subscription_service.activate_trial(1) is True
        # Настоящий триал использован — повторно нельзя
        assert subscription_service.can_activate_trial(1) is False
