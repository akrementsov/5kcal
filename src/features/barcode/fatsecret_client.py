"""
FatSecret Platform API клиент с OAuth 2.0 (client credentials).
Используется как запасной вариант если продукт не найден в Open Food Facts.
Включается только если заданы FATSECRET_KEY и FATSECRET_SECRET.
"""

import time
import xml.etree.ElementTree as ET
from typing import Optional

import httpx

from src.core.utils import get_logger
from src.features.barcode.models import BarcodeProduct, BarcodeSource

logger = get_logger()

_TOKEN_URL = "https://oauth.fatsecret.com/connect/token"
_API_URL = "https://platform.fatsecret.com/rest/server.api"

# Кэш токена: (access_token, expires_at)
_token_cache: tuple[str, float] = ("", 0.0)


async def _get_token(
    client_id: str, client_secret: str, client: httpx.AsyncClient
) -> Optional[str]:
    """Получает Bearer-токен через client credentials grant. Кэширует до истечения."""
    global _token_cache
    token, expires_at = _token_cache
    if token and time.time() < expires_at - 60:
        return token

    try:
        resp = await client.post(
            _TOKEN_URL,
            data={"grant_type": "client_credentials", "scope": "basic"},
            auth=(client_id, client_secret),
        )
        data = resp.json()
        token = data.get("access_token", "")
        expires_in = int(data.get("expires_in", 86400))
        _token_cache = (token, time.time() + expires_in)
        logger.info("FatSecret: токен получен", extra={"expires_in": expires_in})
        return token
    except Exception as e:
        logger.warning("FatSecret: ошибка получения токена", extra={"error": str(e)})
        return None


async def _call(
    method: str, params: dict, token: str, client: httpx.AsyncClient
) -> Optional[ET.Element]:
    """Выполняет запрос к FatSecret API с Bearer-токеном."""
    try:
        resp = await client.get(
            _API_URL,
            params={"method": method, "format": "xml", **params},
            headers={"Authorization": f"Bearer {token}"},
        )
        root = ET.fromstring(resp.text)
        if root.tag == "error":
            logger.warning(
                "FatSecret API error",
                extra={"method": method, "message": root.findtext("message")},
            )
            return None
        return root
    except Exception as e:
        logger.warning(
            "FatSecret: ошибка запроса", extra={"method": method, "error": str(e)}
        )
        return None


async def lookup(
    barcode: str, client: httpx.AsyncClient, client_id: str, client_secret: str
) -> Optional[BarcodeProduct]:
    """Ищет продукт по штрихкоду в FatSecret."""
    token = await _get_token(client_id, client_secret, client)
    if not token:
        return None

    # Шаг 1: получаем food_id по штрихкоду
    root = await _call("food.find_id_for_barcode", {"barcode": barcode}, token, client)
    if root is None:
        return None

    food_id = root.findtext("food_id/value") or root.findtext("food_id")
    if not food_id:
        logger.info(
            "FatSecret: food_id не найден для штрихкода", extra={"barcode": barcode}
        )
        return None

    # Шаг 2: получаем данные о продукте
    root = await _call("food.get.v4", {"food_id": food_id}, token, client)
    if root is None:
        return None

    name = root.findtext("food/food_name") or ""
    brand = root.findtext("food/brand_name") or None

    # Собираем сырые данные из первого serving
    nutrition_raw = _extract_nutrition_raw(root)

    if not name.strip():
        logger.info(
            "FatSecret: продукт без названия",
            extra={"barcode": barcode, "food_id": food_id},
        )
        return None

    return BarcodeProduct(
        barcode=barcode,
        name=name.strip(),
        brand=brand.strip() if brand else None,
        source=BarcodeSource.FATSECRET,
        nutrition_raw=nutrition_raw,
    )


def _extract_nutrition_raw(root: ET.Element) -> str:
    """Извлекает данные о питательной ценности из servings в читаемую строку."""
    servings = root.findall(".//serving")
    if not servings:
        return ""

    # Ищем порцию на 100г (±1г), иначе берём первую граммовую
    serving = None
    for s in servings:
        unit = (s.findtext("metric_serving_unit") or "").lower()
        amount = s.findtext("metric_serving_amount") or ""
        if unit == "g":
            try:
                if abs(float(amount) - 100.0) < 1.0:
                    serving = s
                    break
            except ValueError:
                continue
    if serving is None:
        for s in servings:
            if (s.findtext("metric_serving_unit") or "").lower() == "g":
                serving = s
                break
    if serving is None and servings:
        serving = servings[0]
    if serving is None:
        return ""

    parts = []
    # Размер порции
    desc = serving.findtext("serving_description") or ""
    metric_amount = serving.findtext("metric_serving_amount") or ""
    metric_unit = serving.findtext("metric_serving_unit") or ""
    if metric_amount and metric_unit:
        parts.append(f"порция {metric_amount}{metric_unit}")
    elif desc:
        parts.append(f"порция: {desc}")

    cal = serving.findtext("calories")
    if cal:
        parts.append(f"{cal} ккал")
    protein = serving.findtext("protein")
    if protein:
        parts.append(f"белки {protein}г")
    fat = serving.findtext("fat")
    if fat:
        parts.append(f"жиры {fat}г")
    carbs = serving.findtext("carbohydrate")
    if carbs:
        parts.append(f"углеводы {carbs}г")

    return ", ".join(parts)
