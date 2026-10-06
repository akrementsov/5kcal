"""
Robokassa webhook handlers — Result URL callback + Success/Fail страницы.

Регистрируются на aiohttp web.Application из main.py.
"""

from aiohttp import web

from src.core.utils import get_logger
from src.core.utils.admin_notify import format_sale, notify_admin
from src.core.ui.texts import Msg
from src.payment.robokassa import verify_result_signature
from src.features.subscription.payment_state import (
    get_robokassa_invoice,
    delete_robokassa_invoice,
    mark_robokassa_processed,
    unmark_robokassa_processed,
    is_robokassa_processed,
)
from src.core.database import db as db_funcs
from src.core.metrics import counter_inc
from src.i18n import get_i18n_core, DEFAULT_LOCALE, SUPPORTED_LOCALES

logger = get_logger()


def _count_payment(outcome: str) -> None:
    counter_inc(
        "fivekcal_payments_total",
        labels={"outcome": outcome},
        help="Robokassa payment callbacks by outcome",
    )


ROBOKASSA_ALLOWED_IPS = {"185.59.216.65", "185.59.217.65"}

_PAGE_HTML = """<!DOCTYPE html>
<html lang="{lang}">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{title}</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            display: flex; justify-content: center; align-items: center;
            min-height: 100vh; margin: 0; background: #f5f5f5;
        }}
        .card {{
            background: white; border-radius: 16px; padding: 40px;
            text-align: center; box-shadow: 0 2px 12px rgba(0,0,0,0.1);
            max-width: 400px;
        }}
        .icon {{ font-size: 64px; margin-bottom: 16px; }}
        h1 {{ font-size: 24px; margin: 0 0 8px; }}
        p {{ color: #666; margin: 0 0 24px; }}
        a {{
            display: inline-block; background: #2196F3; color: white;
            text-decoration: none; padding: 12px 32px; border-radius: 8px;
            font-size: 16px; font-weight: 500;
        }}
        a:hover {{ background: #1976D2; }}
    </style>
</head>
<body>
    <div class="card">
        <div class="icon">{icon}</div>
        <h1>{title}</h1>
        <p>{text}</p>
        <a href="https://t.me/{bot_username}">{open_bot}</a>
    </div>
</body>
</html>"""


def _get_client_ip(request: web.Request) -> str:
    """Получает реальный IP клиента (через X-Forwarded-For если за nginx)."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote or ""


def _extract_shp_params(data: dict) -> dict[str, str]:
    """Извлекает Shp_ параметры из данных запроса."""
    return {k: v for k, v in data.items() if k.startswith("Shp_")}


def _get_user_locale(db, user_id: int) -> str:
    with db.session() as session:
        lang = db_funcs.get_user_language(session, user_id)
    return lang if lang in SUPPORTED_LOCALES else DEFAULT_LOCALE


def _resolve_locale(request: web.Request) -> str:
    """Определяет locale по Shp_user_id из query params."""
    user_id_str = request.query.get("Shp_user_id", "")
    if user_id_str:
        try:
            db = request.app["robokassa_db"]
            return _get_user_locale(db, int(user_id_str))
        except Exception as e:
            logger.debug("Ошибка проигнорирована", extra={"error": str(e)})
    return DEFAULT_LOCALE


def register_robokassa_routes(app, bot, subscription_service, db, config) -> None:
    """Регистрирует routes /robokassa/* на aiohttp Application."""
    app["robokassa_bot"] = bot
    app["robokassa_subscription_service"] = subscription_service
    app["robokassa_db"] = db
    app["robokassa_config"] = config

    async def _init_bot_username(app_: web.Application):
        me = await bot.get_me()
        app_["robokassa_bot_username"] = me.username

    app.on_startup.append(_init_bot_username)

    app.router.add_post("/robokassa/result", _result_handler)
    app.router.add_get("/robokassa/result", _result_handler)
    app.router.add_get("/robokassa/success", _success_handler)
    app.router.add_get("/robokassa/fail", _fail_handler)


async def _result_handler(request: web.Request) -> web.Response:
    """Серверный callback от Robokassa — проверяет подпись, активирует подписку."""
    client_ip = _get_client_ip(request)
    if client_ip not in ROBOKASSA_ALLOWED_IPS:
        # INFO, не WARNING: сюда попадает штатный шум (сканеры, smoke-тесты),
        # алертить в админ-чат не нужно; всплеск виден по метрике forbidden_ip
        logger.info(
            "Robokassa callback с неразрешённого IP",
            extra={"ip": client_ip},
        )
        _count_payment("forbidden_ip")
        return web.Response(status=403, text="Forbidden")

    if request.method == "POST":
        data = dict(await request.post())
    else:
        data = dict(request.query)

    out_sum = data.get("OutSum", "")
    inv_id_str = data.get("InvId", "")
    signature = data.get("SignatureValue", "")
    shp_params = _extract_shp_params(data)

    if not out_sum or not inv_id_str or not signature:
        safe_fields = {
            k: v
            for k, v in data.items()
            if k in ("InvId", "OutSum", "IsTest", "Culture")
        }
        logger.warning(
            "Robokassa callback без обязательных параметров", extra=safe_fields
        )
        _count_payment("missing_params")
        return web.Response(status=400, text="Bad Request")

    try:
        inv_id = int(inv_id_str)
    except ValueError:
        _count_payment("missing_params")
        return web.Response(status=400, text="Bad Request")

    # Читаем инвойс БЕЗ удаления — валидируем сначала, удаляем после успеха
    invoice = await get_robokassa_invoice(inv_id)
    if invoice is None:
        return await _handle_missing_invoice(
            request, inv_id, out_sum, signature, shp_params
        )

    # Выбираем пароль (test или prod)
    config = request.app["robokassa_config"]
    if invoice.get("is_test"):
        password2 = config.robokassa_password2_test
    else:
        password2 = config.robokassa_password2

    if not password2 or not verify_result_signature(
        out_sum, inv_id, password2, signature, shp_params
    ):
        logger.warning(
            "Robokassa callback с невалидной подписью",
            extra={"inv_id": inv_id, "out_sum": out_sum},
        )
        _count_payment("invalid_signature")
        return web.Response(status=403, text="Invalid signature")

    user_id = invoice["user_id"]
    period = invoice["period"]
    expected_amount = invoice["amount"]

    try:
        received_amount = int(float(out_sum))
    except ValueError:
        received_amount = 0

    if received_amount != expected_amount:
        logger.warning(
            "Robokassa callback: сумма не совпадает",
            extra={
                "inv_id": inv_id,
                "expected": expected_amount,
                "received": received_amount,
            },
        )
        _count_payment("amount_mismatch")
        return web.Response(status=400, text="Amount mismatch")

    # Idempotency guard: SETNX гарантирует однократную активацию
    if not await mark_robokassa_processed(inv_id):
        logger.info(
            "Robokassa callback: уже обработан (concurrent)",
            extra={"inv_id": inv_id},
        )
        _count_payment("duplicate")
        return web.Response(text=f"OK{inv_id}")

    return await _activate_and_notify(
        request,
        inv_id=inv_id,
        user_id=user_id,
        period=period,
        amount=expected_amount,
        recovered=False,
    )


async def _handle_missing_invoice(
    request: web.Request,
    inv_id: int,
    out_sum: str,
    signature: str,
    shp_params: dict[str, str],
) -> web.Response:
    """Callback для InvId без инвойса в Redis: дубль уже обработанного платежа
    ИЛИ поздняя оплата по протухшему инвойсу (TTL 1ч, а ссылка в чате живёт вечно).

    Раньше здесь был безусловный OK — оплаченный после TTL платёж молча терялся.
    Shp_user_id/Shp_period подписаны, поэтому платёж можно восстановить."""
    db = request.app["robokassa_db"]

    # 1. Дубль: недавно обработан (done-ключ) или уже есть платёж в БД (durable)
    if await is_robokassa_processed(inv_id):
        logger.info(
            "Robokassa callback для уже обработанного InvId",
            extra={"inv_id": inv_id},
        )
        _count_payment("duplicate")
        return web.Response(text=f"OK{inv_id}")

    with db.session() as session:
        existing = db_funcs.get_payment_by_provider_charge(
            session, "robokassa", str(inv_id)
        )
    if existing is not None:
        logger.info(
            "Robokassa callback: платёж уже в БД (поздний дубль)",
            extra={"inv_id": inv_id},
        )
        _count_payment("duplicate")
        return web.Response(text=f"OK{inv_id}")

    # 2. Инвойса нет и платёж не записан — проверяем подпись (prod, затем test)
    config = request.app["robokassa_config"]
    if config.robokassa_password2 and verify_result_signature(
        out_sum, inv_id, config.robokassa_password2, signature, shp_params
    ):
        pass  # валидный боевой платёж — восстанавливаем ниже
    elif config.robokassa_password2_test and verify_result_signature(
        out_sum, inv_id, config.robokassa_password2_test, signature, shp_params
    ):
        logger.info(
            "Robokassa callback тестового платежа по протухшему инвойсу",
            extra={"inv_id": inv_id},
        )
        _count_payment("late_test")
        return web.Response(text=f"OK{inv_id}")
    else:
        logger.warning(
            "Robokassa callback с невалидной подписью (инвойс не найден)",
            extra={"inv_id": inv_id, "out_sum": out_sum},
        )
        _count_payment("invalid_signature")
        return web.Response(status=403, text="Invalid signature")

    # 3. Восстанавливаем данные платежа из подписанных Shp-параметров
    try:
        user_id = int(shp_params["Shp_user_id"])
        period = int(shp_params["Shp_period"])
        amount = int(float(out_sum))
        if period <= 0 or amount <= 0:
            raise ValueError(f"period={period}, amount={amount}")
    except (KeyError, ValueError) as e:
        # WARNING уходит алертом в админ-чат — платёж требует ручного разбора
        logger.warning(
            "Robokassa: оплата по протухшему инвойсу, восстановить не удалось "
            "— нужен ручной разбор",
            extra={"inv_id": inv_id, "out_sum": out_sum, "error": str(e)},
        )
        _count_payment("lost")
        return web.Response(text=f"OK{inv_id}")

    if not await mark_robokassa_processed(inv_id):
        _count_payment("duplicate")
        return web.Response(text=f"OK{inv_id}")

    logger.warning(
        "Robokassa: оплата по протухшему инвойсу восстановлена из Shp-параметров",
        extra={"inv_id": inv_id, "user_id": user_id, "period": period},
    )
    return await _activate_and_notify(
        request,
        inv_id=inv_id,
        user_id=user_id,
        period=period,
        amount=amount,
        recovered=True,
    )


async def _activate_and_notify(
    request: web.Request,
    *,
    inv_id: int,
    user_id: int,
    period: int,
    amount: int,
    recovered: bool,
) -> web.Response:
    """Активирует подписку и рассылает уведомления. При сбое активации откатывает
    idempotency-ключ и отвечает 500 — Robokassa ретраит callback."""
    subscription_service = request.app["robokassa_subscription_service"]
    db = request.app["robokassa_db"]

    try:
        with db.session() as session:
            user_tz, _ = db_funcs.get_user_timezone(session, user_id)

        subscription_service.extend(
            user_id=user_id,
            days=period,
            total_amount=amount,
            currency="RUB",
            provider="robokassa",
            provider_charge_id=str(inv_id),
            user_tz=user_tz,
        )
    except Exception as e:
        # Откатываем done-ключ: ретрай Robokassa должен повторить активацию,
        # иначе деньги списаны, а подписки нет
        await unmark_robokassa_processed(inv_id)
        logger.error(
            "Robokassa: сбой активации подписки, ждём ретрай",
            extra={"inv_id": inv_id, "user_id": user_id, "error": str(e)},
        )
        _count_payment("activation_error")
        return web.Response(status=500, text="Activation failed")

    # Подписка активирована — теперь безопасно удалить инвойс из Redis
    await delete_robokassa_invoice(inv_id)
    _count_payment("recovered_ok" if recovered else "ok")

    await notify_admin(
        format_sale(
            user_id=user_id,
            days=period,
            amount=amount,
            currency="RUB",
            provider="robokassa",
        )
    )

    # Уведомляем пользователя в Telegram
    bot = request.app["robokassa_bot"]
    try:
        info = subscription_service.get_info(user_id)
        date_str = "—"
        if info.ended_on is not None:
            date_str = info.ended_on.strftime("%d.%m.%Y")
        elif info.ended_at is not None:
            date_str = info.ended_at.strftime("%d.%m.%Y")

        locale = _get_user_locale(db, user_id)
        core = get_i18n_core()
        text = core.get(Msg.PAYMENT_SUCCESS, locale, days=period, date=date_str)
        await bot.send_message(user_id, text, parse_mode="HTML")
    except Exception as e:
        logger.warning(
            "Не удалось уведомить пользователя после оплаты Robokassa",
            extra={"user_id": user_id, "error": str(e)},
        )

    # Удаляем paywall-сообщение
    try:
        from src.features.subscription.handlers import _cleanup_paywall

        await _cleanup_paywall(bot, user_id)
    except Exception as e:
        logger.debug("Ошибка проигнорирована", extra={"error": str(e)})
        pass

    logger.info(
        "Robokassa оплата обработана",
        extra={
            "inv_id": inv_id,
            "user_id": user_id,
            "period": period,
            "amount": amount,
        },
    )
    return web.Response(text=f"OK{inv_id}")


async def _success_handler(request: web.Request) -> web.Response:
    """Редирект после успешной оплаты — HTML-страница с deeplink в бот."""
    locale = _resolve_locale(request)
    core = get_i18n_core()
    bot_username = request.app.get("robokassa_bot_username", "fivekcal_bot")
    html = _PAGE_HTML.format(
        lang=locale,
        icon="✅",
        title=core.get(Msg.ROBOKASSA_PAGE_SUCCESS_TITLE, locale),
        text=core.get(Msg.ROBOKASSA_PAGE_SUCCESS_TEXT, locale),
        open_bot=core.get(Msg.ROBOKASSA_PAGE_OPEN_BOT, locale),
        bot_username=bot_username,
    )
    return web.Response(text=html, content_type="text/html")


async def _fail_handler(request: web.Request) -> web.Response:
    """Редирект при отмене/ошибке оплаты."""
    locale = _resolve_locale(request)
    core = get_i18n_core()
    bot_username = request.app.get("robokassa_bot_username", "fivekcal_bot")
    html = _PAGE_HTML.format(
        lang=locale,
        icon="❌",
        title=core.get(Msg.ROBOKASSA_PAGE_FAIL_TITLE, locale),
        text=core.get(Msg.ROBOKASSA_PAGE_FAIL_TEXT, locale),
        open_bot=core.get(Msg.ROBOKASSA_PAGE_OPEN_BOT, locale),
        bot_username=bot_username,
    )
    return web.Response(text=html, content_type="text/html")
