from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

from src.core.database.database import Database
from src.core.database import db as db_funcs
from src.core.utils import get_logger
from src.core.utils.tz import today_for_tz, date_in_tz, day_bounds_utc
from src.core.utils.nutrition import rval

logger = get_logger()


@dataclass
class DayEntry:
    date: date
    meal_count: int
    approx_calories: int


@dataclass
class WeekSummary:
    week_start: date
    week_end: date
    days: list
    approx_total_calories: int
    total_meals: int
    has_prev_week: bool
    has_next_week: bool
    has_any_meals: bool


@dataclass
class MealGroup:
    name: str
    count: int
    last_meal_id: int
    all_meal_ids: list
    total_calories: int
    total_weight: int
    total_protein: float
    total_fat: float
    total_carbs: float
    message_id: Optional[int]
    emoji: str = ""


@dataclass
class DayDetail:
    date: date
    groups: list
    approx_total_calories: int
    approx_total_protein: float
    approx_total_fat: float
    approx_total_carbs: float
    has_prev_day: bool
    has_next_day: bool
    week_offset: int


def _get_week_bounds(week_offset: int, user_tz: str) -> tuple[date, date]:
    today = today_for_tz(user_tz)
    week_start = today - timedelta(days=today.weekday())
    week_start += timedelta(weeks=week_offset)
    week_end = week_start + timedelta(days=6)
    return week_start, week_end


def date_to_week_offset(d: date, user_tz: str) -> int:
    today = today_for_tz(user_tz)
    current_week_start = today - timedelta(days=today.weekday())
    d_week_start = d - timedelta(days=d.weekday())
    return (d_week_start - current_week_start).days // 7


class HistoryService:
    def __init__(self, db: Database):
        self.db = db

    def get_week_summary(
        self, user_id: int, week_offset: int, user_tz: str
    ) -> WeekSummary:
        week_start, week_end = _get_week_bounds(week_offset, user_tz)
        logger.info(
            "Запрашиваем недельную сводку",
            extra={
                "chat_id": user_id,
                "week_offset": week_offset,
                "week_start": week_start.isoformat(),
                "week_end": week_end.isoformat(),
            },
        )
        start_dt, _ = day_bounds_utc(week_start, user_tz)
        _, end_dt = day_bounds_utc(week_end, user_tz)

        with self.db.session() as session:
            meals = db_funcs.get_meals_for_daterange(session, user_id, start_dt, end_dt)
            first_meal_dt = db_funcs.get_user_first_meal_date(session, user_id)

            day_map: dict[date, list] = {}
            for meal in meals:
                d = date_in_tz(meal.created_at, user_tz)
                day_map.setdefault(d, []).append(meal)

            days = []
            total_meals = 0
            total_kcal = 0
            for i in range(7):
                d = week_start + timedelta(days=i)
                day_meals = day_map.get(d, [])
                approx_kcal = sum(int(rval(m.calories_kcal)) for m in day_meals)
                days.append(
                    DayEntry(
                        date=d,
                        meal_count=len(day_meals),
                        approx_calories=approx_kcal,
                    )
                )
                total_meals += len(day_meals)
                total_kcal += approx_kcal

            has_any_meals = first_meal_dt is not None
            if has_any_meals:
                first_meal_date = date_in_tz(first_meal_dt, user_tz)
                first_meal_week_start = first_meal_date - timedelta(
                    days=first_meal_date.weekday()
                )
                has_prev_week = week_start > first_meal_week_start
            else:
                has_prev_week = False

        logger.info(
            "Недельная сводка готова",
            extra={
                "chat_id": user_id,
                "total_meals": total_meals,
                "total_kcal": total_kcal,
            },
        )
        return WeekSummary(
            week_start=week_start,
            week_end=week_end,
            days=days,
            approx_total_calories=total_kcal,
            total_meals=total_meals,
            has_prev_week=has_prev_week,
            has_next_week=week_offset < 0,
            has_any_meals=has_any_meals,
        )

    def _empty_day_detail(self, d: date, week_offset: int) -> DayDetail:
        return DayDetail(
            date=d,
            groups=[],
            approx_total_calories=0,
            approx_total_protein=0.0,
            approx_total_fat=0.0,
            approx_total_carbs=0.0,
            has_prev_day=False,
            has_next_day=False,
            week_offset=week_offset,
        )

    def get_day_detail(
        self, user_id: int, date_str: str, week_offset: int, user_tz: str
    ) -> DayDetail:
        try:
            d = date.fromisoformat(date_str)
        except ValueError:
            logger.warning(
                "Невалидная дата в get_day_detail",
                extra={"chat_id": user_id, "date": date_str},
            )
            return self._empty_day_detail(today_for_tz(user_tz), week_offset)
        logger.info(
            "Запрашиваем детали дня", extra={"chat_id": user_id, "date": date_str}
        )
        start_dt, end_dt = day_bounds_utc(d, user_tz)
        today = today_for_tz(user_tz)

        with self.db.session() as session:
            meals = db_funcs.get_meals_for_daterange(session, user_id, start_dt, end_dt)
            first_meal_dt = db_funcs.get_user_first_meal_date(session, user_id)

            first_meal_date = date_in_tz(first_meal_dt, user_tz) if first_meal_dt else d

            groups = []
            total_kcal = 0
            total_protein = 0.0
            total_fat = 0.0
            total_carbs = 0.0

            for meal in meals:
                g_kcal = int(rval(meal.calories_kcal))
                g_weight = int(rval(meal.weight_g))
                g_protein = rval(meal.protein_g)
                g_fat = rval(meal.fat_g)
                g_carbs = rval(meal.carbs_g)
                groups.append(
                    MealGroup(
                        name=meal.name or "",
                        count=meal.count or 1,
                        last_meal_id=meal.id,
                        all_meal_ids=[meal.id],
                        total_calories=g_kcal,
                        total_weight=g_weight,
                        total_protein=g_protein,
                        total_fat=g_fat,
                        total_carbs=g_carbs,
                        message_id=meal.message_id,
                        emoji=meal.emoji or "",
                    )
                )
                total_kcal += g_kcal
                total_protein += g_protein
                total_fat += g_fat
                total_carbs += g_carbs

        logger.info(
            "Детали дня готовы",
            extra={
                "chat_id": user_id,
                "date": date_str,
                "groups_count": len(groups),
                "total_kcal": total_kcal,
            },
        )
        return DayDetail(
            date=d,
            groups=groups,
            approx_total_calories=total_kcal,
            approx_total_protein=total_protein,
            approx_total_fat=total_fat,
            approx_total_carbs=total_carbs,
            has_prev_day=(d - timedelta(days=1)) >= first_meal_date,
            has_next_day=(d + timedelta(days=1)) <= today,
            week_offset=week_offset,
        )
