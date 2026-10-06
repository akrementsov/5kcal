from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional, TYPE_CHECKING

from src.core.database.database import Database
from src.core.database import db as db_funcs, SubscriptionType, SubscriptionStatus
from src.core.tracking import events
from src.core.utils import get_logger

if TYPE_CHECKING:
    from src.core.tracking import EventTracker
from src.core.utils.tz import (
    date_in_tz,
    end_of_day_utc,
    today_for_tz,
    utc_now_naive,
)


def _utc_now() -> datetime:
    """Naive UTC datetime — для сравнения с ended_at (тоже naive UTC-based)."""
    return utc_now_naive()


TRIAL_DAYS = 5
SUBSCRIPTION_ENDING_DAYS = 3
logger = get_logger()


def _end_of_day(days: int, user_tz: str = "UTC") -> datetime:
    """Конец подписки: 23:59:59 последнего дня в timezone пользователя → naive UTC."""
    end = today_for_tz(user_tz) + timedelta(days=days)
    return end_of_day_utc(end, user_tz)


@dataclass
class SubscriptionInfo:
    """Информация о подписке пользователя для отображения в UI."""

    can_trial: bool = False
    is_ending: bool = False
    is_active: bool = False
    is_trial: bool = False
    is_unlimited: bool = False
    sub_type: Optional[SubscriptionType] = None
    ended_at: Optional[datetime] = None
    ended_on: Optional[date] = None


class SubscriptionService:
    def __init__(self, db: Database, event_tracker: "EventTracker | None" = None):
        self.db = db
        self._event_tracker: "EventTracker | None" = event_tracker

    def _track(
        self, user_id: int, event_type: str, payload: dict | None = None
    ) -> None:
        """Трекинг события монетизации в ОТДЕЛЬНОЙ сессии (EventTracker.track
        никогда не бросает). Вызывать ПОСЛЕ закрытия бизнес-сессии метода, чтобы
        сбой трекинга не откатил оплату/триал/отмену."""
        if self._event_tracker is not None:
            self._event_tracker.track(user_id, event_type, payload)

    def get_info(self, user_id: int) -> SubscriptionInfo:
        with self.db.session() as session:
            used_trial = db_funcs.has_used_trial(session, user_id)
            sub = db_funcs.get_user_subscription(session, user_id)
            user_tz, _ = db_funcs.get_user_timezone(session, user_id)

            info = SubscriptionInfo()
            info.can_trial = not used_trial

            if not sub:
                return info

            is_unlimited = sub.type == SubscriptionType.UNLIMITED

            if sub.status == SubscriptionStatus.ACTIVE and (
                is_unlimited or sub.ended_at > _utc_now()
            ):
                info.is_active = True
                info.is_trial = sub.type == SubscriptionType.TRIAL
                info.is_unlimited = is_unlimited
                info.sub_type = sub.type
                info.ended_at = sub.ended_at
                if not is_unlimited:
                    info.ended_on = date_in_tz(sub.ended_at, user_tz)
                    threshold_date = today_for_tz(user_tz) + timedelta(
                        days=SUBSCRIPTION_ENDING_DAYS
                    )
                    info.is_ending = info.ended_on <= threshold_date

            return info

    def can_activate_trial(self, user_id: int) -> bool:
        with self.db.session() as session:
            return not db_funcs.has_used_trial(session, user_id)

    def activate_trial(self, user_id: int, user_tz: str = "UTC") -> bool:
        with self.db.session() as session:
            if db_funcs.has_used_trial(session, user_id):
                logger.warning(
                    "Попытка повторной активации пробной подписки",
                    extra={"user_id": user_id},
                )
                return False
            ended_at = _end_of_day(TRIAL_DAYS, user_tz)
            db_funcs.set_subscription(
                session, user_id, SubscriptionType.TRIAL, ended_at
            )
            db_funcs.add_payment(
                session, user_id, TRIAL_DAYS, total_amount=0, provider="trial"
            )
            logger.info("Пробная подписка активирована", extra={"chat_id": user_id})
        # Эмит после закрытия сессии (в своей транзакции трекера)
        self._track(user_id, events.TRIAL_STARTED)
        return True

    def extend(
        self,
        user_id: int,
        days: int,
        total_amount: int = 0,
        telegram_charge_id: str | None = None,
        provider_charge_id: str | None = None,
        currency: str | None = None,
        provider: str | None = None,
        user_tz: str = "UTC",
    ) -> None:
        with self.db.session() as session:
            sub = db_funcs.get_user_subscription(session, user_id)
            if (
                sub
                and sub.type != SubscriptionType.UNLIMITED
                and sub.ended_at > _utc_now()
            ):
                base_date = date_in_tz(sub.ended_at, user_tz)
            else:
                base_date = today_for_tz(user_tz)
            end_date = base_date + timedelta(days=days)
            ended_at = end_of_day_utc(end_date, user_tz)
            db_funcs.set_subscription(session, user_id, SubscriptionType.PAID, ended_at)
            db_funcs.add_payment(
                session,
                user_id,
                days,
                total_amount,
                telegram_charge_id=telegram_charge_id,
                provider_charge_id=provider_charge_id,
                currency=currency,
                provider=provider,
            )
            logger.info(
                "Подписка продлена",
                extra={
                    "chat_id": user_id,
                    "days": days,
                    "ended_at": str(ended_at),
                },
            )
        # payment.succeeded — только реальные оплаты (Robokassa/Stars); админский
        # /sub_extend (provider="admin", amount=0) и триал сюда не попадают.
        if provider in ("robokassa", "stars"):
            self._track(
                user_id,
                events.PAYMENT_SUCCEEDED,
                {
                    "provider": provider,
                    "amount": total_amount,
                    "currency": currency,
                    "days": days,
                },
            )

    def get_active_type(self, user_id: int) -> Optional[SubscriptionType]:
        with self.db.session() as session:
            sub = db_funcs.get_user_subscription(session, user_id)
            if not sub or sub.status != SubscriptionStatus.ACTIVE:
                return None
            if sub.type == SubscriptionType.UNLIMITED:
                return sub.type
            if sub.ended_at <= _utc_now():
                return None
            return sub.type

    def get_active_ended_at(self, user_id: int) -> Optional[datetime]:
        with self.db.session() as session:
            sub = db_funcs.get_user_subscription(session, user_id)
            if not sub or sub.status != SubscriptionStatus.ACTIVE:
                return None
            if sub.type == SubscriptionType.UNLIMITED:
                return None
            if sub.ended_at <= _utc_now():
                return None
            return sub.ended_at

    def cancel(self, user_id: int) -> bool:
        with self.db.session() as session:
            ok = db_funcs.cancel_subscription(session, user_id, _utc_now())
            if ok:
                logger.info("Подписка отменена", extra={"chat_id": user_id})
        if ok:
            self._track(user_id, events.SUBSCRIPTION_CANCELLED)
        return ok

    def grant_unlimited(self, user_id: int) -> None:
        with self.db.session() as session:
            db_funcs.grant_unlimited(session, user_id)
            logger.info("Безлимитная подписка выдана", extra={"chat_id": user_id})

    def refund_payment(self, user_id: int, payment_id: int) -> tuple[bool, str]:
        """Возврат конкретной оплаты: создаёт запись возврата, вычитает дни."""
        with self.db.session() as session:
            from src.core.database.models import Payment

            payment = (
                session.query(Payment)
                .filter(Payment.id == payment_id, Payment.user_id == user_id)
                .first()
            )
            if not payment:
                return False, f"Платёж #{payment_id} не найден у пользователя {user_id}"

            if payment.days <= 0:
                return (
                    False,
                    f"Платёж #{payment_id} не является оплатой (days={payment.days})",
                )

            # Проверяем нет ли уже возврата для этого платежа
            existing_refund = (
                session.query(Payment)
                .filter(Payment.refund_for_id == payment_id)
                .first()
            )
            if existing_refund:
                return False, f"Платёж #{payment_id} уже возвращён"

            sub = db_funcs.get_user_subscription(session, user_id)
            if not sub:
                return False, f"Подписка пользователя {user_id} не найдена"

            refund_days = payment.days
            user_tz, _ = db_funcs.get_user_timezone(session, user_id)
            current_end_date = date_in_tz(sub.ended_at, user_tz)
            new_end_date = current_end_date - timedelta(days=refund_days)
            new_ended_at = end_of_day_utc(new_end_date, user_tz)

            if new_ended_at <= _utc_now():
                sub.type = SubscriptionType.NONE
                sub.status = SubscriptionStatus.CANCELLED
                sub.ended_at = _utc_now()
            else:
                sub.ended_at = new_ended_at

            # Создаём запись возврата со ссылкой на оригинал
            db_funcs.add_payment(
                session,
                user_id,
                days=-refund_days,
                total_amount=-payment.total_amount,
                refund_for_id=payment_id,
            )
            session.flush()

            logger.info(
                "Оплата отменена (refund)",
                extra={
                    "chat_id": user_id,
                    "payment_id": payment_id,
                    "refund_days": refund_days,
                    "new_ended_at": str(sub.ended_at),
                },
            )

            status = (
                "подписка отменена"
                if sub.status == SubscriptionStatus.CANCELLED
                else f"до {new_end_date.strftime('%d.%m.%Y')}"
            )
            return (
                True,
                f"Платёж #{payment_id} возвращён (−{refund_days} дн). Подписка: {status}",
            )

    def get_subscriptions_expiring_in(self, days: int):
        with self.db.session() as session:
            subs = db_funcs.get_subscriptions_expiring_in(session, days)
            for sub in subs:
                session.expunge(sub)
            return subs
