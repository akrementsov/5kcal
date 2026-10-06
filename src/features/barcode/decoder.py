import io

from PIL import Image, ImageOps, ImageEnhance

from src.core.utils import get_logger

logger = get_logger()

_BARCODE_FORMATS = {"EAN13", "EAN8", "UPCA", "UPCE"}


def _to_zxing_formats():
    import zxingcpp

    return [getattr(zxingcpp.BarcodeFormat, f) for f in _BARCODE_FORMATS]


def decode_barcodes_from_image(image_bytes: bytes) -> list[str]:
    """Возвращает все EAN/UPC штрихкоды, найденные на изображении."""
    try:
        import zxingcpp
    except ImportError:
        logger.warning("zxing-cpp не установлен, декодирование штрихкодов недоступно")
        return []

    try:
        image = Image.open(io.BytesIO(image_bytes))
        formats = _to_zxing_formats()

        # Попытка 1: оригинал с дефолтными настройками
        results = zxingcpp.read_barcodes(image, formats=formats)
        found = [r.text for r in results]
        if found:
            logger.info(
                "Штрихкоды распознаны на изображении",
                extra={"barcodes": found, "count": len(found)},
            )
            return found

        # Попытка 2: grayscale + повышенный контраст
        gray = ImageOps.grayscale(image)
        gray = ImageEnhance.Contrast(gray).enhance(2.0)
        results = zxingcpp.read_barcodes(
            gray, formats=formats, binarizer=zxingcpp.Binarizer.GlobalHistogram
        )
        found = [r.text for r in results]
        if found:
            logger.info(
                "Штрихкоды распознаны (fallback grayscale)",
                extra={"barcodes": found, "count": len(found)},
            )
            return found

        return []
    except Exception as e:
        logger.info("Не удалось декодировать штрихкод", extra={"error": str(e)})
        return []


def find_all_barcodes(photos: list[bytes]) -> list[str]:
    """Собирает все уникальные штрихкоды со всех фото."""
    seen: set[str] = set()
    result: list[str] = []
    for img_bytes in photos:
        for code in decode_barcodes_from_image(img_bytes):
            if code not in seen:
                seen.add(code)
                result.append(code)
    return result


async def find_all_barcodes_async(photos: list[bytes]) -> list[str]:
    """find_all_barcodes в thread-pool — zxing (C-расширение, освобождает GIL)
    и PIL перед каждым анализом не должны блокировать event loop."""
    import asyncio

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, find_all_barcodes, photos)
