import asyncio

from .image_processor import (
    resize,
    generate_placeholder,
)


async def generate_placeholder_async(name: str, emoji: str | None = None) -> bytes:
    """generate_placeholder в thread-pool — тяжёлая генерация 768×1024 JPEG
    (≈150 эмодзи + blur) не должна блокировать event loop."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, generate_placeholder, name, emoji)


__all__ = [
    "resize",
    "generate_placeholder",
    "generate_placeholder_async",
]
