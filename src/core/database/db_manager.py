from typing import Optional, List
from datetime import datetime, date, timedelta

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError

from src.core.database.models import (
    User,
    Subscription,
    SubscriptionType,
    SubscriptionStatus,
    Payment,
    SubscriptionEvent,
    UserEvent,
    Meal,
    MealAnalysisLog,
    BarcodeCache,
)
from src.core.metrics import counter_inc
from src.core.utils import get_logger
from src.core.utils.tz import (
    date_in_tz,
    local_date_to_utc_naive,
    today_for_tz,
    utc_now_naive,
)

logger = get_logger()


# ---------- Chat (User) Operations ----------


def get_or_create_user(session, chat_id: int, tag: Optional[str] = None) -> User:
    """
    Получает существующего пользователя или создает нового.

    Args:
        session: Сессия базы данных
        chat_id: Telegram chat ID (используется как идентификатор пользователя)
        tag: Реферальная метка (опционально)

    Returns:
        User: Объект пользователя
    """
    user = session.query(User).filter(User.user_id == chat_id).first()
    if user:
        logger.info("Пользователь уже существует", extra={"chat_id": chat_id})
        return user

    # Создаём нового пользователя; при гонке двух параллельных запросов
    # IntegrityError на unique constraint — перечитываем из БД.
    user = User(user_id=chat_id, start_tag=tag)
    session.add(user)
    try:
        session.flush()
        counter_inc(
            "fivekcal_users_new_total",
            help="Total new users registered",
        )
    except IntegrityError:
        session.rollback()
        user = session.query(User).filter(User.user_id == chat_id).first()
        logger.info(
            "Пользователь уже существует (race condition)", extra={"chat_id": chat_id}
        )
    return user


def user_exists(session, chat_id: int) -> bool:
    """True, если пользователь уже есть в БД (для отличия первого /start от повторного)."""
    return session.query(User.id).filter(User.user_id == chat_id).first() is not None


# ---------- Subscription Operations ----------


def get_user_subscription(session, user_id: int) -> Optional[Subscription]:
    """Возвращает подписку пользователя (одна строка на пользователя)."""
    return session.query(Subscription).filter(Subscription.user_id == user_id).first()


def set_subscription(
    session, user_id: int, sub_type: SubscriptionType, ended_at: datetime
) -> Subscription:
    """Создаёт или обновляет подписку пользователя."""
    sub = session.query(Subscription).filter(Subscription.user_id == user_id).first()
    if sub:
        sub.type = sub_type
        sub.ended_at = ended_at
        # Оплата/триал после отмены снова активирует подписку
        sub.status = SubscriptionStatus.ACTIVE
    else:
        sub = Subscription(user_id=user_id, type=sub_type, ended_at=ended_at)
        session.add(sub)
    session.flush()
    return sub


def add_payment(
    session,
    user_id: int,
    days: int,
    total_amount: int = 0,
    telegram_charge_id: str | None = None,
    provider_charge_id: str | None = None,
    currency: str | None = None,
    provider: str | None = None,
    refund_for_id: int | None = None,
) -> Payment:
    """Добавляет финансовую запись. total_amount — рубли (Robokassa) или звёзды (Stars)."""
    payment = Payment(
        user_id=user_id,
        days=days,
        total_amount=total_amount,
        telegram_charge_id=telegram_charge_id,
        provider_charge_id=provider_charge_id,
        currency=currency,
        provider=provider,
        refund_for_id=refund_for_id,
        created_at=utc_now_naive(),
    )
    session.add(payment)
    session.flush()

    if total_amount < 0 or days < 0:
        kind = "refund"
    elif total_amount == 0:
        kind = "trial"
    else:
        kind = "paid"
    counter_inc(
        "fivekcal_payment_records_total",
        labels={"kind": kind, "provider": provider or "none"},
        help="Payment records created by kind and provider",
    )
    # Counter должен быть монотонным: суммы возвратов копим отдельным счётчиком
    amount_labels = {"currency": currency or "none", "provider": provider or "none"}
    if total_amount > 0:
        counter_inc(
            "fivekcal_payment_amount_total",
            labels=amount_labels,
            amount=float(total_amount),
            help="Total amount received, in payment currency units",
        )
    elif total_amount < 0:
        counter_inc(
            "fivekcal_refund_amount_total",
            labels=amount_labels,
            amount=float(-total_amount),
            help="Total amount refunded, in payment currency units",
        )
    return payment


def add_meal_analysis_log(
    session,
    user_id: int,
    call_type: str,
    model: str | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    cached_tokens: int | None = None,
    duration_ms: int | None = None,
    call_source: str = "ai",
) -> MealAnalysisLog:
    """Записывает usage LLM-вызова (для рейтинга расхода токенов по пользователям)."""
    log = MealAnalysisLog(
        user_id=user_id,
        call_type=call_type,
        call_source=call_source,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cached_tokens=cached_tokens,
        duration_ms=duration_ms,
        created_at=utc_now_naive(),
    )
    session.add(log)
    session.flush()
    return log


def add_subscription_event(
    session,
    user_id: int,
    event: str,
    payment_id: int | None = None,
    admin_id: int | None = None,
) -> SubscriptionEvent:
    """Записывает событие подписки в аудит-лог."""
    evt = SubscriptionEvent(
        user_id=user_id,
        payment_id=payment_id,
        event=event,
        admin_id=admin_id,
        created_at=utc_now_naive(),
    )
    session.add(evt)
    session.flush()
    return evt


def add_event(
    session,
    user_id: int,
    event_type: str,
    payload: dict | None = None,
) -> UserEvent:
    """Записывает событие воронки. Зеркало add_subscription_event: add + flush,
    БЕЗ commit (commit делает Database.session на выходе)."""
    evt = UserEvent(
        user_id=user_id,
        event_type=event_type,
        payload=payload,
        created_at=utc_now_naive(),
    )
    session.add(evt)
    session.flush()
    return evt


def has_used_trial(session, user_id: int) -> bool:
    """Проверяет, использовал ли пользователь пробную подписку.

    Триал: бесплатная запись с provider NULL (легаси) или 'trial'.
    Админ-подарки дней (provider='admin') триал не сжигают."""
    from sqlalchemy import or_

    return (
        session.query(Payment)
        .filter(
            Payment.user_id == user_id,
            Payment.days > 0,
            Payment.total_amount == 0,
            or_(Payment.provider.is_(None), Payment.provider == "trial"),
        )
        .first()
        is not None
    )


def get_user_events(session, user_id: int) -> List[SubscriptionEvent]:
    """Возвращает события подписки пользователя, новые первыми."""
    return (
        session.query(SubscriptionEvent)
        .filter(SubscriptionEvent.user_id == user_id)
        .order_by(SubscriptionEvent.created_at.desc())
        .all()
    )


def get_user_payments(session, user_id: int) -> List[Payment]:
    """Возвращает историю платежей пользователя, новые первыми."""
    return (
        session.query(Payment)
        .filter(Payment.user_id == user_id)
        .order_by(Payment.created_at.desc())
        .all()
    )


def get_payment_by_provider_charge(
    session, provider: str, provider_charge_id: str
) -> Optional[Payment]:
    """Ищет платёж по идентификатору у платёжного провайдера (durable-идемпотентность)."""
    return (
        session.query(Payment)
        .filter(
            Payment.provider == provider,
            Payment.provider_charge_id == provider_charge_id,
        )
        .first()
    )


def get_max_robokassa_inv_id(session) -> int:
    """Максимальный InvId среди платежей Robokassa (provider_charge_id — строка)."""
    rows = (
        session.query(Payment.provider_charge_id)
        .filter(
            Payment.provider == "robokassa",
            Payment.provider_charge_id.isnot(None),
        )
        .all()
    )
    max_inv = 0
    for (raw,) in rows:
        try:
            max_inv = max(max_inv, int(raw))
        except (TypeError, ValueError):
            continue
    return max_inv


def get_payment_by_telegram_charge(
    session, telegram_charge_id: str
) -> Optional[Payment]:
    """Ищет платёж по telegram_payment_charge_id (дедупликация Stars-оплат)."""
    return (
        session.query(Payment)
        .filter(Payment.telegram_charge_id == telegram_charge_id)
        .first()
    )


def cancel_subscription(session, user_id: int, now: datetime) -> bool:
    """Отменяет подписку (ended_at = now)."""
    sub = session.query(Subscription).filter(Subscription.user_id == user_id).first()
    if not sub:
        return False
    sub.type = SubscriptionType.NONE
    sub.status = SubscriptionStatus.CANCELLED
    sub.ended_at = now
    add_subscription_event(session, user_id, "cancel")
    session.flush()
    return True


def grant_unlimited(session, user_id: int) -> None:
    """Выдаёт безлимитную подписку (создаёт или обновляет)."""
    sub = session.query(Subscription).filter(Subscription.user_id == user_id).first()
    ended_at = datetime(2099, 12, 31, 23, 59, 59)
    if sub:
        sub.type = SubscriptionType.UNLIMITED
        sub.status = SubscriptionStatus.ACTIVE
        sub.ended_at = ended_at
    else:
        sub = Subscription(
            user_id=user_id,
            type=SubscriptionType.UNLIMITED,
            status=SubscriptionStatus.ACTIVE,
            ended_at=ended_at,
        )
        session.add(sub)
    add_subscription_event(session, user_id, "grant_unlimited")
    session.flush()


def get_subscriptions_expiring_in(session, days: int) -> List[Subscription]:
    """Возвращает подписки, истекающие через `days` локальных дней пользователя."""
    subs = (
        session.query(Subscription)
        .join(User, Subscription.user_id == User.user_id)
        .filter(Subscription.type != SubscriptionType.UNLIMITED)
        .filter(Subscription.status == SubscriptionStatus.ACTIVE)
        .all()
    )

    expiring: list[Subscription] = []
    for sub in subs:
        user_tz = sub.user.timezone if sub.user and sub.user.timezone else "UTC"
        target_date = today_for_tz(user_tz) + timedelta(days=days)
        if date_in_tz(sub.ended_at, user_tz) == target_date:
            expiring.append(sub)

    return expiring


def expire_due_subscriptions(session) -> list[tuple[int, SubscriptionType]]:
    """Помечает истёкшие ACTIVE подписки как CANCELLED (churn-свип).

    Возвращает (user_id, type) тех, кого пометили в ЭТОТ вызов (для эмита события
    с типом — trial-churn vs paid-churn).

    Атомарный UPDATE … RETURNING (SQLAlchemy Core): flip и выбор «кого свипнули»
    — один statement. Строка, чей ended_at только что подняли в будущее
    (re-subscription), не попадёт под WHERE и не будет затёрта; два параллельных
    свипа не дадут двойной эмит одного user_id. Идемпотентно: уже-CANCELLED под
    WHERE не попадают. Фильтр по type — ТОЛЬКО TRIAL и PAID: так payload {type}
    строго 'trial'|'paid' (контракт churn-сплита), а NONE (уже отменённая с
    прошедшим ended_at) и UNLIMITED не попадают — иначе был бы мусорный бакет
    'none'. Enum-члены передаём объектами — SQLAlchemy биндит имя члена
    ('TRIAL'/'PAID'/'CANCELLED'), как хранят колонки; RETURNING отдаёт type
    обратно как SubscriptionType.
    """
    now = utc_now_naive()
    rows = session.execute(
        update(Subscription)
        .where(
            Subscription.status == SubscriptionStatus.ACTIVE,
            Subscription.type.in_((SubscriptionType.TRIAL, SubscriptionType.PAID)),
            Subscription.ended_at < now,
        )
        .values(status=SubscriptionStatus.CANCELLED)
        .returning(Subscription.user_id, Subscription.type)
    ).fetchall()
    return [(r[0], r[1]) for r in rows]


def meal_to_model(meal: Meal):
    """Конвертирует DB Meal в Pydantic MealModel.
    Вызывать ВНУТРИ сессии (до истечения сессии/commit + expiry).
    """
    from src.core.llm.meal_model import Meal as MealModel, MealComponent

    return MealModel(
        name=meal.name or "",
        emoji=meal.emoji or "",
        count=meal.count or 1,
        estimated_weight_g=meal.weight_g or 0,
        calories_kcal=meal.calories_kcal or 0,
        protein_g=meal.protein_g or 0,
        fat_g=meal.fat_g or 0,
        carbs_g=meal.carbs_g or 0,
        confidence=meal.confidence if meal.confidence is not None else 15,
        confidence_reason=meal.confidence_reason or "",
        components=[MealComponent(**c) for c in (meal.components or [])],
    )


def count_user_meals(session, user_id: int) -> int:
    """Число сохранённых блюд юзера — критерий активации для онбординга."""
    return session.query(Meal).filter(Meal.user_id == user_id).count()


def save_meal_data(
    session,
    user_id: int,
    meal_model,
    caption: str,
    message_id: int,
    timezone: Optional[str] = None,
    telegram_file_id: Optional[str] = None,
    photo_file_ids: Optional[list[str]] = None,
) -> Meal:
    """Сохраняет блюдо в БД после получения ответа ИИ и отправки карточки в Telegram."""
    meal = Meal(
        user_id=user_id,
        photo_file_ids=photo_file_ids,
        caption=caption,
        message_id=message_id,
        telegram_file_id=telegram_file_id,
        timezone=timezone,
        name=meal_model.name,
        emoji=meal_model.emoji,
        count=meal_model.count,
        weight_g=meal_model.estimated_weight_g,
        calories_kcal=meal_model.calories_kcal,
        protein_g=meal_model.protein_g,
        fat_g=meal_model.fat_g,
        carbs_g=meal_model.carbs_g,
        confidence=meal_model.confidence,
        confidence_reason=meal_model.confidence_reason,
        components=[c.model_dump() for c in meal_model.components],
    )
    session.add(meal)
    session.flush()
    counter_inc(
        "fivekcal_meals_saved_total",
        help="Total meals saved to database",
    )
    link_analysis_logs_to_meal(session, user_id, meal.id)
    return meal


def link_analysis_logs_to_meal(session, user_id: int, meal_id: int) -> None:
    """Привязывает недавние usage-логи LLM пользователя к сохранённому блюду.

    Точной связи нет (логи пишутся до создания Meal), поэтому эвристика:
    непривязанные логи пользователя за последние 30 минут. Бот не даёт
    запустить второй анализ параллельно, так что коллизии маловероятны.
    """
    cutoff = utc_now_naive() - timedelta(minutes=30)
    session.query(MealAnalysisLog).filter(
        MealAnalysisLog.user_id == user_id,
        MealAnalysisLog.meal_id.is_(None),
        MealAnalysisLog.created_at >= cutoff,
    ).update({MealAnalysisLog.meal_id: meal_id}, synchronize_session=False)


def _meal_query(session, meal_id: int, user_id: Optional[int] = None):
    """Запрос блюда по ID с опциональной проверкой владельца.

    meal_id приходит из callback data и может быть подделан — хендлеры обязаны
    передавать user_id, чтобы нельзя было трогать чужие блюда (anti-IDOR).
    """
    query = session.query(Meal).filter(Meal.id == meal_id)
    if user_id is not None:
        query = query.filter(Meal.user_id == user_id)
    return query


def get_meal(session, meal_id: int, user_id: Optional[int] = None) -> Optional[Meal]:
    """
    Получает данные о питании по ID.

    Args:
        session: Сессия базы данных
        meal_id: ID питания
        user_id: владелец блюда (если задан — чужое блюдо не вернётся)
    """
    return _meal_query(session, meal_id, user_id).first()


def get_user_language(session, chat_id: int) -> str | None:
    """Возвращает язык интерфейса пользователя или None если не задан вручную."""
    user = session.query(User).filter(User.user_id == chat_id).first()
    return user.language if user else None


def set_user_language(session, chat_id: int, language: str) -> bool:
    """Сохраняет язык интерфейса пользователя.
    Возвращает False, если пользователь не найден (запись не произошла)."""
    user = session.query(User).filter(User.user_id == chat_id).first()
    if user is None:
        return False
    user.language = language
    return True


def get_user_show_xe(session, chat_id: int) -> bool:
    """True если пользователь включил показ ХЕ. False если выключено или юзера нет."""
    user = session.query(User).filter(User.user_id == chat_id).first()
    return bool(user.show_xe) if user else False


def set_user_show_xe(session, chat_id: int, show_xe: bool) -> bool:
    """Сохраняет флаг показа ХЕ.
    Возвращает False, если пользователь не найден (запись не произошла)."""
    user = session.query(User).filter(User.user_id == chat_id).first()
    if user is None:
        return False
    user.show_xe = show_xe
    return True


def get_user_goal(session, chat_id: int) -> int | None:
    """Возвращает дневную цель по калориям или None если не задана."""
    user = session.query(User).filter(User.user_id == chat_id).first()
    return user.daily_calorie_target if user else None


def set_user_goal(session, chat_id: int, goal: int | None) -> None:
    """Сохраняет дневную цель по калориям (None = сброс).
    Если пользователь не найден — тихо игнорируется."""
    user = session.query(User).filter(User.user_id == chat_id).first()
    if user:
        user.daily_calorie_target = goal


def _is_tz_confirmed(user, default_timezone: str) -> bool:
    """Подтверждение timezone: явный выбор пользователя или отличный от дефолта пояс."""
    return bool(user.timezone_confirmed) or user.timezone != default_timezone


def get_user_created_at(session, user_id: int):
    """Дата регистрации пользователя (naive UTC) или None, если юзера нет."""
    user = session.query(User).filter(User.user_id == user_id).first()
    return user.created_at if user else None


def get_user_timezone(
    session, chat_id: int, default_timezone: str = "UTC"
) -> tuple[str, bool]:
    """Возвращает (timezone, confirmed). confirmed=True если пользователь выбрал пояс вручную."""
    user = session.query(User).filter(User.user_id == chat_id).first()
    if not user:
        return default_timezone, False
    return user.timezone, _is_tz_confirmed(user, default_timezone)


def set_user_timezone(session, chat_id: int, timezone: str) -> bool:
    """Сохраняет timezone пользователя.
    Возвращает False, если пользователь не найден (запись не произошла)."""
    user = session.query(User).filter(User.user_id == chat_id).first()
    if user is None:
        return False
    user.timezone = timezone
    user.timezone_confirmed = 1
    return True


def claim_tz_prompt(session, chat_id: int, default_timezone: str = "UTC") -> bool:
    """Возвращает True если нужно показать промпт выбора timezone.

    - 0 показов + UTC → показать после первого анализа
    - 1 показ + UTC → показать после 15-го блюда
    - пояс выбран или уже 2 показа → не показывать
    """
    user = session.query(User).filter(User.user_id == chat_id).first()
    if not user or _is_tz_confirmed(user, default_timezone):
        return False
    count = user.timezone_prompt_count or 0
    if count == 0:
        should_show = True
    elif count == 1:
        meal_count = session.query(Meal).filter(Meal.user_id == chat_id).count()
        should_show = meal_count >= 15
    else:
        should_show = False
    if should_show:
        user.timezone_prompt_count = count + 1
    return should_show


def update_meal_data(
    session, meal_id: int, meal_model, user_id: Optional[int] = None
) -> None:
    meal = _meal_query(session, meal_id, user_id).first()
    if meal is None:
        raise ValueError(f"Meal {meal_id} not found")
    meal.name = meal_model.name
    meal.emoji = meal_model.emoji
    meal.count = meal_model.count
    meal.weight_g = meal_model.estimated_weight_g
    meal.calories_kcal = meal_model.calories_kcal
    meal.protein_g = meal_model.protein_g
    meal.fat_g = meal_model.fat_g
    meal.carbs_g = meal_model.carbs_g
    meal.confidence = meal_model.confidence
    meal.confidence_reason = meal_model.confidence_reason
    meal.components = [c.model_dump() for c in meal_model.components]


def update_meal_message_id(
    session, meal_id: int, message_id: int, telegram_file_id: Optional[str] = None
) -> None:
    meal = session.query(Meal).filter(Meal.id == meal_id).first()
    if meal is None:
        raise ValueError(f"Meal {meal_id} not found")
    meal.message_id = message_id
    if telegram_file_id is not None:
        meal.telegram_file_id = telegram_file_id


def update_meal_date(
    session,
    meal_id: int,
    new_date: date,
    tz_name: str = "UTC",
    user_id: Optional[int] = None,
) -> None:
    meal = _meal_query(session, meal_id, user_id).first()
    if meal is None:
        raise ValueError(f"Meal {meal_id} not found")
    meal.created_at = local_date_to_utc_naive(new_date, tz_name, hour=12)


def delete_meal(session, meal_id: int, user_id: Optional[int] = None) -> bool:
    """
    Удаляет данные о питании по ID. Возвращает True, если блюдо было удалено.

    Args:
        session: Сессия базы данных
        meal_id: ID питания
        user_id: владелец блюда (если задан — чужое блюдо не удалится)
    """
    return _meal_query(session, meal_id, user_id).delete() > 0


def get_meals_for_daterange(
    session, user_id: int, start_dt: datetime, end_dt: datetime
) -> List[Meal]:
    """Возвращает все блюда пользователя за указанный диапазон дат (start_dt включительно, end_dt не включается).
    Исключённые из статистики блюда (excluded=True) не возвращаются."""
    return (
        session.query(Meal)
        .filter(Meal.user_id == user_id)
        .filter(Meal.created_at >= start_dt)
        .filter(Meal.created_at < end_dt)
        .filter(Meal.excluded == False)  # noqa: E712
        .order_by(Meal.created_at)
        .all()
    )


def get_user_first_meal_date(session, user_id: int) -> Optional[datetime]:
    """Возвращает дату первого блюда пользователя или None если блюд нет."""
    meal = (
        session.query(Meal)
        .filter(Meal.user_id == user_id)
        .order_by(Meal.created_at)
        .first()
    )
    return meal.created_at if meal else None


# ---------- Repeat Meal Operations ----------


def _scale_components(
    components: Optional[list[dict]], ratio: float
) -> Optional[list[dict]]:
    """Масштабирует точечный вес/КБЖУ компонентов пропорционально изменению порции."""
    if not components:
        return components
    keys = ("weight_g", "calories_kcal", "protein_g", "fat_g", "carbs_g")
    return [
        {**c, **{k: round((c.get(k, 0) or 0) * ratio, 1) for k in keys}}
        for c in components
    ]


def copy_meal(session, meal_id: int, user_id: int) -> Optional[Meal]:
    """Создаёт копию блюда с count=1 (одна порция) и текущим временем.

    Копировать можно только собственное блюдо (user_id — и владелец, и получатель)."""
    source = _meal_query(session, meal_id, user_id).first()
    if source is None:
        return None
    ratio = 1 / (source.count or 1)
    new_meal = Meal(
        user_id=user_id,
        photo_file_ids=source.photo_file_ids,
        caption=None,
        message_id=0,
        name=source.name,
        emoji=source.emoji,
        count=1,
        weight_g=(source.weight_g or 0) * ratio,
        calories_kcal=(source.calories_kcal or 0) * ratio,
        protein_g=(source.protein_g or 0) * ratio,
        fat_g=(source.fat_g or 0) * ratio,
        carbs_g=(source.carbs_g or 0) * ratio,
        confidence=source.confidence,
        confidence_reason=source.confidence_reason,
        telegram_file_id=source.telegram_file_id,
        components=_scale_components(source.components, ratio),
        excluded=source.excluded,  # копия наследует статус: «Повторить» демо-блюда
        # (excluded=True) не должно заносить фейковые числа в реальную статистику.
    )
    session.add(new_meal)
    session.flush()
    return new_meal


def update_meal_count(session, meal_id: int, delta: int, user_id: Optional[int] = None):
    """Изменяет count блюда на delta, пересчитывает КБЖУ пропорционально.
    Минимум 1 порция — удаление блюда только явной кнопкой (delete_meal).
    Возвращает (meal, changed): changed=False если count упёрся в минимум."""
    meal = _meal_query(session, meal_id, user_id).first()
    if meal is None:
        return None, False

    current_count = meal.count or 1
    new_count = current_count + delta

    if new_count < 1:
        return meal, False

    ratio = new_count / current_count
    meal.count = new_count
    meal.weight_g = (meal.weight_g or 0) * ratio
    meal.calories_kcal = (meal.calories_kcal or 0) * ratio
    meal.protein_g = (meal.protein_g or 0) * ratio
    meal.fat_g = (meal.fat_g or 0) * ratio
    meal.carbs_g = (meal.carbs_g or 0) * ratio
    meal.components = _scale_components(meal.components, ratio)
    session.flush()
    return meal, True


def toggle_meal_excluded(
    session, meal_id: int, user_id: Optional[int] = None
) -> Optional[bool]:
    """Переключает excluded-флаг блюда. Возвращает новое значение или None если блюдо не найдено."""
    meal = _meal_query(session, meal_id, user_id).first()
    if meal is None:
        return None
    meal.excluded = not meal.excluded
    session.flush()
    return meal.excluded


# ---------- Barcode Cache ----------


def get_barcode_cache(session, barcode: str) -> Optional[BarcodeCache]:
    return session.query(BarcodeCache).filter(BarcodeCache.barcode == barcode).first()


def save_barcode_cache(
    session,
    barcode: str,
    name: str,
    brand: Optional[str],
    source: str,
    nutrition_raw: str = "",
) -> BarcodeCache:
    """Upsert: создаёт или обновляет кэш штрихкода."""
    cache = session.query(BarcodeCache).filter(BarcodeCache.barcode == barcode).first()
    if cache:
        cache.name = name
        cache.brand = brand
        cache.source = source
        cache.nutrition_raw = nutrition_raw
    else:
        cache = BarcodeCache(
            barcode=barcode,
            name=name,
            brand=brand,
            source=source,
            nutrition_raw=nutrition_raw,
        )
        session.add(cache)
    session.flush()
    return cache
