"""Тесты ChartService — агрегация данных для графиков."""

from datetime import date, datetime, timedelta

import pytest

from src.core.llm.two_call_models import build_range
from src.core.utils.tz import today_for_tz
from tests.helpers import save_test_meal

_TZ = "UTC"


class TestChartData:
    def test_empty(self, user_service, chart_service, test_db):
        user_service.get_or_create(user_id=1)

        result = chart_service.get_chart_data(user_id=1, period=7, user_tz=_TZ)

        assert len(result) == 7
        assert all(d.kcal == 0 for d in result)
        assert all(d.protein_g == 0 for d in result)

    def test_with_meals(self, user_service, chart_service, test_db):
        user_service.get_or_create(user_id=1)
        today = today_for_tz(_TZ)

        for offset in (0, -2, -5):
            d = today + timedelta(days=offset)
            dt = datetime(d.year, d.month, d.day, 12, 0, 0)
            save_test_meal(test_db, user_id=1, created_at=dt)

        result = chart_service.get_chart_data(user_id=1, period=7, user_tz=_TZ)

        assert len(result) == 7
        days_with_meals = [d for d in result if d.kcal > 0]
        days_without = [d for d in result if d.kcal == 0]
        assert len(days_with_meals) == 3
        assert len(days_without) == 4

    def test_aggregation(self, user_service, chart_service, test_db):
        user_service.get_or_create(user_id=1)
        today = today_for_tz(_TZ)
        noon = datetime(today.year, today.month, today.day, 12, 0, 0)

        # save_test_meal хранит точечное значение = (min+max)/2, confidence по умолчанию 10
        save_test_meal(
            test_db,
            user_id=1,
            created_at=noon,
            calories_min=100,
            calories_max=200,
            protein_min=5,
            protein_max=10,
        )
        save_test_meal(
            test_db,
            user_id=1,
            created_at=noon + timedelta(hours=1),
            calories_min=150,
            calories_max=250,
            protein_min=8,
            protein_max=12,
        )

        result = chart_service.get_chart_data(user_id=1, period=7, user_tz=_TZ)
        today_data = [d for d in result if d.date == today][0]

        # Точечные значения: 150 (=avg(100,200)) и 200 (=avg(150,250))
        assert today_data.kcal == 350  # 150 + 200
        assert today_data.protein_g == 17.5  # 7.5 + 10

        # Полоса разброса — build_range(value, confidence=10) на каждое блюдо
        lo1, hi1 = build_range(150, 10)
        lo2, hi2 = build_range(200, 10)
        assert today_data.kcal_min == pytest.approx(lo1 + lo2)
        assert today_data.kcal_max == pytest.approx(hi1 + hi2)

    def test_period_30(self, user_service, chart_service, test_db):
        user_service.get_or_create(user_id=1)

        result = chart_service.get_chart_data(user_id=1, period=30, user_tz=_TZ)

        assert len(result) == 30
        today = today_for_tz(_TZ)
        assert result[0].date == today - timedelta(days=29)
        assert result[-1].date == today

    def test_boundary(self, user_service, chart_service, test_db):
        user_service.get_or_create(user_id=1)
        today = today_for_tz(_TZ)
        start_date = today - timedelta(days=6)  # period=7

        # Блюдо на границе (start_date) — должно попасть
        dt_in = datetime(start_date.year, start_date.month, start_date.day, 12, 0, 0)
        save_test_meal(test_db, user_id=1, created_at=dt_in)

        # Блюдо до границы — не должно
        day_before = start_date - timedelta(days=1)
        dt_out = datetime(day_before.year, day_before.month, day_before.day, 12, 0, 0)
        save_test_meal(test_db, user_id=1, created_at=dt_out)

        result = chart_service.get_chart_data(user_id=1, period=7, user_tz=_TZ)

        first_day = [d for d in result if d.date == start_date][0]
        assert first_day.kcal > 0

        # Блюдо до start_date не попало
        all_kcal = sum(d.kcal for d in result)
        assert all_kcal == first_day.kcal  # только одно блюдо в результатах
