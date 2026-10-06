"""Тесты HistoryService — недельная сводка и детали дня."""

from datetime import datetime, timedelta, date, timezone

from src.core.utils.tz import today_for_tz
from tests.helpers import save_test_meal

_TZ = "UTC"


def _utc_now() -> datetime:
    """Naive UTC datetime для тестовых данных."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _utc_today() -> date:
    return today_for_tz(_TZ)


def _weekday_dt(weekday: int, hour: int = 12) -> datetime:
    """Возвращает datetime текущей недели для заданного дня (0=пн) в UTC."""
    today = _utc_today()
    monday = today - timedelta(days=today.weekday())
    d = monday + timedelta(days=weekday)
    return datetime(d.year, d.month, d.day, hour, 0, 0)


class TestWeekSummary:
    def test_empty(self, user_service, history_service, test_db):
        user_service.get_or_create(user_id=1)

        summary = history_service.get_week_summary(
            user_id=1, week_offset=0, user_tz="UTC"
        )

        assert summary.total_meals == 0
        assert summary.approx_total_calories == 0
        assert summary.has_any_meals is False
        assert summary.has_prev_week is False
        assert summary.has_next_week is False
        assert len(summary.days) == 7
        assert all(d.meal_count == 0 for d in summary.days)

    def test_with_meals(self, user_service, history_service, test_db):
        user_service.get_or_create(user_id=1)

        # Три блюда: пн, ср, пт (cal 200-300 → точечное значение 250)
        for wd in (0, 2, 4):
            save_test_meal(
                test_db,
                user_id=1,
                created_at=_weekday_dt(wd),
                calories_min=200,
                calories_max=300,
            )

        summary = history_service.get_week_summary(
            user_id=1, week_offset=0, user_tz="UTC"
        )

        assert summary.total_meals == 3
        assert summary.approx_total_calories == 750
        assert summary.has_any_meals is True

    def test_prev_week(self, user_service, history_service, test_db):
        user_service.get_or_create(user_id=1)
        last_week = _utc_now() - timedelta(weeks=1)
        save_test_meal(test_db, user_id=1, created_at=last_week)

        summary = history_service.get_week_summary(
            user_id=1, week_offset=-1, user_tz="UTC"
        )

        assert summary.has_next_week is True
        assert summary.total_meals >= 1

    def test_has_prev(self, user_service, history_service, test_db):
        user_service.get_or_create(user_id=1)
        two_weeks_ago = _utc_now() - timedelta(weeks=2)
        save_test_meal(test_db, user_id=1, created_at=two_weeks_ago)

        summary = history_service.get_week_summary(
            user_id=1, week_offset=-1, user_tz="UTC"
        )

        assert summary.has_prev_week is True

    def test_timezone(self, user_service, history_service, test_db):
        user_service.get_or_create(user_id=1)
        today = _utc_today()
        # 23:00 UTC сегодня → 02:00 завтра по Москве (+3)
        created = datetime(today.year, today.month, today.day, 23, 0, 0)
        save_test_meal(test_db, user_id=1, created_at=created)

        # В UTC это сегодня
        summary_utc = history_service.get_week_summary(
            user_id=1, week_offset=0, user_tz="UTC"
        )
        utc_today_entry = [d for d in summary_utc.days if d.date == today]
        assert len(utc_today_entry) == 1
        assert utc_today_entry[0].meal_count == 1

        # В Moscow это завтра
        tomorrow = today + timedelta(days=1)
        summary_msk = history_service.get_week_summary(
            user_id=1, week_offset=0, user_tz="Europe/Moscow"
        )
        msk_tomorrow_entry = [d for d in summary_msk.days if d.date == tomorrow]
        if msk_tomorrow_entry:
            assert msk_tomorrow_entry[0].meal_count == 1


class TestDayDetail:
    def test_empty(self, user_service, history_service, test_db):
        user_service.get_or_create(user_id=1)
        today = today_for_tz("UTC")

        detail = history_service.get_day_detail(
            user_id=1, date_str=today.isoformat(), week_offset=0, user_tz="UTC"
        )

        assert detail.groups == []
        assert detail.approx_total_calories == 0
        assert detail.approx_total_protein == 0.0
        assert detail.approx_total_fat == 0.0
        assert detail.approx_total_carbs == 0.0

    def test_with_meals(self, user_service, history_service, test_db):
        user_service.get_or_create(user_id=1)
        today = _utc_today()
        noon = datetime(today.year, today.month, today.day, 12, 0, 0)

        save_test_meal(
            test_db,
            user_id=1,
            created_at=noon,
            name="Суп",
            calories_min=200,
            calories_max=300,
            protein_min=10,
            protein_max=20,
        )
        save_test_meal(
            test_db,
            user_id=1,
            created_at=noon + timedelta(hours=1),
            name="Хлеб",
            calories_min=100,
            calories_max=150,
            protein_min=3,
            protein_max=5,
        )

        detail = history_service.get_day_detail(
            user_id=1, date_str=today.isoformat(), week_offset=0, user_tz="UTC"
        )

        assert len(detail.groups) == 2
        assert detail.approx_total_calories == 375  # 250 + 125
        assert detail.approx_total_protein == 19.0  # 15 + 4

    def test_navigation(self, user_service, history_service, test_db):
        user_service.get_or_create(user_id=1)
        today = _utc_today()

        for offset in (-2, -1, 0):
            d = today + timedelta(days=offset)
            dt = datetime(d.year, d.month, d.day, 12, 0, 0)
            save_test_meal(test_db, user_id=1, created_at=dt)

        yesterday = today + timedelta(days=-1)
        detail = history_service.get_day_detail(
            user_id=1,
            date_str=yesterday.isoformat(),
            week_offset=0,
            user_tz="UTC",
        )

        assert detail.has_prev_day is True
        assert detail.has_next_day is True
