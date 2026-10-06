"""
Robokassa payment integration — генерация платёжных ссылок и проверка подписей.

Документация: https://docs.robokassa.ru/ru/pay-interface
"""

import hashlib
import json
from urllib.parse import urlencode, quote


ROBOKASSA_BASE_URL = "https://auth.robokassa.ru/Merchant/Index.aspx"


def _build_shp_string(shp_params: dict[str, str] | None) -> str:
    """Shp_ параметры сортируются по алфавиту и соединяются через ':'."""
    if not shp_params:
        return ""
    sorted_items = sorted(shp_params.items(), key=lambda x: x[0].lower())
    return ":" + ":".join(f"{k}={v}" for k, v in sorted_items)


def _md5(s: str) -> str:
    return hashlib.md5(s.encode()).hexdigest()


def build_receipt(description: str, out_sum: str) -> str:
    """Формирует JSON чека (номенклатуру) для Робокассы по 54-ФЗ."""
    receipt = {
        "items": [
            {
                "name": description,
                "quantity": 1,
                "sum": float(out_sum),
                "payment_method": "full_payment",
                "payment_object": "service",
                "tax": "none",
            }
        ],
    }
    return quote(json.dumps(receipt, ensure_ascii=False))


def generate_payment_url(
    merchant_login: str,
    password1: str,
    inv_id: int,
    out_sum: str,
    description: str,
    is_test: bool = False,
    shp_params: dict[str, str] | None = None,
    receipt: str | None = None,
) -> str:
    """Формирует URL для перехода на страницу оплаты Robokassa."""
    sig_base = f"{merchant_login}:{out_sum}:{inv_id}:{receipt or ''}:{password1}"
    sig_base += _build_shp_string(shp_params)
    signature = _md5(sig_base)

    params = {
        "MerchantLogin": merchant_login,
        "OutSum": out_sum,
        "InvId": inv_id,
        "Description": description,
        "SignatureValue": signature,
        "Culture": "ru",
    }
    if receipt:
        params["Receipt"] = receipt
    if is_test:
        params["IsTest"] = 1

    if shp_params:
        for k, v in sorted(shp_params.items(), key=lambda x: x[0].lower()):
            params[k] = v

    return f"{ROBOKASSA_BASE_URL}?{urlencode(params)}"


def verify_result_signature(
    out_sum: str,
    inv_id: int,
    password2: str,
    received_signature: str,
    shp_params: dict[str, str] | None = None,
) -> bool:
    """Проверяет подпись Result URL callback (Пароль#2)."""
    sig_base = f"{out_sum}:{inv_id}:{password2}"
    sig_base += _build_shp_string(shp_params)
    expected = _md5(sig_base)
    return expected.lower() == received_signature.lower()
