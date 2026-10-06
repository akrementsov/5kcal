import io

from PIL import Image

MAX_SIDE = 1024
JPEG_QUALITY = 85


def resize_image_bytes(image_bytes: bytes) -> bytes:
    # Открываем изображение из байтов
    try:
        img = Image.open(io.BytesIO(image_bytes))
    except Exception as e:
        raise ValueError(f"Не удалось открыть изображение для ресайза: {e}") from e
    # JPEG не поддерживает альфа-канал/палитру (RGBA/LA/P — PNG-скриншоты «как файл»)
    if img.mode != "RGB":
        img = img.convert("RGB")
    width, height = img.size  # Получаем размеры исходного изображения

    # Если изображение уже не превышает максимальный размер, возвращаем как есть
    if max(width, height) <= MAX_SIDE:
        output = io.BytesIO()
        img.save(output, format="JPEG", quality=JPEG_QUALITY)
        return output.getvalue()

    # Вычисляем новые размеры, сохраняя пропорции
    if width >= height:
        new_width = MAX_SIDE
        new_height = int(height * (MAX_SIDE / width))
    else:
        new_height = MAX_SIDE
        new_width = int(width * (MAX_SIDE / height))

    # Ресайзим изображение с использованием высокого качества
    resized_img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
    output = io.BytesIO()
    # Сохраняем ресайзнутое изображение в формате JPEG
    resized_img.save(output, format="JPEG", quality=JPEG_QUALITY)
    return output.getvalue()
