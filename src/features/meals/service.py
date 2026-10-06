"""
MealService — сервис анализа блюд.

Все зависимости (DB, Redis, LLM, ImageProcessor) принимаются через конструктор.
Логика разбита по миксинам:
  - AnalysisMixin: Create flow (анализ фото/текста, уточнения)
  - EditingMixin: Update flow (редактирование существующего блюда)
"""

from src.core.database.database import Database
from src.core.user_state.storage import RedisStorage
from src.core.llm.protocol import LLMClient
from src.core.image_processing.processor import ImageProcessor
from ._types import AnalysisResult
from ._analysis_mixin import AnalysisMixin
from ._clarification_mixin import ClarificationMixin
from ._editing_mixin import EditingMixin

# Re-export для обратной совместимости
__all__ = ["MealService", "AnalysisResult"]


class MealService(AnalysisMixin, ClarificationMixin, EditingMixin):
    """Сервис анализа и редактирования блюд."""

    def __init__(
        self,
        db: Database,
        storage: RedisStorage,
        llm: LLMClient,
        image_processor: ImageProcessor,
    ):
        self.db = db
        self.storage = storage
        self.llm = llm
        self.image_processor = image_processor

    async def _resize_extra_photos(
        self, photo_bytes: list[bytes], chat_id: int
    ) -> list[str]:
        """Ресайзит дополнительные фото. Возвращает список base64-строк."""
        return await self.image_processor.process_images(photo_bytes)
