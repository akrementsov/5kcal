"""Тесты валидации initData Mini App."""

import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

from src.features.webapp.auth import parse_auth_header

TEST_TOKEN = "test:token"  # из config._override в tests/conftest.py


def make_init_data(
    token: str = TEST_TOKEN,
    user_id: int = 1,
    language_code: str = "ru",
    auth_date: int | None = None,
) -> str:
    """Собирает initData, подписанный по алгоритму Telegram WebApp.

    auth_date — unix-время формирования данных; по умолчанию текущее время
    (свежие данные). Передайте явно устаревшее значение для тестов max-age.
    """
    if auth_date is None:
        auth_date = int(time.time())
    user = json.dumps(
        {"id": user_id, "first_name": "Test", "language_code": language_code},
        separators=(",", ":"),
    )
    fields = {"auth_date": str(auth_date), "query_id": "AAHtest", "user": user}
    check_string = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    signature = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode({**fields, "hash": signature})


def test_valid_init_data():
    header = f"tma {make_init_data(user_id=42)}"

    parsed = parse_auth_header(header)

    assert parsed is not None
    assert parsed.user.id == 42
    assert parsed.user.language_code == "ru"


def test_missing_header():
    assert parse_auth_header(None) is None
    assert parse_auth_header("") is None


def test_wrong_scheme():
    assert parse_auth_header(f"Bearer {make_init_data()}") is None


def test_tampered_signature():
    init_data = make_init_data(user_id=42)
    # Меняем query_id, не пересчитывая hash — подпись становится невалидной
    tampered = init_data.replace("query_id=AAHtest", "query_id=AAHtampered")

    assert parse_auth_header(f"tma {tampered}") is None


def test_stale_auth_date():
    """Валидная подпись, но auth_date старше 24 ч — должно вернуть None."""
    stale = int(time.time()) - 25 * 3600
    header = f"tma {make_init_data(user_id=1, auth_date=stale)}"

    assert parse_auth_header(header) is None


def test_garbage():
    assert parse_auth_header("tma not-a-query-string=") is None
