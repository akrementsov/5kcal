"""Тесты Robokassa webhook: подпись, IP-whitelist, idempotency, активация подписки."""

import hashlib
import logging
from dataclasses import dataclass

import pytest
from aiohttp import web

from config.bot.config import config
from src.payment.robokassa import (
    generate_payment_url,
    verify_result_signature,
    build_receipt,
)
from src.payment.robokassa_webhook import (
    _result_handler,
    _success_handler,
    _fail_handler,
    ROBOKASSA_ALLOWED_IPS,
)
from src.features.subscription.payment_state import (
    init_payment_state,
    create_robokassa_invoice,
    get_robokassa_invoice,
    delete_robokassa_invoice,
    _KEY_ROBOKASSA_DONE,
)
from tests.mocks import MockBot


VALID_IP = next(iter(ROBOKASSA_ALLOWED_IPS))
PROD_PASSWORD2 = "prod_p2"
TEST_PASSWORD2 = "test_p2"


# ─── Helpers ────────────────────────────────────────────────────────────────


@dataclass
class _FakeBotMe:
    username: str = "fivekcal_bot"


class _BotWithGetMe(MockBot):
    async def get_me(self):
        return _FakeBotMe()


def _md5(s: str) -> str:
    return hashlib.md5(s.encode()).hexdigest()


def _sig_for(out_sum: str, inv_id: int, password2: str, shp: dict | None = None) -> str:
    base = f"{out_sum}:{inv_id}:{password2}"
    if shp:
        base += ":" + ":".join(
            f"{k}={v}" for k, v in sorted(shp.items(), key=lambda x: x[0].lower())
        )
    return _md5(base)


class _FakeRequest:
    """Минимальный мок aiohttp.web.Request для вызова handler-ов напрямую."""

    def __init__(
        self,
        app,
        *,
        method: str = "POST",
        remote_ip: str = VALID_IP,
        post_data: dict | None = None,
        query_data: dict | None = None,
        headers: dict | None = None,
    ):
        self.app = app
        self.method = method
        self.remote = remote_ip
        self.headers = headers or {}
        self._post_data = post_data or {}
        self.query = query_data or {}

    async def post(self):
        return self._post_data


def _make_app(bot, subscription_service, db, cfg) -> dict:
    """Возвращает dict, имитирующий aiohttp.Application для request.app[...] доступа."""
    app = {
        "robokassa_bot": bot,
        "robokassa_subscription_service": subscription_service,
        "robokassa_db": db,
        "robokassa_config": cfg,
        "robokassa_bot_username": "fivekcal_bot",
    }
    return app


class _FakeI18nCore:
    """Заглушка FluentRuntimeCore — возвращает ключ как текст."""

    def get(self, msg_id, locale=None, **kwargs):
        return f"[{msg_id}]"


@pytest.fixture(autouse=True)
async def _init_state(fake_redis, monkeypatch):
    """Инициализирует payment_state и i18n для каждого теста."""
    init_payment_state(fake_redis)
    # Подменяем пароли Robokassa в config
    config._real.robokassa_password2 = PROD_PASSWORD2
    config._real.robokassa_password2_test = TEST_PASSWORD2
    config._real.robokassa_merchant_login = "test_login"
    config._real.robokassa_password1 = "prod_p1"
    config._real.robokassa_password1_test = "test_p1"
    # Подменяем i18n_core — handler шлёт уведомление и читает у user локаль
    monkeypatch.setattr(
        "src.payment.robokassa_webhook.get_i18n_core",
        lambda: _FakeI18nCore(),
    )
    yield


# ─── Unit-тесты подписи и URL ────────────────────────────────────────────────


class TestRobokassaSignature:
    """Чистые unit-тесты функций подписи."""

    def test_verify_valid_signature(self):
        sig = _md5("100.00:42:secret")
        assert verify_result_signature("100.00", 42, "secret", sig) is True

    def test_verify_invalid_signature(self):
        assert verify_result_signature("100.00", 42, "secret", "0" * 32) is False

    def test_verify_case_insensitive(self):
        sig = _md5("100.00:42:secret").upper()
        assert verify_result_signature("100.00", 42, "secret", sig) is True

    def test_verify_signature_with_shp_params(self):
        shp = {"Shp_user_id": "123", "Shp_period": "30"}
        # Параметры сортируются по алфавиту в lower-case
        base = "100.00:42:secret:Shp_period=30:Shp_user_id=123"
        sig = _md5(base)
        assert (
            verify_result_signature("100.00", 42, "secret", sig, shp) is True
        )

    def test_generate_payment_url_has_signature(self):
        url = generate_payment_url(
            merchant_login="m",
            password1="p1",
            inv_id=1,
            out_sum="100.00",
            description="desc",
        )
        assert "SignatureValue=" in url
        assert "MerchantLogin=m" in url
        assert "InvId=1" in url
        assert "OutSum=100.00" in url

    def test_generate_payment_url_is_test_flag(self):
        url = generate_payment_url(
            merchant_login="m",
            password1="p1",
            inv_id=1,
            out_sum="100.00",
            description="desc",
            is_test=True,
        )
        assert "IsTest=1" in url

    def test_generate_payment_url_no_is_test_when_prod(self):
        """is_test=False (default) — IsTest параметр отсутствует."""
        url = generate_payment_url(
            merchant_login="m",
            password1="p1",
            inv_id=1,
            out_sum="100.00",
            description="desc",
            is_test=False,
        )
        assert "IsTest=" not in url

    def test_generate_payment_url_signature_differs_for_test_and_prod(self):
        """Один и тот же inv_id с разными password1 даёт разные подписи (тест vs prod пароли)."""
        url_prod = generate_payment_url(
            merchant_login="m",
            password1="prod_secret",
            inv_id=1,
            out_sum="100.00",
            description="desc",
            is_test=False,
        )
        url_test = generate_payment_url(
            merchant_login="m",
            password1="test_secret",
            inv_id=1,
            out_sum="100.00",
            description="desc",
            is_test=True,
        )
        # SignatureValue должен отличаться, так как password1 разный
        import re

        sig_prod = re.search(r"SignatureValue=([a-f0-9]+)", url_prod).group(1)
        sig_test = re.search(r"SignatureValue=([a-f0-9]+)", url_test).group(1)
        assert sig_prod != sig_test

    def test_build_receipt_is_url_encoded(self):
        receipt = build_receipt("Подписка", "299.00")
        # URL-кодирование: пробелы как %20, кириллица как %XX
        assert "%" in receipt
        assert " " not in receipt


# ─── Интеграционные тесты _result_handler ────────────────────────────────────


class TestResultHandler:
    """Тесты обработки Robokassa Result URL callback."""

    async def test_rejects_unknown_ip(self, test_db):
        app = _make_app(MockBot(), None, test_db, config)
        request = _FakeRequest(app, remote_ip="1.2.3.4")

        response = await _result_handler(request)

        assert response.status == 403

    async def test_unknown_ip_logs_info_not_warning(self, test_db):
        """Чужой IP — штатный шум (сканеры), не должен алертить в админ-чат.

        Телеграм-хендлер шлёт WARNING+, поэтому лог должен быть уровня INFO.
        """
        app = _make_app(MockBot(), None, test_db, config)
        request = _FakeRequest(app, remote_ip="1.2.3.4")

        records = []
        handler = logging.Handler()
        handler.emit = records.append
        fivekcal_logger = logging.getLogger("fivekcal")
        old_level = fivekcal_logger.level
        fivekcal_logger.setLevel(logging.INFO)
        fivekcal_logger.addHandler(handler)
        try:
            await _result_handler(request)
        finally:
            fivekcal_logger.removeHandler(handler)
            fivekcal_logger.setLevel(old_level)

        ip_records = [r for r in records if "IP" in r.getMessage()]
        assert ip_records, "лог о неразрешённом IP должен писаться"
        assert all(r.levelno < logging.WARNING for r in ip_records)

    async def test_accepts_ip_via_x_forwarded_for(self, test_db):
        """Проброс через nginx: реальный IP в X-Forwarded-For."""
        app = _make_app(MockBot(), None, test_db, config)
        request = _FakeRequest(
            app,
            remote_ip="127.0.0.1",  # nginx
            headers={"X-Forwarded-For": f"{VALID_IP}, 127.0.0.1"},
            post_data={},
        )

        response = await _result_handler(request)
        # IP принят → дальше валится на отсутствующих параметрах
        assert response.status == 400

    async def test_rejects_missing_params(self, test_db):
        app = _make_app(MockBot(), None, test_db, config)
        request = _FakeRequest(app, post_data={"OutSum": "100.00"})  # нет InvId/Signature

        response = await _result_handler(request)

        assert response.status == 400

    async def test_unknown_inv_id_with_invalid_signature_rejected(self, test_db):
        """Несуществующий InvId с невалидной подписью — мусор/сканер, отказ 403.

        (Раньше отвечали OK, предполагая «уже обработан»; теперь дубли
        распознаются по done-ключу/платежу в БД, а не по отсутствию инвойса.)"""
        app = _make_app(MockBot(), None, test_db, config)
        request = _FakeRequest(
            app,
            post_data={
                "OutSum": "100.00",
                "InvId": "999999",
                "SignatureValue": "0" * 32,
            },
        )

        response = await _result_handler(request)

        assert response.status == 403

    async def test_rejects_invalid_signature(
        self, test_db, subscription_service, user_service
    ):
        user_service.get_or_create(1)
        inv_id = await create_robokassa_invoice(
            user_id=1, period=30, amount=299, is_test=False
        )

        app = _make_app(MockBot(), subscription_service, test_db, config)
        request = _FakeRequest(
            app,
            post_data={
                "OutSum": "299.00",
                "InvId": str(inv_id),
                "SignatureValue": "0" * 32,  # неверная подпись
            },
        )

        response = await _result_handler(request)

        assert response.status == 403
        # Инвойс остался в Redis — повторная попытка возможна
        assert await get_robokassa_invoice(inv_id) is not None

    async def test_rejects_amount_mismatch(
        self, test_db, subscription_service, user_service
    ):
        """Сумма из callback ≠ сумма в инвойсе — отказ."""
        user_service.get_or_create(1)
        inv_id = await create_robokassa_invoice(
            user_id=1, period=30, amount=299, is_test=False
        )

        # Подпись валидна, но сумма подменена на 1₽
        sig = _sig_for("1.00", inv_id, PROD_PASSWORD2)
        app = _make_app(MockBot(), subscription_service, test_db, config)
        request = _FakeRequest(
            app,
            post_data={
                "OutSum": "1.00",
                "InvId": str(inv_id),
                "SignatureValue": sig,
            },
        )

        response = await _result_handler(request)

        assert response.status == 400
        # Инвойс не удалён — атака пресечена, обработка не произошла
        assert await get_robokassa_invoice(inv_id) is not None

    async def test_activates_subscription_on_valid_callback(
        self, test_db, subscription_service, user_service
    ):
        """Happy path: валидный callback → подписка продлена, инвойс удалён."""
        user_service.get_or_create(1)
        inv_id = await create_robokassa_invoice(
            user_id=1, period=30, amount=299, is_test=False
        )

        sig = _sig_for("299.00", inv_id, PROD_PASSWORD2)
        bot = _BotWithGetMe()
        app = _make_app(bot, subscription_service, test_db, config)
        request = _FakeRequest(
            app,
            post_data={
                "OutSum": "299.00",
                "InvId": str(inv_id),
                "SignatureValue": sig,
            },
        )

        response = await _result_handler(request)
        body = await _response_text(response)

        assert response.status == 200
        assert body == f"OK{inv_id}"

        # Подписка активирована
        info = subscription_service.get_info(1)
        assert info.is_active is True

        # Инвойс удалён
        assert await get_robokassa_invoice(inv_id) is None

        # Пользователь уведомлён в Telegram
        assert len(bot.sent_messages) >= 1

    async def test_idempotent_on_duplicate_callback(
        self, test_db, subscription_service, user_service
    ):
        """Robokassa может прислать callback дважды — активируется только один раз."""
        user_service.get_or_create(1)
        inv_id = await create_robokassa_invoice(
            user_id=1, period=30, amount=299, is_test=False
        )

        sig = _sig_for("299.00", inv_id, PROD_PASSWORD2)
        bot = _BotWithGetMe()
        app = _make_app(bot, subscription_service, test_db, config)

        def _make_request():
            return _FakeRequest(
                app,
                post_data={
                    "OutSum": "299.00",
                    "InvId": str(inv_id),
                    "SignatureValue": sig,
                },
            )

        # Первый callback
        r1 = await _result_handler(_make_request())
        # Второй (дубль) — попадает в idempotency guard или в "уже обработанный"
        r2 = await _result_handler(_make_request())

        assert r1.status == 200
        assert r2.status == 200

        # Подписка активна, но продлена только один раз
        info = subscription_service.get_info(1)
        assert info.is_active is True

        # Только один платёж в истории
        from src.core.database import db as db_funcs

        with test_db.session() as session:
            payments = db_funcs.get_user_payments(session, 1)
            paid = [p for p in payments if p.provider == "robokassa"]
            assert len(paid) == 1

    async def test_test_mode_uses_test_password(
        self, test_db, subscription_service, user_service
    ):
        """Invoice с is_test=True валидируется через ROBOKASSA_PASSWORD2_TEST."""
        user_service.get_or_create(1)
        inv_id = await create_robokassa_invoice(
            user_id=1, period=30, amount=299, is_test=True
        )

        # Подпись через ТЕСТОВЫЙ пароль — должна пройти
        sig = _sig_for("299.00", inv_id, TEST_PASSWORD2)
        bot = _BotWithGetMe()
        app = _make_app(bot, subscription_service, test_db, config)
        request = _FakeRequest(
            app,
            post_data={
                "OutSum": "299.00",
                "InvId": str(inv_id),
                "SignatureValue": sig,
            },
        )

        response = await _result_handler(request)
        assert response.status == 200

        # Та же подпись с боевым паролем НЕ прошла бы
        inv_id2 = await create_robokassa_invoice(
            user_id=1, period=30, amount=299, is_test=True
        )
        bad_sig = _sig_for("299.00", inv_id2, PROD_PASSWORD2)
        request2 = _FakeRequest(
            app,
            post_data={
                "OutSum": "299.00",
                "InvId": str(inv_id2),
                "SignatureValue": bad_sig,
            },
        )
        response2 = await _result_handler(request2)
        assert response2.status == 403


# ─── Success / Fail страницы ────────────────────────────────────────────────


class TestSuccessFailPages:
    """HTML-страницы редиректа после оплаты."""

    async def test_success_returns_html(self, test_db):
        app = _make_app(MockBot(), None, test_db, config)
        request = _FakeRequest(app, method="GET", query_data={"Shp_user_id": "1"})

        response = await _success_handler(request)
        body = await _response_text(response)

        assert response.status == 200
        assert response.content_type == "text/html"
        assert "fivekcal_bot" in body
        assert "<!DOCTYPE html>" in body

    async def test_fail_returns_html(self, test_db):
        app = _make_app(MockBot(), None, test_db, config)
        request = _FakeRequest(app, method="GET", query_data={"Shp_user_id": "1"})

        response = await _fail_handler(request)
        body = await _response_text(response)

        assert response.status == 200
        assert response.content_type == "text/html"
        assert "fivekcal_bot" in body

    async def test_success_handles_empty_shp_user_id(self, test_db):
        """Пустой Shp_user_id в /success — fallback на DEFAULT_LOCALE, страница рендерится."""
        app = _make_app(MockBot(), None, test_db, config)
        request = _FakeRequest(app, method="GET", query_data={"Shp_user_id": ""})

        response = await _success_handler(request)

        assert response.status == 200

    async def test_success_handles_missing_shp_user_id(self, test_db):
        """Полностью отсутствующий Shp_user_id — то же поведение."""
        app = _make_app(MockBot(), None, test_db, config)
        request = _FakeRequest(app, method="GET", query_data={})

        response = await _success_handler(request)

        assert response.status == 200

    async def test_success_handles_non_numeric_shp_user_id(self, test_db):
        """Shp_user_id не int — поглощается, locale = default."""
        app = _make_app(MockBot(), None, test_db, config)
        request = _FakeRequest(
            app, method="GET", query_data={"Shp_user_id": "not-a-number"}
        )

        response = await _success_handler(request)

        assert response.status == 200


# ─── Edge cases: OutSum, concurrent duplicates ───────────────────────────────


class TestResultHandlerEdgeCases:
    """Граничные значения и многократные дубли callback-а."""

    async def test_outsum_zero_rejected(
        self, test_db, subscription_service, user_service
    ):
        """OutSum='0.00' с валидной подписью — amount mismatch, подписка не активируется."""
        user_service.get_or_create(1)
        inv_id = await create_robokassa_invoice(
            user_id=1, period=30, amount=299, is_test=False
        )

        sig = _sig_for("0.00", inv_id, PROD_PASSWORD2)
        app = _make_app(MockBot(), subscription_service, test_db, config)
        request = _FakeRequest(
            app,
            post_data={
                "OutSum": "0.00",
                "InvId": str(inv_id),
                "SignatureValue": sig,
            },
        )

        response = await _result_handler(request)

        assert response.status == 400
        info = subscription_service.get_info(1)
        assert info.is_active is False
        # Инвойс остался — для повторной попытки
        assert await get_robokassa_invoice(inv_id) is not None

    async def test_outsum_non_numeric_rejected(
        self, test_db, subscription_service, user_service
    ):
        """OutSum='garbage' с валидной подписью — received_amount=0 → amount mismatch."""
        user_service.get_or_create(1)
        inv_id = await create_robokassa_invoice(
            user_id=1, period=30, amount=299, is_test=False
        )

        sig = _sig_for("garbage", inv_id, PROD_PASSWORD2)
        app = _make_app(MockBot(), subscription_service, test_db, config)
        request = _FakeRequest(
            app,
            post_data={
                "OutSum": "garbage",
                "InvId": str(inv_id),
                "SignatureValue": sig,
            },
        )

        response = await _result_handler(request)

        assert response.status == 400
        info = subscription_service.get_info(1)
        assert info.is_active is False

    async def test_three_consecutive_callbacks_activate_only_once(
        self, test_db, subscription_service, user_service
    ):
        """SETNX-guard: даже три подряд одинаковых callback — одна активация, два idempotent OK."""
        from src.core.database import db as db_funcs

        user_service.get_or_create(1)
        inv_id = await create_robokassa_invoice(
            user_id=1, period=30, amount=299, is_test=False
        )

        sig = _sig_for("299.00", inv_id, PROD_PASSWORD2)
        bot = _BotWithGetMe()
        app = _make_app(bot, subscription_service, test_db, config)

        def _make_request():
            return _FakeRequest(
                app,
                post_data={
                    "OutSum": "299.00",
                    "InvId": str(inv_id),
                    "SignatureValue": sig,
                },
            )

        responses = []
        for _ in range(3):
            responses.append(await _result_handler(_make_request()))

        assert all(r.status == 200 for r in responses)

        info = subscription_service.get_info(1)
        assert info.is_active is True

        # Ровно один платёж в БД — двойная/тройная активация отсечена
        with test_db.session() as session:
            payments = db_funcs.get_user_payments(session, 1)
            paid = [p for p in payments if p.provider == "robokassa"]
            assert len(paid) == 1


# ─── Helper для извлечения текста ответа ────────────────────────────────────


async def _response_text(response: web.Response) -> str:
    """Извлекает body из web.Response, который handler вернул синхронно."""
    if response.body is None:
        return ""
    if isinstance(response.body, bytes):
        return response.body.decode()
    # aiohttp StreamReader или Payload — преобразуем через text
    return response.text if hasattr(response, "text") and isinstance(response.text, str) else str(response.body)


# ─── Надёжность: сбой активации, протухший инвойс, поздние дубли ─────────────


class TestResultHandlerReliability:
    """Регрессии: платежи не должны молча теряться при сбоях и протухших инвойсах."""

    def _request(self, app, inv_id: int, sig: str, shp: dict | None = None):
        post_data = {
            "OutSum": "299.00",
            "InvId": str(inv_id),
            "SignatureValue": sig,
        }
        if shp:
            post_data.update(shp)
        return _FakeRequest(app, post_data=post_data)

    async def test_retry_after_extend_failure_activates(
        self, test_db, subscription_service, user_service, monkeypatch
    ):
        """Сбой extend() (БД недоступна) → первый callback НЕ отвечает OK,
        ретрай Robokassa успешно активирует подписку."""
        user_service.get_or_create(1)
        inv_id = await create_robokassa_invoice(
            user_id=1, period=30, amount=299, is_test=False
        )
        sig = _sig_for("299.00", inv_id, PROD_PASSWORD2)
        bot = _BotWithGetMe()
        app = _make_app(bot, subscription_service, test_db, config)

        orig_extend = subscription_service.extend
        calls = {"n": 0}

        def flaky_extend(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("db down")
            return orig_extend(*args, **kwargs)

        monkeypatch.setattr(subscription_service, "extend", flaky_extend)

        # Первый callback: сбой активации — Robokassa должна получить не-OK и ретраить
        try:
            r1 = await _result_handler(self._request(app, inv_id, sig))
            body1 = await _response_text(r1)
            assert body1 != f"OK{inv_id}", "сбой активации не должен подтверждаться как OK"
        except RuntimeError:
            pass  # исключение наружу → aiohttp вернёт 500, это тоже приемлемо

        # Ретрай Robokassa: подписка должна активироваться
        r2 = await _result_handler(self._request(app, inv_id, sig))
        assert r2.status == 200
        assert (await _response_text(r2)) == f"OK{inv_id}"
        assert subscription_service.get_info(1).is_active is True

    async def test_late_callback_after_invoice_ttl_recovers_payment(
        self, test_db, subscription_service, user_service
    ):
        """Инвойс протух в Redis (TTL 1ч), но callback с валидной подписью и
        Shp-параметрами (они подписаны) должен восстановить оплату, а не молча OK."""
        user_service.get_or_create(1)
        inv_id = await create_robokassa_invoice(
            user_id=1, period=30, amount=299, is_test=False
        )
        # Эмулируем истечение TTL
        await delete_robokassa_invoice(inv_id)

        shp = {"Shp_period": "30", "Shp_user_id": "1"}
        sig = _sig_for("299.00", inv_id, PROD_PASSWORD2, shp)
        bot = _BotWithGetMe()
        app = _make_app(bot, subscription_service, test_db, config)

        response = await _result_handler(self._request(app, inv_id, sig, shp))

        assert response.status == 200
        assert subscription_service.get_info(1).is_active is True

        from src.core.database import db as db_funcs

        with test_db.session() as session:
            paid = [
                p
                for p in db_funcs.get_user_payments(session, 1)
                if p.provider == "robokassa"
            ]
            assert len(paid) == 1

    async def test_duplicate_after_done_key_expiry_not_reprocessed(
        self, test_db, subscription_service, user_service, fake_redis
    ):
        """Дубль callback-а после истечения done-ключа не должен активировать
        подписку второй раз (идемпотентность по платежу в БД)."""
        user_service.get_or_create(1)
        inv_id = await create_robokassa_invoice(
            user_id=1, period=30, amount=299, is_test=False
        )
        shp = {"Shp_period": "30", "Shp_user_id": "1"}
        sig = _sig_for("299.00", inv_id, PROD_PASSWORD2, shp)
        bot = _BotWithGetMe()
        app = _make_app(bot, subscription_service, test_db, config)

        r1 = await _result_handler(self._request(app, inv_id, sig, shp))
        assert r1.status == 200

        # Эмулируем истечение done-ключа (SETNX TTL) — поздний дубль
        await fake_redis.delete(_KEY_ROBOKASSA_DONE.format(inv_id=inv_id))
        r2 = await _result_handler(self._request(app, inv_id, sig, shp))
        assert r2.status == 200

        from src.core.database import db as db_funcs

        with test_db.session() as session:
            paid = [
                p
                for p in db_funcs.get_user_payments(session, 1)
                if p.provider == "robokassa"
            ]
            assert len(paid) == 1, "поздний дубль не должен создавать второй платёж"


# ─── Счётчик InvId и TTL тест-режима ─────────────────────────────────────────


class TestInvCounterSeeding:
    """Потеря Redis обнуляет INCR-счётчик InvId — Robokassa отклонит дубли.
    При старте счётчик сидируется максимальным InvId из истории платежей."""

    async def test_counter_seeded_from_db_payments(
        self, test_db, user_service, fake_redis
    ):
        from src.core.database import db as db_funcs
        from src.features.subscription.payment_state import (
            create_robokassa_invoice,
            seed_robokassa_inv_counter,
        )

        user_service.get_or_create(1)
        with test_db.session() as session:
            db_funcs.add_payment(
                session,
                1,
                days=30,
                total_amount=299,
                provider="robokassa",
                provider_charge_id="41",
            )

        await seed_robokassa_inv_counter(test_db)
        inv_id = await create_robokassa_invoice(user_id=1, period=30, amount=299)

        assert inv_id > 41

    async def test_seeding_noop_when_counter_exists(self, test_db, fake_redis):
        from src.features.subscription.payment_state import (
            create_robokassa_invoice,
            seed_robokassa_inv_counter,
        )

        first = await create_robokassa_invoice(user_id=1, period=30, amount=299)
        await seed_robokassa_inv_counter(test_db)
        second = await create_robokassa_invoice(user_id=1, period=30, amount=299)

        assert second == first + 1


class TestRobokassaTestModeTtl:
    async def test_test_mode_key_expires(self, fake_redis):
        """Забытый /pay_mode test не должен жить вечно — ключ с TTL."""
        from src.features.subscription.payment_state import set_robokassa_test_mode

        await set_robokassa_test_mode(7, True)

        ttl = await fake_redis.ttl("pay:robokassa:test_mode:7")
        assert ttl > 0
