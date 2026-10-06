"""
ImageProcessor — инфраструктурный класс для обработки изображений.

Оборачивает resize в ProcessPoolExecutor (CPU-bound операция).
Инстанциируется один раз в main.py, передаётся в сервисы через конструктор.
"""

import asyncio
from concurrent.futures import ProcessPoolExecutor

from src.core.image_processing import resize


class ImageProcessor:
    """Запускает обработку изображений в ProcessPoolExecutor."""

    def __init__(self, executor: ProcessPoolExecutor):
        self._executor = executor

    async def process_images(self, images: list[bytes]) -> list[str]:
        """Ресайзит список изображений. Возвращает список base64-строк."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._executor, resize, images)

    def shutdown(self, wait: bool = False) -> None:
        self._executor.shutdown(wait=wait)
