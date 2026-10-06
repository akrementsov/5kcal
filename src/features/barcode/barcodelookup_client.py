"""
Barcode Lookup API клиент (barcodelookup.com).
Используется как третий источник после OFF и FatSecret.
Включается если задан BARCODE_LOOKUP_API_KEY.
"""

from typing import Optional

import httpx

from src.core.utils import get_logger
from src.features.barcode.models import BarcodeProduct, BarcodeSource

logger = get_logger()

_API_URL = "https://api.barcodelookup.com/v3/products"


async def lookup(
    barcode: str, client: httpx.AsyncClient, api_key: str
) -> Optional[BarcodeProduct]:
    """Ищет продукт по штрихкоду в Barcode Lookup API."""
    try:
        resp = await client.get(_API_URL, params={"barcode": barcode, "key": api_key})
        if resp.status_code == 404:
            logger.info("BarcodeLookup: продукт не найден", extra={"barcode": barcode})
            return None
        if resp.status_code == 403:
            logger.warning(
                "BarcodeLookup: ошибка авторизации (проверьте API ключ)",
                extra={"barcode": barcode},
            )
            return None
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPStatusError as e:
        logger.warning(
            "BarcodeLookup: HTTP ошибка",
            extra={"barcode": barcode, "status": e.response.status_code},
        )
        return None
    except Exception as e:
        logger.warning(
            "BarcodeLookup: ошибка запроса",
            extra={"barcode": barcode, "error": type(e).__name__},
            exc_info=False,
        )
        return None

    products = data.get("products")
    if not products:
        logger.info("BarcodeLookup: пустой ответ", extra={"barcode": barcode})
        return None

    product = products[0]
    name = (product.get("product_name") or product.get("title") or "").strip()
    if not name:
        logger.info("BarcodeLookup: продукт без названия", extra={"barcode": barcode})
        return None

    brand = (product.get("brand") or product.get("manufacturer") or "").strip() or None
    nutrition_raw = (product.get("nutrition_facts") or "").strip()

    return BarcodeProduct(
        barcode=barcode,
        name=name,
        brand=brand,
        source=BarcodeSource.BARCODE_LOOKUP,
        nutrition_raw=nutrition_raw,
    )
