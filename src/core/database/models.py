from sqlalchemy import (
    Boolean,
    Column,
    Integer,
    BigInteger,
    String,
    Float,
    DateTime,
    ForeignKey,
    Enum,
    JSON,
    Index,
)
from sqlalchemy.orm import declarative_base, relationship
from datetime import datetime, timezone
import enum

# Базовый класс для моделей
Base = declarative_base()


def _utc_now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(Base):
    """
    Модель пользователя Telegram бота.

    Хранит основную информацию о пользователе и связи с его подписками и изображениями.
    """

    __tablename__ = "users"

    id = Column(Integer, primary_key=True, nullable=False)  # Внутренний ID записи
    user_id = Column(BigInteger, unique=True, nullable=False)  # Telegram user ID
    created_at = Column(
        DateTime, default=_utc_now_naive, nullable=False
    )  # Дата регистрации
    start_tag = Column(String, nullable=True)  # Реферальная метка при старте
    timezone = Column(
        String, default="UTC", nullable=False
    )  # Часовой пояс пользователя
    timezone_prompt_count = Column(
        Integer, default=0, nullable=False, server_default="0"
    )  # Сколько раз пользователю предлагали выбрать timezone
    timezone_confirmed = Column(
        Integer, default=0, nullable=False, server_default="0"
    )  # 1 если пользователь явно выбрал timezone
    language = Column(
        String, nullable=True
    )  # Язык интерфейса (ftl locale); None = не задан вручную, определяется по клиенту
    daily_calorie_target = Column(
        Integer, nullable=True
    )  # Дневная цель по калориям из Mini App; None = не задана
    show_xe = Column(
        Boolean, default=False, nullable=False, server_default="false"
    )  # Показывать ХЕ (хлебные единицы) в карточке — для диабетиков

    subscription = relationship("Subscription", back_populates="user", uselist=False)
    payments = relationship("Payment", back_populates="user")
    meals = relationship("Meal", back_populates="user")


class SubscriptionType(enum.Enum):
    """Типы подписок в системе."""

    NONE = "none"  # Нет подписки (отменена)
    TRIAL = "trial"  # Пробная подписка
    PAID = "paid"  # Платная подписка
    UNLIMITED = "unlimited"  # Безлимитная (не истекает)


class SubscriptionStatus(enum.Enum):
    """Статус подписки."""

    ACTIVE = "active"
    CANCELLED = "cancelled"


class Subscription(Base):
    """
    Текущая подписка пользователя. Одна строка на пользователя.
    История покупок хранится в таблице payments.
    """

    __tablename__ = "subscriptions"

    user_id = Column(BigInteger, ForeignKey("users.user_id"), primary_key=True)
    type = Column(Enum(SubscriptionType), nullable=False)
    status = Column(
        Enum(SubscriptionStatus), nullable=False, default=SubscriptionStatus.ACTIVE
    )
    ended_at = Column(DateTime, nullable=False)  # 23:59:59 последнего дня (naive UTC)

    user = relationship("User", back_populates="subscription")


class Payment(Base):
    """Финансовые операции: оплаты, триалы, возвраты."""

    __tablename__ = "payments"

    id = Column(Integer, primary_key=True)
    user_id = Column(
        BigInteger, ForeignKey("users.user_id"), nullable=False, index=True
    )
    days = Column(Integer, nullable=False)  # >0 оплата/триал, <0 возврат
    total_amount = Column(
        Integer, nullable=False, default=0
    )  # рубли (Robokassa) / звёзды (Stars) целиком; 0 для триала, <0 для возврата
    currency = Column(String, nullable=True)  # RUB, XTR
    provider = Column(String, nullable=True)  # robokassa, stars, admin, trial
    telegram_charge_id = Column(String, nullable=True)  # ID платежа в Telegram
    provider_charge_id = Column(String, nullable=True)  # ID платежа в провайдере
    refund_for_id = Column(
        Integer, ForeignKey("payments.id"), nullable=True
    )  # ссылка на оригинал (для возвратов)
    created_at = Column(DateTime, default=_utc_now_naive, nullable=False)

    user = relationship("User", back_populates="payments")
    refund_for = relationship("Payment", remote_side=[id])


class SubscriptionEvent(Base):
    """Аудит-лог событий подписки: отмена, грант безлимита."""

    __tablename__ = "subscription_events"

    id = Column(Integer, primary_key=True)
    user_id = Column(
        BigInteger, ForeignKey("users.user_id"), nullable=False, index=True
    )
    payment_id = Column(
        Integer, ForeignKey("payments.id"), nullable=True
    )  # к какой оплате относится
    event = Column(String, nullable=False)  # cancel, grant_unlimited
    admin_id = Column(BigInteger, nullable=True)  # кто выполнил (NULL если система)
    created_at = Column(DateTime, default=_utc_now_naive, nullable=False)


class UserEvent(Base):
    """Сквозной трекинг действий пользователя для воронок (funnel analytics).

    Одна строка на событие. event_type — свободная строка (константы в
    src/core/tracking/events.py, НЕ DB-enum). payload — только машинные
    значения (enum/int/bool/ref-tag), без пользовательского контента.
    """

    __tablename__ = "user_events"

    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, ForeignKey("users.user_id"), nullable=False)
    event_type = Column(String, nullable=False)
    payload = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=_utc_now_naive, nullable=False)

    __table_args__ = (
        Index("ix_user_events_user_id_created_at", "user_id", "created_at"),
        Index("ix_user_events_event_type_created_at", "event_type", "created_at"),
    )


class Meal(Base):
    """
    Модель приёма пищи: данные от OpenAI + фото + Telegram-сообщение.
    Сохраняется одной записью после получения ответа ИИ и отправки карточки пользователю.
    """

    __tablename__ = "meals"

    id = Column(Integer, primary_key=True)
    user_id = Column(
        BigInteger, ForeignKey("users.user_id"), nullable=False, index=True
    )
    photo_file_ids = Column(
        JSON, nullable=True
    )  # Telegram file_id оригинальных фото пользователя
    caption = Column(String, nullable=True)  # Подпись пользователя к фото
    message_id = Column(
        Integer, nullable=True
    )  # ID карточки в Telegram (NULL у старых записей)
    telegram_file_id = Column(
        String, nullable=True
    )  # file_id последней отправленной карточки
    timezone = Column(
        String, nullable=True
    )  # IANA timezone на момент создания (NULL у старых записей)
    created_at = Column(DateTime, default=_utc_now_naive, nullable=False, index=True)

    # Плоские колонки питания (замена meal_data JSON).
    # Хранится только точечное значение — диапазон для UI/графиков считается на лету
    # из value+confidence (см. build_range), min/max отдельно не хранятся.
    name = Column(String, nullable=True)
    emoji = Column(String, default="")
    count = Column(Integer, default=1)
    weight_g = Column(Float, nullable=True)
    calories_kcal = Column(Float, nullable=True)
    protein_g = Column(Float, nullable=True)
    fat_g = Column(Float, nullable=True)
    carbs_g = Column(Float, nullable=True)
    confidence = Column(Integer, default=15)
    confidence_reason = Column(String, default="")
    excluded = Column(Boolean, default=False, nullable=False)
    components = Column(JSON, nullable=True)  # список компонентов блюда (V2, Call 1+2)

    user = relationship("User", back_populates="meals")


class DemoExample(Base):
    """Статичный пример для онбординг-демо (фейковый анализ без LLM).

    5 строк засеиваются миграцией. Числа локале-независимы (на порцию),
    локализуется только название (name_ru/name_en). telegram_file_id —
    кэш file_id после первой отправки, чтобы не гонять байты каждый раз.
    """

    __tablename__ = "demo_examples"

    id = Column(Integer, primary_key=True)
    sort_order = Column(Integer, nullable=False)  # порядок в пикере (1..5); 1 — hero
    asset_filename = Column(String, nullable=False)  # имя файла в assets/demo/
    telegram_file_id = Column(String, nullable=True)  # кэш file_id (optimization)
    emoji = Column(String, default="")
    name_ru = Column(String, nullable=False)
    name_en = Column(String, nullable=False)
    calories_kcal = Column(Integer, nullable=False)  # на порцию
    protein_g = Column(Float, nullable=False)
    fat_g = Column(Float, nullable=False)
    carbs_g = Column(Float, nullable=False)
    count = Column(Integer, default=1, nullable=False)
    components = Column(
        JSON, nullable=True
    )  # список имён компонентов блюда (для «Состав:»)


class MealAnalysisLog(Base):
    """Лог каждого вызова OpenAI в двухвызовной архитектуре."""

    __tablename__ = "meal_analysis_logs"

    id = Column(Integer, primary_key=True)
    user_id = Column(
        BigInteger, ForeignKey("users.user_id"), nullable=False, index=True
    )
    meal_id = Column(
        Integer, ForeignKey("meals.id", ondelete="SET NULL"), nullable=True, index=True
    )  # NULL до сохранения Meal; SET NULL при удалении блюда (лог токенов остаётся)
    call_type = Column(String, nullable=False)  # "identification" | "weight"
    call_source = Column(String, nullable=False)  # "ai" | "barcode"
    model = Column(String, nullable=True)
    input_tokens = Column(Integer, nullable=True)
    output_tokens = Column(Integer, nullable=True)
    cached_tokens = Column(Integer, nullable=True)
    duration_ms = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=_utc_now_naive, nullable=False, index=True)


class BarcodeCache(Base):
    """Кэш результатов поиска штрихкодов в платных API (Dietagram, Barcode Lookup)."""

    __tablename__ = "barcode_cache"

    id = Column(Integer, primary_key=True)
    barcode = Column(String, nullable=False, unique=True, index=True)
    name = Column(String, nullable=False)
    brand = Column(String, nullable=True)
    source = Column(String, nullable=False)
    nutrition_raw = Column(String, default="")
    created_at = Column(DateTime, default=_utc_now_naive, nullable=False)
