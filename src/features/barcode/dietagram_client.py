"""
Dietagram API клиент (через RapidAPI).
150K+ товаров с фокусом на РФ/СНГ, КБЖУ на 100г.
Включается если задан DIETAGRAM_API_KEY.
"""

from typing import Optional

import httpx

from src.core.utils import get_logger
from src.features.barcode.models import BarcodeProduct, BarcodeSource

logger = get_logger()

_API_URL = "https://dietagram.p.rapidapi.com/apiBarcode.php"
_HOST = "dietagram.p.rapidapi.com"


async def lookup(
    barcode: str, client: httpx.AsyncClient, api_key: str
) -> Optional[BarcodeProduct]:
    """Ищет продукт по штрихкоду в Dietagram."""
    try:
        resp = await client.get(
            _API_URL,
            params={"name": barcode},
            headers={
                "X-RapidAPI-Key": api_key,
                "X-RapidAPI-Host": _HOST,
            },
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.warning(
            "Dietagram: ошибка запроса",
            extra={"barcode": barcode, "error": type(e).__name__},
            exc_info=False,
        )
        return None

    dishes = data.get("dishes")
    if not dishes:
        logger.info("Dietagram: продукт не найден", extra={"barcode": barcode})
        return None

    dish = dishes[0]
    name = (dish.get("name") or "").strip()
    if not name:
        logger.info("Dietagram: продукт без названия", extra={"barcode": barcode})
        return None

    # КБЖУ приходят как строки, на 100г
    parts = []
    cal = dish.get("caloric")
    if cal:
        parts.append(f"{cal} ккал/100г")
    protein = dish.get("protein")
    if protein:
        parts.append(f"белки {protein}г")
    fat = dish.get("fat")
    if fat:
        parts.append(f"жиры {fat}г")
    carbs = dish.get("carbon")
    if carbs:
        parts.append(f"углеводы {carbs}г")

    return BarcodeProduct(
        barcode=barcode,
        name=name,
        brand=None,
        source=BarcodeSource.DIETAGRAM,
        nutrition_raw=", ".join(parts),
    )
