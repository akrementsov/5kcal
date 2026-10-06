"""
Реестры ftl-ключей для всех user-facing строк.

Значения — ключи из locales/{locale}/LC_MESSAGES/bot.ftl.
Используются как: i18n.get(Btn.MENU), i18n.get(Msg.LOADING_STEP_1), и т.д.
"""


class Btn:
    # Постоянная reply-клавиатура
    REPLY_MENU = "btn-reply-menu"
    REPLY_HOWTO = "btn-reply-howto"

    # Навигация
    MENU = "btn-menu"
    BACK = "btn-back"
    STATS = "btn-stats"
    CHARTS = "btn-charts"
    ABOUT = "btn-about"
    ABOUT_WHAT = "btn-about-what"
    ABOUT_PHOTO = "btn-about-photo"
    ABOUT_ACCURACY = "btn-about-accuracy"
    ABOUT_LEGAL = "btn-about-legal"
    ABOUT_ACCURACY_MORE = "btn-about-accuracy-more"
    SUPPORT = "btn-support"
    SUBSCRIPTION = "btn-subscription"
    LANGUAGE = "btn-language"
    # Блюда
    EDIT_MEAL = "btn-edit-meal"
    DELETE_MEAL = "btn-delete-meal"
    CHANGE_DATE = "btn-change-date"
    REPEAT_MEAL = "btn-repeat-meal"
    CANCEL_EDITING = "btn-cancel-editing"
    CONTINUE_EDITING = "btn-continue-editing"
    CLARIFY_PROCEED = "btn-clarify-proceed"
    CLARIFY_CANCEL = "btn-clarify-cancel"
    EXCLUDE_FROM_STATS = "btn-exclude-from-stats"
    INCLUDE_IN_STATS = "btn-include-in-stats"
    # Подписка
    RENEW = "btn-renew"
    BUY = "btn-buy"
    PAYMENT_HISTORY = "btn-payment-history"
    REFUND_POLICY = "btn-refund-policy"
    TERMS_OF_SERVICE = "btn-terms-of-service"
    PERIOD_30D = "btn-period-30d"
    PERIOD_90D = "btn-period-90d"
    PERIOD_180D = "btn-period-180d"
    PERIOD_365D = "btn-period-365d"
    PAY_CARD = "btn-pay-card"
    PAY_STARS = "btn-pay-stars"
    # Языки
    LANG_RU = "btn-lang-ru"
    LANG_EN = "btn-lang-en"
    # Timezone
    TIMEZONE = "btn-timezone"
    TZ_OTHER = "btn-tz-other"
    # ХЕ (хлебные единицы, для диабетиков) — кнопка-переключатель в меню,
    # метка отражает состояние: XE_ON = показываются, XE_OFF = скрыты.
    XE_ON = "btn-xe-on"
    XE_OFF = "btn-xe-off"
    # История
    HISTORY_PREV_WEEK = "btn-history-prev-week"
    HISTORY_NEXT_WEEK = "btn-history-next-week"
    HISTORY_PREV_DAY = "btn-history-prev-day"
    HISTORY_NEXT_DAY = "btn-history-next-day"
    HISTORY_SHOW_CARD = "btn-history-show-card"
    # Онбординг-демо
    TRY_DEMO = "btn-try-demo"


class Msg:
    # Баркод
    BARCODE_NOT_FOUND = "msg-barcode-not-found"
    # Загрузка (степы анимации)
    LOADING_STEP_1 = "msg-loading-step-1"
    LOADING_STEP_2 = "msg-loading-step-2"
    LOADING_STEP_3 = "msg-loading-step-3"
    LOADING_STEP_4 = "msg-loading-step-4"
    LOADING_STEP_5 = "msg-loading-step-5"
    LOADING_STEP_6 = "msg-loading-step-6"
    LOADING_STEP_7 = "msg-loading-step-7"
    LOADING_STEP_8 = "msg-loading-step-8"
    LOADING_STEP_9 = "msg-loading-step-9"
    LOADING_STEP_10 = "msg-loading-step-10"
    LOADING_STEP_11 = "msg-loading-step-11"
    ALREADY_ANALYZING = "msg-already-analyzing"
    DAILY_LIMIT_REACHED = "msg-daily-limit-reached"
    # Уточняющие вопросы (V2 clarification)
    CLARIFICATION = "msg-clarification"
    CLARIFICATION_CANCELLED = "msg-clarification-cancelled"
    # Шаблоны (передают $text)
    ERROR = "msg-error"
    # Меню
    MENU = "msg-menu"
    # Стартовый экран
    GREETING = "msg-greeting"
    START_UNLIMITED = "msg-start-unlimited"
    START_TRIAL_ACTIVE = "msg-start-trial-active"
    START_EXPIRING = "msg-start-expiring"
    START_ACTIVE = "msg-start-active"

    SUBSCRIPTION_EXPIRED = "msg-subscription-expired"
    SUBSCRIPTION_EXPIRED_BLOCK = "msg-subscription-expired-block"
    BANNED = "msg-banned"
    SUBSCRIPTION_ENDS_TOMORROW = "msg-subscription-ends-tomorrow"
    FALLBACK = "msg-fallback"
    ABOUT = "msg-about"
    ABOUT_WHAT = "msg-about-what"
    ABOUT_PHOTO = "msg-about-photo"
    ABOUT_ACCURACY = "msg-about-accuracy"
    ABOUT_ACCURACY_LINK = "link-about-accuracy"
    ABOUT_LEGAL = "msg-about-legal"
    ABOUT_PHOTO_GALLERY_INTRO = "cap-photo-gallery-intro"
    CAP_PHOTO_GOOD_1 = "cap-photo-good-1"
    CAP_PHOTO_GOOD_2 = "cap-photo-good-2"
    CAP_PHOTO_GOOD_3 = "cap-photo-good-3"
    CAP_PHOTO_GOOD_4 = "cap-photo-good-4"
    CAP_PHOTO_GOOD_5 = "cap-photo-good-5"
    CAP_PHOTO_BAD_1 = "cap-photo-bad-1"
    CAP_PHOTO_BAD_2 = "cap-photo-bad-2"
    CAP_PHOTO_BAD_3 = "cap-photo-bad-3"
    CAP_PHOTO_BAD_4 = "cap-photo-bad-4"
    # Блюда
    MEAL_EDIT_PROMPT = "msg-meal-edit-prompt"
    MEAL_EDITED = "msg-meal-edited"
    MEAL_DELETED = "msg-meal-deleted"
    MEAL_REPEATED = "msg-meal-repeated"
    MEAL_DATE_PICKER = "msg-meal-date-picker"
    MEAL_DATE_CHANGED = "msg-meal-date-changed"
    MEAL_DATE_TOO_OLD = "msg-meal-date-too-old"
    # Короткие метки макросов
    LBL_PROTEIN = "lbl-protein"
    LBL_FAT = "lbl-fat"
    LBL_CARBS = "lbl-carbs"
    # Общие метки
    LBL_KCAL = "lbl-kcal"
    LBL_TODAY = "lbl-today"
    LBL_YESTERDAY = "lbl-yesterday"
    LBL_DAY_BEFORE_YESTERDAY = "lbl-day-before-yesterday"
    LBL_GRAMS = "lbl-grams"
    LBL_PORTIONS = "lbl-portions"
    PORTION_MIN = "msg-portion-min"
    PORTION_HINT = "msg-portion-hint"
    LBL_WEEKDAYS_SHORT = "lbl-weekdays-short"
    LBL_WEEKDAYS_FULL = "lbl-weekdays-full"
    LBL_MONTHS_GEN = "lbl-months-gen"
    LBL_COMPOSITION = "lbl-composition"
    LBL_XE = "lbl-xe"
    # История
    HISTORY_MEAL_REPLY = "msg-history-meal-reply"
    HISTORY_NO_MEALS = "msg-history-no-meals"
    HISTORY_NO_MEALS_WEEK = "msg-history-no-meals-week"
    HISTORY_NO_MEALS_DAY = "msg-history-no-meals-day"
    HISTORY_WEEK_HEADER = "msg-history-week-header"
    HISTORY_DAY_HEADER = "msg-history-day-header"
    HISTORY_TOTAL_WEEK = "msg-history-total-week"
    HISTORY_TOTAL_DAY = "msg-history-total-day"
    # Подписка
    SUB_SCREEN_TITLE = "msg-sub-screen-title"
    SUB_INFO_TRIAL = "msg-sub-info-trial"  # $date
    SUB_INFO_PAID = "msg-sub-info-paid"  # $date
    SUB_INFO_UNLIMITED = "msg-sub-info-unlimited"
    SUB_INFO_NONE = "msg-sub-info-none"
    # Уведомления об изменении подписки
    SUB_NOTIFY_CANCELLED = "msg-sub-notify-cancelled"
    SUB_NOTIFY_UNLIMITED = "msg-sub-notify-unlimited"
    SUB_NOTIFY_EXTENDED = "msg-sub-notify-extended"  # $days $date
    # Язык
    LANGUAGE_SELECT = "msg-language-select"
    LANGUAGE_SAVED = "msg-language-saved"
    # Timezone
    TIMEZONE_SELECT = "msg-timezone-select"
    TIMEZONE_CURRENT = "msg-timezone-current"
    TIMEZONE_SAVED = "msg-timezone-saved"
    TIMEZONE_ASK = "msg-timezone-ask"
    # Экран оформления подписки
    SUBSCRIBE_TITLE = "msg-subscribe-title"
    SUBSCRIBE_CHOOSE = "msg-subscribe-choose"
    SUBSCRIBE_TIP = "msg-subscribe-tip"
    SUBSCRIBE_PRICES = "msg-subscribe-prices"  # $p30 $s30 $p90 $s90 $p90m $p180 $s180 $p180m $p365 $s365 $p365m
    PAYMENT_METHOD_TITLE = "msg-payment-method-title"  # $days
    PAYMENT_METHOD_CHOOSE = "msg-payment-method-choose"
    PAYMENT_INVOICE_TITLE = "msg-payment-invoice-title"
    PAYMENT_INVOICE_DESCRIPTION = "msg-payment-invoice-description"  # $days
    PAYMENT_SUCCESS = "msg-payment-success"  # $days $date
    PAYMENT_UNAVAILABLE = "msg-payment-unavailable"
    ROBOKASSA_PAGE_SUCCESS_TITLE = "msg-robokassa-page-success-title"
    ROBOKASSA_PAGE_SUCCESS_TEXT = "msg-robokassa-page-success-text"
    ROBOKASSA_PAGE_FAIL_TITLE = "msg-robokassa-page-fail-title"
    ROBOKASSA_PAGE_FAIL_TEXT = "msg-robokassa-page-fail-text"
    ROBOKASSA_PAGE_OPEN_BOT = "msg-robokassa-page-open-bot"
    PAYMENT_HISTORY_TITLE = "msg-payment-history-title"
    PAYMENT_HISTORY_EMPTY = "msg-payment-history-empty"
    PAYMENT_HISTORY_REFUND = "msg-payment-history-refund"  # $days
    PAYMENT_HISTORY_TRIAL = "msg-payment-history-trial"  # $days
    PAYMENT_HISTORY_PAID = "msg-payment-history-paid"  # $days
    PAYMENT_REFUNDED = "msg-payment-refunded"  # $days $date
    # Сокращения месяцев (используются в date_picker и history/formatters)
    CHART_MONTHS_SHORT = "msg-chart-months-short"  # 12 сокращений через пробел
    # Онбординг-демо
    ONBOARDING_HERO_CAPTION = "msg-onboarding-hero-caption"
    ONBOARDING_HERO_CTA = "msg-onboarding-hero-cta"
    DEMO_PICKER = "msg-demo-picker"
    DEMO_UNAVAILABLE = "msg-demo-unavailable"


class Url:
    REFUND_POLICY = "url-refund-policy"
    TERMS_OF_SERVICE = "url-terms-of-service"


class Err:
    """Готовые ошибки хендлеров — уже содержат ❌, отправляются напрямую."""

    COMMAND = "err-command"
    CALLBACK = "err-callback"
    NAV = "err-nav"

    MEAL_NOT_FOUND = "err-meal-not-found"
    MEAL_DELETE_FAILED = "err-meal-delete-failed"
    MEAL_UPDATE_FAILED = "err-meal-update-failed"
    HISTORY_NO_ORIGINAL = "err-history-no-original"


class ErrSvc:
    """Сырые ключи из сервисного слоя — оборачиваются через Msg.ERROR + $text."""

    PHOTO_PROCESSING = "err-svc-photo-processing"
    LLM_CONNECTION = "err-svc-llm-connection"
    LLM_API = "err-svc-llm-api"
    LLM_PARSE = "err-svc-llm-parse"
    LLM_UNAVAILABLE = "err-svc-llm-unavailable"
    DB_SAVE = "err-svc-db-save"
    DB_READ = "err-svc-db-read"
    PHOTO_LOAD = "err-svc-photo-load"
    EXTRA_PHOTO = "err-svc-extra-photo"
    MEAL_NOT_RECOGNIZED = "err-svc-meal-not-recognized"
    MULTIPLE_DISHES = "err-svc-multiple-dishes"
    SESSION_EXPIRED = "err-svc-session-expired"
    MAX_ROUNDS = "err-svc-max-rounds"
    GENERAL = "err-svc-general"
