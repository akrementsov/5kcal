"""
Списки часовых поясов для выбора пользователем.

CIS_TIMEZONE_OPTIONS — основной экран (страны СНГ).
WORLD_TIMEZONE_OPTIONS — расширенный экран (весь мир от -11 до +13).

Второй элемент кортежа — ключ i18n из bot.ftl.
"""

# Первый экран: Россия + основные страны СНГ
CIS_TIMEZONE_OPTIONS: list[tuple[str, str]] = [
    ("Europe/Kaliningrad", "btn-tz-kaliningrad"),
    ("Europe/Moscow", "btn-tz-moscow"),
    ("Europe/Samara", "btn-tz-samara"),
    ("Asia/Yekaterinburg", "btn-tz-yekaterinburg"),
    ("Asia/Omsk", "btn-tz-omsk"),
    ("Asia/Krasnoyarsk", "btn-tz-krasnoyarsk"),
    ("Asia/Irkutsk", "btn-tz-irkutsk"),
    ("Asia/Yakutsk", "btn-tz-yakutsk"),
    ("Asia/Vladivostok", "btn-tz-vladivostok"),
    ("Asia/Magadan", "btn-tz-magadan"),
    ("Asia/Kamchatka", "btn-tz-kamchatka"),
]

# Второй экран: весь мир
WORLD_TIMEZONE_OPTIONS: list[tuple[str, str]] = [
    ("Pacific/Pago_Pago", "btn-tz-pago-pago"),
    ("Pacific/Honolulu", "btn-tz-honolulu"),
    ("America/Anchorage", "btn-tz-anchorage"),
    ("America/Los_Angeles", "btn-tz-los-angeles"),
    ("America/Denver", "btn-tz-denver"),
    ("America/Chicago", "btn-tz-chicago"),
    ("America/New_York", "btn-tz-new-york"),
    ("America/Halifax", "btn-tz-halifax"),
    ("America/Sao_Paulo", "btn-tz-sao-paulo"),
    ("Atlantic/Azores", "btn-tz-azores"),
    ("Europe/London", "btn-tz-london"),
    ("Europe/Paris", "btn-tz-paris"),
    ("Asia/Jerusalem", "btn-tz-tel-aviv"),
    ("Europe/Istanbul", "btn-tz-istanbul"),
    ("Asia/Tehran", "btn-tz-tehran"),
    ("Asia/Dubai", "btn-tz-dubai"),
    ("Asia/Kabul", "btn-tz-kabul"),
    ("Asia/Karachi", "btn-tz-karachi"),
    ("Asia/Kolkata", "btn-tz-delhi"),
    ("Asia/Kathmandu", "btn-tz-kathmandu"),
    ("Asia/Dhaka", "btn-tz-dhaka"),
    ("Asia/Yangon", "btn-tz-yangon"),
    ("Asia/Bangkok", "btn-tz-bangkok"),
    ("Asia/Shanghai", "btn-tz-shanghai"),
    ("Asia/Tokyo", "btn-tz-tokyo"),
    ("Australia/Adelaide", "btn-tz-adelaide"),
    ("Australia/Sydney", "btn-tz-sydney"),
    ("Pacific/Noumea", "btn-tz-noumea"),
    ("Pacific/Auckland", "btn-tz-auckland"),
    ("Pacific/Tongatapu", "btn-tz-nukualofa"),
]
