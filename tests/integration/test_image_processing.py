"""Тесты core/image_processing — resize_image_bytes, generate_placeholder, resize batch."""

import base64
import io

import pytest
from PIL import Image

from src.core.image_processing.image_processor import generate_placeholder, resize
from src.core.image_processing.resizer import MAX_SIDE, resize_image_bytes


def _jpeg_bytes(width: int, height: int, color=(255, 0, 0)) -> bytes:
    """Создаёт валидный JPEG заданного размера."""
    img = Image.new("RGB", (width, height), color)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


class TestResizeImageBytes:
    @pytest.mark.parametrize(
        "src_w, src_h, expected_w, expected_h",
        [
            # Большое изображение — длинная сторона ужимается до MAX_SIDE
            (2048, 1024, MAX_SIDE, MAX_SIDE // 2),
            (1024, 2048, MAX_SIDE // 2, MAX_SIDE),
            # Квадрат больше MAX_SIDE
            (2000, 2000, MAX_SIDE, MAX_SIDE),
            # Граница ровно MAX_SIDE — не меняется
            (MAX_SIDE, MAX_SIDE, MAX_SIDE, MAX_SIDE),
            (MAX_SIDE, 500, MAX_SIDE, 500),
            # Меньше MAX_SIDE — апскейл не делается
            (500, 300, 500, 300),
            (100, 100, 100, 100),
        ],
    )
    def test_resize_preserves_aspect_and_bounds(
        self, src_w, src_h, expected_w, expected_h
    ):
        result = resize_image_bytes(_jpeg_bytes(src_w, src_h))

        img = Image.open(io.BytesIO(result))
        assert img.size == (expected_w, expected_h)

    def test_resize_output_is_decodable_jpeg(self):
        result = resize_image_bytes(_jpeg_bytes(2000, 1500))

        # Должен открываться без ошибок
        img = Image.open(io.BytesIO(result))
        assert img.format == "JPEG"

    def test_invalid_bytes_raises_value_error(self):
        with pytest.raises(ValueError, match="Не удалось открыть"):
            resize_image_bytes(b"not an image")

    def test_empty_bytes_raises_value_error(self):
        with pytest.raises(ValueError):
            resize_image_bytes(b"")


class TestGeneratePlaceholder:
    def test_returns_valid_jpeg(self):
        result = generate_placeholder("Test Dish")

        img = Image.open(io.BytesIO(result))
        assert img.format == "JPEG"

    def test_dimensions_are_768x1024(self):
        result = generate_placeholder("Test Dish")

        img = Image.open(io.BytesIO(result))
        assert img.size == (768, 1024)

    def test_accepts_emoji(self):
        result = generate_placeholder("Меню", emoji="🍣")

        img = Image.open(io.BytesIO(result))
        assert img.size == (768, 1024)

    def test_empty_name_does_not_crash(self):
        result = generate_placeholder("")

        img = Image.open(io.BytesIO(result))
        assert img.format == "JPEG"

    def test_long_name_wraps_lines(self):
        """Длинное название не должно падать (line wrapping)."""
        result = generate_placeholder(
            "Очень длинное название блюда которое нужно перенести на много строк"
        )

        img = Image.open(io.BytesIO(result))
        assert img.size == (768, 1024)


class TestResizeBatch:
    def test_returns_base64_for_each_input(self):
        inputs = [_jpeg_bytes(2000, 1000), _jpeg_bytes(500, 500)]

        result = resize(inputs)

        assert len(result) == 2
        # Должно быть валидным base64
        for b64 in result:
            decoded = base64.b64decode(b64)
            img = Image.open(io.BytesIO(decoded))
            assert img.format == "JPEG"

    def test_empty_list_returns_empty(self):
        assert resize([]) == []

    def test_invalid_in_batch_propagates(self):
        """Ошибка в одном элементе пробрасывается — batch не маскирует."""
        with pytest.raises(ValueError):
            resize([_jpeg_bytes(100, 100), b"not an image"])


class TestResizeNonRgbModes:
    """Регрессия: PNG/WebP с альфа-каналом (скриншоты «как файл») падали
    с OSError: cannot write mode RGBA as JPEG."""

    def _png_bytes(self, mode: str, size: tuple[int, int]) -> bytes:
        color = {"RGBA": (255, 0, 0, 128), "LA": (128, 200), "P": 3}[mode]
        img = Image.new(mode, size, color)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    @pytest.mark.parametrize("mode", ["RGBA", "LA", "P"])
    def test_small_image_converted_to_jpeg(self, mode):
        """Ветка «без ресайза» (<= MAX_SIDE) тоже должна конвертировать в RGB."""
        result = resize_image_bytes(self._png_bytes(mode, (100, 100)))

        img = Image.open(io.BytesIO(result))
        assert img.format == "JPEG"

    def test_large_rgba_converted_to_jpeg(self):
        """Ветка с ресайзом: RGBA > MAX_SIDE."""
        result = resize_image_bytes(self._png_bytes("RGBA", (2048, 1024)))

        img = Image.open(io.BytesIO(result))
        assert img.format == "JPEG"
        assert img.size == (MAX_SIDE, MAX_SIDE // 2)
