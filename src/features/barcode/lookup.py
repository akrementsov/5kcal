import asyncio
from typing import Optional

import httpx

from src.core.utils import get_logger
from src.core.database import db as db_funcs
from src.features.barcode import (
    off_client,
    fatsecret_client,
    dietagram_client,
    barcodelookup_client,
)
from src.features.barcode.models import BarcodeProduct

logger = get_logger()

_TIMEOUT = httpx.Timeout(5.0)
_GOOD_NAME_LEN = 20  # название длиннее этого считается достаточно детальным


def _is_good(product: Optional[BarcodeProduct]) -> bool:
    """Продукт с КБЖУ и детальным названием — дальше искать не нужно."""
    return (
        product is not None
        and bool(product.nutrition_raw)
        and len(product.name) > _GOOD_NAME_LEN
    )


def _merge_products(found: list[BarcodeProduct]) -> BarcodeProduct:
    """Объединяет находки из разных источников: лучшее КБЖУ + лучшее название."""
    with_nutrition = [p for p in found if p.nutrition_raw]
    base = with_nutrition[0] if with_nutrition else found[0]

    best_name = max(found, key=lambda p: len(p.name))

    if best_name.name != base.name and len(best_name.name) > len(base.name):
        sources = f"{base.source}+{best_name.source}"
        logger.info(
            "Объединяем данные из разных источников",
            extra={
                "barcode": base.barcode,
                "nutrition_source": base.source,
                "name_source": best_name.source,
                "product_name": best_name.name,
            },
        )
        return BarcodeProduct(
            barcode=base.barcode,
            name=best_name.name,
            brand=best_name.brand or base.brand,
            source=sources,
            nutrition_raw=base.nutrition_raw,
        )

    return base


async def _lookup_one(
    barcode: str,
    client: httpx.AsyncClient,
    fs_key: Optional[str],
    fs_secret: Optional[str],
    dg_api_key: Optional[str],
    bl_api_key: Optional[str],
    db=None,
) -> Optional[BarcodeProduct]:
    found: list[BarcodeProduct] = []

    # ── 1. Бесплатные источники (последовательно) ──
    product = await off_client.lookup(barcode, client)
    if product:
        found.append(product)
        if _is_good(product):
            logger.info(
                "Штрихкод найден в OFF (полный)",
                extra={"barcode": barcode, "product_name": product.name},
            )
            return product

    if fs_key and fs_secret:
        product = await fatsecret_client.lookup(barcode, client, fs_key, fs_secret)
        if product:
            found.append(product)
            if _is_good(product):
                logger.info(
                    "Штрихкод найден в FatSecret (полный)",
                    extra={"barcode": barcode, "product_name": product.name},
                )
                return product

    # ── 2. Кэш из БД ──
    if db:
        try:
            with db.session() as session:
                cached = db_funcs.get_barcode_cache(session, barcode)
                if cached:
                    logger.info(
                        "Штрихкод найден в кэше",
                        extra={"barcode": barcode, "product_name": cached.name},
                    )
                    return BarcodeProduct(
                        barcode=barcode,
                        name=cached.name,
                        brand=cached.brand,
                        source=cached.source,
                        nutrition_raw=cached.nutrition_raw or "",
                    )
        except Exception as e:
            logger.warning(
                "Ошибка чтения кэша штрихкодов",
                extra={"barcode": barcode, "error": str(e)},
            )

    # ── 3. Платные источники (параллельно) ──
    paid_tasks = []
    if dg_api_key:
        paid_tasks.append(dietagram_client.lookup(barcode, client, dg_api_key))
    if bl_api_key:
        paid_tasks.append(barcodelookup_client.lookup(barcode, client, bl_api_key))

    used_paid = False
    if paid_tasks:
        paid_results = await asyncio.gather(*paid_tasks, return_exceptions=True)
        for result in paid_results:
            if isinstance(result, BarcodeProduct):
                found.append(result)
                used_paid = True

    if not found:
        logger.info("Штрихкод не найден ни в одной базе", extra={"barcode": barcode})
        return None

    # ── 4. Merge + сохранить в кэш ──
    merged = _merge_products(found) if len(found) > 1 else found[0]

    if db and used_paid:
        try:
            with db.session() as session:
                db_funcs.save_barcode_cache(
                    session,
                    barcode=merged.barcode,
                    name=merged.name,
                    brand=merged.brand,
                    source=merged.source,
                    nutrition_raw=merged.nutrition_raw,
                )
            logger.info(
                "Штрихкод сохранён в кэш",
                extra={"barcode": barcode, "product_name": merged.name},
            )
        except Exception as e:
            logger.warning(
                "Ошибка сохранения кэша штрихкодов",
                extra={"barcode": barcode, "error": str(e)},
            )

    logger.info(
        "Штрихкод найден",
        extra={
            "barcode": barcode,
            "product_name": merged.name,
            "source": merged.source,
            "has_nutrition": bool(merged.nutrition_raw),
        },
    )
    return merged


async def lookup_all(barcodes: list[str], db=None) -> list[BarcodeProduct]:
    """Параллельный поиск всех штрихкодов. Возвращает только найденные продукты."""
    from config.bot import config

    fs_key: Optional[str] = getattr(config, "fatsecret_key", None)
    fs_secret: Optional[str] = getattr(config, "fatsecret_secret", None)
    dg_api_key: Optional[str] = getattr(config, "dietagram_api_key", None)
    bl_api_key: Optional[str] = getattr(config, "barcode_lookup_api_key", None)

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        results = await asyncio.gather(
            *[
                _lookup_one(code, client, fs_key, fs_secret, dg_api_key, bl_api_key, db)
                for code in barcodes
            ],
            return_exceptions=False,
        )

    return [p for p in results if p is not None]
