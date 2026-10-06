from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

from src.core.database.database import Database
from src.core.database import db as db_funcs
from src.core.llm.two_call_models import build_range
from src.core.utils.nutrition import rval
from src.core.utils.tz import today_for_tz, day_bounds_utc, date_in_tz


@dataclass
class DayData:
    date: date
    kcal: float
    kcal_min: float
    kcal_max: float
    protein_g: float
    protein_min: float
    protein_max: float
    fat_g: float
    fat_min: float
    fat_max: float
    carbs_g: float
    carbs_min: float
    carbs_max: float


def _sum_with_band(meals: list, attr: str) -> tuple[float, float, float]:
    """Сумма точечных значений + полоса разброса (± meal.confidence%, на лету)."""
    total = lo_sum = hi_sum = 0.0
    for m in meals:
        value = rval(getattr(m, attr))
        pct = m.confidence if m.confidence is not None else 15
        lo, hi = build_range(value, pct)
        total += value
        lo_sum += lo
        hi_sum += hi
    return total, lo_sum, hi_sum


class ChartService:
    def __init__(self, db: Database):
        self.db = db

    def get_chart_data(
        self, user_id: int, period: int, user_tz: str = "UTC"
    ) -> list[DayData]:
        """Возвращает агрегированные данные по дням за последние `period` дней."""
        end_date = today_for_tz(user_tz)
        start_date = end_date - timedelta(days=period - 1)
        start_dt, _ = day_bounds_utc(start_date, user_tz)
        _, end_dt = day_bounds_utc(end_date, user_tz)

        with self.db.session() as session:
            meals = db_funcs.get_meals_for_daterange(session, user_id, start_dt, end_dt)

            day_map: dict[date, list] = defaultdict(list)
            for meal in meals:
                day_map[date_in_tz(meal.created_at, user_tz)].append(meal)

            result = []
            for i in range(period):
                d = start_date + timedelta(days=i)
                ms = day_map.get(d, [])
                kcal, kcal_min, kcal_max = _sum_with_band(ms, "calories_kcal")
                protein_g, protein_min, protein_max = _sum_with_band(ms, "protein_g")
                fat_g, fat_min, fat_max = _sum_with_band(ms, "fat_g")
                carbs_g, carbs_min, carbs_max = _sum_with_band(ms, "carbs_g")
                result.append(
                    DayData(
                        date=d,
                        kcal=kcal,
                        kcal_min=kcal_min,
                        kcal_max=kcal_max,
                        protein_g=protein_g,
                        protein_min=protein_min,
                        protein_max=protein_max,
                        fat_g=fat_g,
                        fat_min=fat_min,
                        fat_max=fat_max,
                        carbs_g=carbs_g,
                        carbs_min=carbs_min,
                        carbs_max=carbs_max,
                    )
                )
        return result
