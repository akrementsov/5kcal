from enum import StrEnum


class MainStates(StrEnum):
    menu = "nav:menu"
    start = "nav:start"

    stats = "nav:stats"
    about = "nav:about"
    about_what = "nav:about_what"
    about_photo = "nav:about_photo"
    about_accuracy = "nav:about_accuracy"
    about_legal = "nav:about_legal"
    back = "nav:back"


class SubscriptionStates(StrEnum):
    main = "sub:main"
    trial = "sub:trial"
    subscribe = "sub:subscribe"
    cancel = "sub:cancel"
    try_trial = "sub:try_trial"
    payment_method = "sub:payment_method"
    payment_history = "sub:payment_history"


class MealStates(StrEnum):
    editing = "meal:editing"
    end_editing = "meal:end_editing"
    clarify_proceed = "meal:clarify_proceed"
    clarify_cancel = "meal:clarify_cancel"


class LanguageStates(StrEnum):
    select = "lang:select"
    set_ru = "lang:set_ru"
    set_en = "lang:set_en"


class TimezoneStates(StrEnum):
    select = "tz:select"
    other = "tz:other"
    back_to_cis = "tz:back_cis"
