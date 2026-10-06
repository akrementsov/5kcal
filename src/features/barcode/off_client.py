from typing import Optional

import httpx

from src.core.utils import get_logger
from src.features.barcode.models import BarcodeProduct, BarcodeSource

logger = get_logger()

_OFF_URL = "https://world.openfoodfacts.org/api/v2/product/{barcode}.json"
_FIELDS = "product_name,product_name_ru,brands,nutriments"


async def lookup(barcode: str, client: httpx.AsyncClient) -> Optional[BarcodeProduct]:
    """Ищет продукт по штрихкоду в Open Food Facts."""
    try:
        url = _OFF_URL.format(barcode=barcode)
        resp = await client.get(url, params={"fields": _FIELDS})
        data = resp.json()
    except Exception as e:
        logger.warning(
            "OFF: ошибка запроса",
            extra={"barcode": barcode, "error": type(e).__name__},
            exc_info=False,
        )
        return None

    if data.get("status") != 1:
        logger.info(
            "OFF: продукт не найден",
            extra={"barcode": barcode, "status": data.get("status")},
        )
        return None

    product = data.get("product", {})
    name = product.get("product_name_ru") or product.get("product_name", "").strip()
    if not name:
        logger.info("OFF: продукт без названия", extra={"barcode": barcode})
        return None

    n = product.get("nutriments", {})
    parts = []
    cal = n.get("energy-kcal_100g") or n.get("energy_100g")
    if cal is not None:
        parts.append(f"{float(cal):.0f} ккал/100г")
    protein = n.get("proteins_100g")
    if protein is not None:
        parts.append(f"белки {float(protein):.1f}г")
    fat = n.get("fat_100g")
    if fat is not None:
        parts.append(f"жиры {float(fat):.1f}г")
    carbs = n.get("carbohydrates_100g")
    if carbs is not None:
        parts.append(f"углеводы {float(carbs):.1f}г")

    return BarcodeProduct(
        barcode=barcode,
        name=name,
        brand=product.get("brands") or None,
        source=BarcodeSource.OPEN_FOOD_FACTS,
        nutrition_raw=", ".join(parts),
    )
