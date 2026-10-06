"""EditingMixin — Update flow: редактирование существующего блюда (V2).

Clarification-диалоги удалены: редактирование — один проход
Call 1 (с текстом/фото пользователя) → Call 2 → обновлённый Meal.
"""

from typing import Optional

from src.i18n import DEFAULT_LOCALE

from src.core.database import db as db_funcs
from src.core.llm.two_call_models import FoodInfo, FoodItemError
from src.core.ui.texts import ErrSvc
from src.core.utils import get_logger
from ._types import AnalysisResult, HistoryEntry
from ._llm_calls import call_identification
from ._message_builder import _build_two_call_messages
from ._analysis_mixin import (
    _append_user_history,
    _build_food_item_error_result,
)

logger = get_logger()


class EditingMixin:
    """Update flow: редактирование блюда одним проходом."""

    async def start_editing(
        self,
        meal_id: int,
        user_text: Optional[str],
        extra_photo_bytes: Optional[list[bytes]],
        chat_id: int,
        user_id: int,
        loading_msg_id: Optional[int],
        meal_card_msg_id: Optional[int],
        locale: str = DEFAULT_LOCALE,
        on_photos_processed=None,
        original_base64_images: Optional[list[str]] = None,
    ) -> AnalysisResult:
        """Редактирование блюда: полный переанализ с учётом правок пользователя.

        original_base64_images — base64 оригинальных фото, скачанных из Telegram.
        """
        logger.info(
            "Начинаем редактирование блюда",
            extra={
                "chat_id": chat_id,
                "meal_id": meal_id,
                "has_text": bool(user_text),
                "extra_photos": len(extra_photo_bytes or []),
            },
        )
        try:
            with self.db.session() as session:
                meal_record = db_funcs.get_meal(session, meal_id, user_id=user_id)
                if not meal_record:
                    return AnalysisResult(error=ErrSvc.MEAL_NOT_RECOGNIZED)
                caption = meal_record.caption or ""
        except Exception as e:
            logger.error(
                "Ошибка загрузки блюда для редактирования",
                extra={"chat_id": chat_id, "meal_id": meal_id, "error": str(e)},
            )
            return AnalysisResult(error=ErrSvc.DB_READ)

        base64_images = list(original_base64_images or [])

        extra_base64: list[str] = []
        if extra_photo_bytes:
            try:
                extra_base64 = await self._resize_extra_photos(
                    extra_photo_bytes, chat_id
                )
            except Exception as e:
                logger.error(
                    "Ошибка обработки фото для редактирования",
                    extra={"chat_id": chat_id, "error": str(e)},
                )
                return AnalysisResult(error=ErrSvc.EXTRA_PHOTO)

        if on_photos_processed:
            await on_photos_processed()

        history: list[HistoryEntry] = []
        _append_user_history(history, user_text=user_text, extra_base64=extra_base64)
        if not history:
            return AnalysisResult(error=ErrSvc.PHOTO_PROCESSING)

        base64_images = base64_images + extra_base64

        messages = _build_two_call_messages(base64_images, caption, history, [], None)
        id_result = await call_identification(
            self.llm,
            user_id,
            messages,
            chat_id,
            locale,
        )

        if isinstance(id_result, AnalysisResult):
            return id_result

        if isinstance(id_result, FoodItemError):
            return _build_food_item_error_result(id_result)

        food_info = FoodInfo.from_ok(id_result)
        logger.info(
            "Call 1 завершён при редактировании, переходим к Call 2",
            extra={"chat_id": chat_id, "meal_name": food_info.name},
        )
        return await self._run_weight_estimation(
            user_id=user_id,
            chat_id=chat_id,
            base64_images=base64_images,
            caption=caption,
            food_info=food_info,
            history=history,
            locale=locale,
            allow_question=False,
        )
