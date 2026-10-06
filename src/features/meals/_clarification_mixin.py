"""ClarificationMixin — продолжение анализа после уточняющего вопроса (V2)."""

from src.i18n import DEFAULT_LOCALE

from src.core.llm.two_call_models import (
    FoodInfo,
    FoodItemError,
    FoodItemClarification,
    FoodItemOk,
    WeightComponent,
    WeightItemOk,
)
from src.core.ui.texts import ErrSvc
from src.core.user_state.session import CallPhase, SessionMode
from src.core.utils import get_logger
from ._types import AnalysisResult, HistoryRole
from ._llm_calls import call_identification
from ._message_builder import _build_two_call_messages
from ._analysis_mixin import _assemble_meal_result, _build_food_item_error_result

logger = get_logger()


class ClarificationMixin:
    """Продолжение CREATE-сессии: ответ пользователя или авто-продолжение."""

    async def _get_create_session(self, chat_id: int):
        session = await self.storage.get_session(chat_id)
        if session is None or session.mode != SessionMode.CREATE:
            return None
        return session

    def _session_ctx(self, session) -> dict:
        return {
            "telegram_file_ids": session.telegram_file_ids,
            "original_msg_ids": session.original_msg_ids,
        }

    async def answer_clarification(
        self, chat_id: int, user_text: str, user_id: int, locale: str = DEFAULT_LOCALE
    ) -> AnalysisResult:
        session = await self._get_create_session(chat_id)
        if session is None:
            return AnalysisResult(error=ErrSvc.SESSION_EXPIRED)

        history = list(session.history) + [
            {"role": HistoryRole.USER, "text": user_text}
        ]
        food_info = (
            FoodInfo.from_dict(session.food_info) if session.food_info else None
        )

        if session.call_phase == CallPhase.WEIGHT:
            # Повторный Call 2 с диалогом; его повторный вопрос запрещён
            result = await self._run_weight_estimation(
                user_id=user_id,
                chat_id=chat_id,
                base64_images=session.base64_images,
                caption=session.caption,
                food_info=food_info,
                history=history,
                locale=locale,
                allow_question=False,
                session_ctx=self._session_ctx(session),
            )
            await self.storage.clear_session(chat_id)
            return result

        # call_phase == IDENTIFICATION: повторный Call 1 с диалогом
        messages = _build_two_call_messages(
            session.base64_images, session.caption, history, [], None
        )
        id_result = await call_identification(
            self.llm, user_id, messages, chat_id, locale
        )
        if isinstance(id_result, AnalysisResult):
            await self.storage.clear_session(chat_id)
            return id_result
        if isinstance(id_result, FoodItemError):
            await self.storage.clear_session(chat_id)
            return _build_food_item_error_result(id_result)
        if isinstance(id_result, FoodItemClarification):
            # Повторный вопрос от Call 1 запрещён — принимаем гипотезу
            id_result = FoodItemOk(
                name=id_result.name,
                emoji=id_result.emoji,
                components=id_result.components,
                reasoning=id_result.reasoning,
                verification=id_result.verification,
            )

        new_food_info = FoodInfo.from_ok(id_result)
        await self.storage.update_session(
            chat_id, history=history, food_info=new_food_info.to_dict()
        )
        # Call 2 после ответа имеет право спросить (пользователь вовлечён)
        result = await self._run_weight_estimation(
            user_id=user_id,
            chat_id=chat_id,
            base64_images=session.base64_images,
            caption=session.caption,
            food_info=new_food_info,
            history=history,
            locale=locale,
            allow_question=True,
            session_ctx=self._session_ctx(session),
        )
        if result.clarification is None:
            await self.storage.clear_session(chat_id)
        return result

    async def proceed_clarification(
        self, chat_id: int, user_id: int, locale: str = DEFAULT_LOCALE
    ) -> AnalysisResult:
        session = await self._get_create_session(chat_id)
        if session is None:
            return AnalysisResult(error=ErrSvc.SESSION_EXPIRED)

        food_info = (
            FoodInfo.from_dict(session.food_info) if session.food_info else None
        )

        if session.call_phase == CallPhase.WEIGHT and session.weight_info:
            # Карточка из черновика — без LLM
            w_ok = WeightItemOk(
                components=[
                    WeightComponent(**c)
                    for c in session.weight_info.get("components", [])
                ],
                total_weight_g=session.weight_info.get("total_weight_g", 0.0),
                reasoning="",
                verification="",
            )
            await self.storage.clear_session(chat_id)
            if w_ok.total_weight_g > 0:
                return _assemble_meal_result(
                    chat_id, session.caption, food_info, w_ok
                )
            # Черновика нет (total=0) — принудительный Call 2 через единое правило
            return await self._run_weight_estimation(
                user_id=user_id,
                chat_id=chat_id,
                base64_images=session.base64_images,
                caption=session.caption,
                food_info=food_info,
                history=session.history,
                locale=locale,
                allow_question=False,
                session_ctx=self._session_ctx(session),
            )

        # call_phase == IDENTIFICATION: пользователь не ответил → Call 2 молчит
        result = await self._run_weight_estimation(
            user_id=user_id,
            chat_id=chat_id,
            base64_images=session.base64_images,
            caption=session.caption,
            food_info=food_info,
            history=session.history,
            locale=locale,
            allow_question=False,
            session_ctx=self._session_ctx(session),
        )
        await self.storage.clear_session(chat_id)
        return result
