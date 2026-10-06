"""
Периодический опрос БД → бизнес-gauge'и (пользователи, подписки, DAU).

Запускается фоновой asyncio-задачей из main.py. Запросы — лёгкие count'ы,
выполняются синхронно в event loop (как в notifications/notifier.py).
"""

import asyncio
from datetime import timedelta

from sqlalchemy import distinct, func

from src.core.database.models import (
    Meal,
    Subscription,
    SubscriptionStatus,
    SubscriptionType,
    User,
)
from src.core.utils import get_logger
from src.core.utils.tz import utc_now_naive

from .registry import gauge_set

logger = get_logger()

POLL_INTERVAL_SECONDS = 60

# Типы, у которых считаем активные подписки (NONE — это «нет подписки»)
_GAUGE_SUB_TYPES = (
    SubscriptionType.TRIAL,
    SubscriptionType.PAID,
    SubscriptionType.UNLIMITED,
)


def update_business_gauges(db) -> None:
    """Читает агрегаты из БД и выставляет gauge'и."""
    now = utc_now_naive()
    day_ago = now - timedelta(hours=24)

    with db.session() as session:
        users_total = session.query(func.count(User.id)).scalar() or 0
        meals_total = session.query(func.count(Meal.id)).scalar() or 0
        users_active_24h = (
            session.query(func.count(distinct(Meal.user_id)))
            .filter(Meal.created_at >= day_ago)
            .scalar()
            or 0
        )

        # Активная подписка = status ACTIVE и не истекла (UNLIMITED не истекает)
        rows = (
            session.query(Subscription.type, func.count(Subscription.user_id))
            .filter(Subscription.status == SubscriptionStatus.ACTIVE)
            .filter(
                (Subscription.type == SubscriptionType.UNLIMITED)
                | (Subscription.ended_at > now)
            )
            .group_by(Subscription.type)
            .all()
        )
        active_by_type = {sub_type: count for sub_type, count in rows}

    gauge_set("fivekcal_users_total", users_total, help="Total registered users")
    gauge_set("fivekcal_meals_total", meals_total, help="Total meals in database")
    gauge_set(
        "fivekcal_users_active_24h",
        users_active_24h,
        help="Distinct users who saved a meal in the last 24h",
    )
    for sub_type in _GAUGE_SUB_TYPES:
        gauge_set(
            "fivekcal_subscriptions_active",
            active_by_type.get(sub_type, 0),
            labels={"type": sub_type.value},
            help="Active non-expired subscriptions by type",
        )


async def run_business_gauges_poller(db) -> None:
    """Обновляет бизнес-gauge'и каждые POLL_INTERVAL_SECONDS."""
    while True:
        try:
            update_business_gauges(db)
        except Exception as e:
            logger.warning(
                "Не удалось обновить бизнес-метрики", extra={"error": str(e)}
            )
        await asyncio.sleep(POLL_INTERVAL_SECONDS)
