from .resizer import resize_image_bytes
import base64
import io
import random

from PIL import Image, ImageDraw, ImageFont, ImageFilter

_FONT_PATHS = [
    "/usr/share/fonts/truetype/custom/Helvetica.ttc",  # Docker (bundled)
    "/System/Library/Fonts/Helvetica.ttc",  # macOS
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",  # Linux fallback
]
_EMOJI_FONT_PATHS = [
    "/usr/share/fonts/truetype/custom/Apple Color Emoji.ttc",  # Docker (bundled)
    "/System/Library/Fonts/Apple Color Emoji.ttc",  # macOS
]
_BG_COLOR = (255, 248, 240)
_TEXT_COLOR = (45, 95, 90)
_FALLBACK_EMOJIS = ["🍽️", "🥣"]
_PATTERN_EMOJIS = ["🥗", "🍜", "🥩", "🥦", "🍳", "🥕", "🫐", "🥑", "🍋", "🧆"]


def _load_font(paths: list[str], size: int, index: int = 0) -> ImageFont.FreeTypeFont:
    indices = [index, 0] if index != 0 else [0]
    for path in paths:
        for idx in indices:
            try:
                return ImageFont.truetype(path, size, index=idx)
            except OSError:
                continue
    return ImageFont.load_default(size=size)


def generate_placeholder(meal_name: str, emoji: str | None = None) -> bytes:
    """Генерирует JPEG-заглушку с названием блюда, эмодзи блюда и паттерном."""
    W, H = 768, 1024

    # Паттерн из мелких эмодзи
    pattern = Image.new("RGB", (W, H), _BG_COLOR)
    draw_p = ImageDraw.Draw(pattern)
    small_font = _load_font(_EMOJI_FONT_PATHS, 32)
    step = 72
    for row, y in enumerate(range(-10, H + step, step)):
        for col, x in enumerate(range(-10, W + step, step)):
            pat_emoji = _PATTERN_EMOJIS[(row * 3 + col) % len(_PATTERN_EMOJIS)]
            ox = (step // 2) if row % 2 else 0
            draw_p.text((x + ox, y), pat_emoji, font=small_font, embedded_color=True)
    pattern = pattern.filter(ImageFilter.GaussianBlur(radius=0.8))
    bg = Image.new("RGB", (W, H), _BG_COLOR)
    img = Image.blend(pattern, bg, alpha=0.94)
    draw = ImageDraw.Draw(img)

    # Главное эмодзи — от AI или fallback
    main_emoji = emoji if emoji else random.choice(_FALLBACK_EMOJIS)
    emoji_font = _load_font(_EMOJI_FONT_PATHS, 160)
    ew = draw.textlength(main_emoji, font=emoji_font)
    draw.text(
        ((W - ew) / 2, H // 2 - 260), main_emoji, font=emoji_font, embedded_color=True
    )

    # Название блюда
    text_font = _load_font(_FONT_PATHS, 72, index=1)
    words = meal_name.split()
    lines, current = [], ""
    for word in words:
        test = (current + " " + word).strip()
        if draw.textlength(test, font=text_font) > W - 120:
            if current:
                lines.append(current)
            current = word
        else:
            current = test
    if current:
        lines.append(current)

    y = H // 2 + 40
    for line in lines:
        x = (W - draw.textlength(line, font=text_font)) / 2
        draw.text((x, y), line, fill=_TEXT_COLOR, font=text_font)
        y += 90

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


def resize(images_bytes: list[bytes]) -> list[str]:
    """Ресайзит изображения и возвращает список base64-строк."""
    return [base64.b64encode(resize_image_bytes(b)).decode("utf-8") for b in images_bytes]
