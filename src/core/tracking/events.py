"""Константы event_type для user_events (funnel analytics).

event_type — свободная строка в БД (НЕ DB-enum). Значения стабильны:
их читают SQL-воронки и Grafana, менять существующие нельзя без миграции запросов.
"""

# --- Активация ---
START = "start"
ONBOARDING_HERO_SHOWN = "onboarding.hero_shown"
ONBOARDING_DEMO_SHOWN = "onboarding.demo_shown"
ONBOARDING_DEMO_PICKED = "onboarding.demo_picked"
PHOTO_RECEIVED = "photo.received"
ANALYSIS_STARTED = "analysis.started"
ANALYSIS_FAILED = "analysis.failed"
MEAL_SAVED = "meal.saved"

# --- Монетизация ---
PAYWALL_SHOWN = "paywall.shown"
TRIAL_STARTED = "trial.started"
PAYMENT_SUCCEEDED = "payment.succeeded"
SUBSCRIPTION_CANCELLED = "subscription.cancelled"
SUBSCRIPTION_EXPIRED = "subscription.expired"

# --- Удержание ---
NOTIFICATION_SENT = "notification.sent"
