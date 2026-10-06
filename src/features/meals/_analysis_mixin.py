"""AnalysisMixin — Create flow: анализ фотографий и текста (V2, компонентная схема).

Реализует clarification-вопросы для нового анализа: Call 1/Call 2 могут вернуть
status="clarification" (вопрос + черновая гипотеза) — сессия сохраняется в Redis,
вопрос показывается пользователю. В edit-flow (живая UPDATE-сессия) вопросы
запрещены: гипотеза принимается молча, UPDATE-сессия не затирается.
"""

import difflib
import time
from collections.abc import Awaitable, Callable
from typing import Optional

from src.i18n import DEFAULT_LOCALE
from src.core.llm.models import MessageRole, Content
from src.core.llm.meal_model import Meal, MealComponent
from src.core.llm.two_call_models import (
    FoodInfo,
    FoodItemClarification,
    FoodItemError,
    FoodIdentificationErrorCode,
    WeightEstimationErrorCode,
    WeightItemClarification,
    WeightItemError,
    WeightItemOk,
)
from src.core.user_state import config as state_cfg
from src.core.user_state.session import AnalysisSession, CallPhase, SessionMode
from src.core.llm.local_prompts import (
    render_barcode_hints_prompt,
    render_product_context_prompt,
)
from src.core.ui.texts import ErrSvc
from src.core.metrics import (
    counter_inc,
    gauge_inc,
    gauge_dec,
    histogram_observe,
    ANALYSIS_BUCKETS,
    FAST_BUCKETS,
)
from src.core.utils import get_logger
from ._types import AnalysisResult, HistoryEntry, HistoryRole
from ._llm_calls import call_identification, call_weight_estimation
from ._message_builder import _build_two_call_messages

logger = get_logger()

# Диапазоны для UI: фиксированная display-погрешность.
# Из бенчмарка V2 на Gemini: MAPE веса ~19%, bias +5% → ±15% честно
# отражает типичную неопределённость без per-запросного confidence.
DISPLAY_UNCERTAINTY_PCT = 15

# Для событий prompt_injection логируем усечённый сырой ввод пользователя —
# иначе доказать/разобрать инцидент нечем (обычный текст ввода не логируется).
_INJECTION_LOG_MAXLEN = 500


# ─── Модульные хелперы ────────────────────────────────────────────────────────


def _match_component(components: list[dict], name: str) -> Optional[dict]:
    """Находит компонент Call 1 по имени из Call 2 (точно → подстрока → fuzzy)."""
    by_name = {c.get("name", ""): c for c in components}
    if name in by_name:
        return by_name[name]
    lowered = name.lower()
    for comp_name, comp in by_name.items():
        cn = comp_name.lower()
        if lowered in cn or cn in lowered:
            return comp
    close = difflib.get_close_matches(name, list(by_name), n=1, cutoff=0.6)
    if close:
        return by_name[close[0]]
    return None


def _build_meal_from_two_calls(
    food_info: FoodInfo,
    weight_item: WeightItemOk,
) -> Meal:
    """Собирает Meal: веса компонентов из Call 2 × КБЖУ компонентов из Call 1."""
    components = food_info.components

    # Средние КБЖУ по компонентам — fallback для несматчившихся имён
    n = max(len(components), 1)
    avg = {
        key: sum(float(c.get(key, 0.0)) for c in components) / n
        for key in (
            "calories_per_100g",
            "protein_per_100g",
            "fat_per_100g",
            "carbs_per_100g",
        )
    }

    pct = DISPLAY_UNCERTAINTY_PCT

    total_w = 0.0
    cal = prot = fat = carbs = 0.0
    meal_components: list[MealComponent] = []
    for wc in weight_item.components:
        comp = _match_component(components, wc.name)
        if comp is None:
            logger.warning(
                "Компонент Call 2 не сматчился с Call 1, используем средние КБЖУ",
                extra={"component": wc.name},
            )
            comp = avg
        w = wc.weight_g
        total_w += w
        c_cal = w * float(comp.get("calories_per_100g", 0.0)) / 100
        c_prot = w * float(comp.get("protein_per_100g", 0.0)) / 100
        c_fat = w * float(comp.get("fat_per_100g", 0.0)) / 100
        c_carbs = w * float(comp.get("carbs_per_100g", 0.0)) / 100
        cal += c_cal
        prot += c_prot
        fat += c_fat
        carbs += c_carbs

        meal_components.append(
            MealComponent(
                name=wc.name,
                weight_g=round(w, 1),
                calories_kcal=round(c_cal, 1),
                protein_g=round(c_prot, 1),
                fat_g=round(c_fat, 1),
                carbs_g=round(c_carbs, 1),
                confidence=pct,
            )
        )

    if total_w <= 0:
        total_w = weight_item.total_weight_g

    return Meal(
        name=food_info.name,
        emoji=food_info.emoji,
        count=1,
        estimated_weight_g=round(total_w, 1),
        calories_kcal=round(cal, 1),
        protein_g=round(prot, 1),
        fat_g=round(fat, 1),
        carbs_g=round(carbs, 1),
        confidence=pct,
        confidence_reason="",
        components=meal_components,
    )


def _assemble_meal_result(
    chat_id: int, caption: str, food_info: FoodInfo, w_ok: WeightItemOk
) -> AnalysisResult:
    """Собирает карточку из гипотезы Call 1 и весов Call 2 (без LLM-вызовов)."""
    meal = _build_meal_from_two_calls(food_info, w_ok)
    logger.info(
        "Двухвызовный анализ завершён",
        extra={
            "chat_id": chat_id,
            "meal_name": meal.name,
            "total_weight_g": w_ok.total_weight_g,
        },
    )
    return AnalysisResult(meals=[meal], caption=caption)


def _record_analysis_done(outcome: str, started_at: float) -> None:
    gauge_dec("fivekcal_analyses_active")
    histogram_observe(
        "fivekcal_analysis_duration_seconds",
        time.monotonic() - started_at,
        buckets=ANALYSIS_BUCKETS,
        help="Full photo analysis pipeline duration in seconds",
    )
    counter_inc(
        "fivekcal_analysis_total",
        labels={"outcome": outcome},
        help="Total photo analyses by outcome (ok/error)",
    )


def _build_food_item_error_result(item: FoodItemError) -> AnalysisResult:
    if item.error_code == FoodIdentificationErrorCode.PROMPT_INJECTION:
        return AnalysisResult(error=ErrSvc.MEAL_NOT_RECOGNIZED)
    if item.error:
        return AnalysisResult(error_text=item.error)
    if item.error_code == FoodIdentificationErrorCode.MULTIPLE_DISHES:
        return AnalysisResult(error=ErrSvc.MULTIPLE_DISHES)
    return AnalysisResult(error=ErrSvc.MEAL_NOT_RECOGNIZED)


def _append_user_history(
    history: list[HistoryEntry],
    *,
    user_text: Optional[str],
    extra_base64: list[str],
) -> None:
    has_user_text = bool(user_text and user_text.strip())
    if not extra_base64 and not has_user_text:
        return

    entry = HistoryEntry(role=HistoryRole.USER)
    if extra_base64:
        entry["has_photos"] = True
        entry["extra_images"] = extra_base64
    if has_user_text:
        entry["text"] = user_text
    history.append(entry)


# ─── Миксин ───────────────────────────────────────────────────────────────────


class AnalysisMixin:
    """Create flow: анализ фото/текста."""

    async def analyze_photos(
        self,
        photo_bytes: list[bytes],
        user_id: int,
        chat_id: int,
        caption: str,
        locale: str = DEFAULT_LOCALE,
        on_retry: Callable[[], Awaitable[None]] | None = None,
        on_photos_processed: Callable[[], Awaitable[None]] | None = None,
        barcode_hints: set[str] | None = None,
        barcode_products: list | None = None,
        original_msg_ids: list[int] | None = None,
        telegram_file_ids: list[str] | None = None,
    ) -> AnalysisResult:
        """Пайплайн анализа фотографий еды (двухвызовная архитектура)."""
        logger.info(
            "Начинаем анализ фотографий",
            extra={
                "chat_id": chat_id,
                "photos_count": len(photo_bytes),
                "has_caption": bool(caption),
                "has_barcode_products": bool(barcode_products),
            },
        )

        gauge_inc("fivekcal_analyses_active", help="Currently running photo analyses")
        _analysis_t0 = time.monotonic()

        try:
            _t0 = time.monotonic()
            base64_images = await self.image_processor.process_images(photo_bytes)
            _resize_s = time.monotonic() - _t0
            logger.debug(
                "Фото обработаны",
                extra={
                    "chat_id": chat_id,
                    "photos_count": len(base64_images),
                    "resize_s": round(_resize_s, 2),
                },
            )
            histogram_observe(
                "fivekcal_resize_duration_seconds",
                _resize_s,
                buckets=FAST_BUCKETS,
                help="Image resize duration in seconds",
            )
            if on_photos_processed:
                await on_photos_processed()
        except Exception as e:
            gauge_dec("fivekcal_analyses_active")
            counter_inc(
                "fivekcal_analysis_total",
                labels={"outcome": "error"},
                help="Total photo analyses by outcome",
            )
            logger.error(
                "Ошибка при обработке фото", extra={"chat_id": chat_id, "error": str(e)}
            )
            return AnalysisResult(error=ErrSvc.PHOTO_PROCESSING)

        # ── Call 1: идентификация ────────────────────────────────────────────
        call1_content: list[Content] = []
        if barcode_products:
            call1_content.append(
                Content.from_text(render_product_context_prompt(barcode_products))
            )
        elif barcode_hints:
            call1_content.append(
                Content.from_text(render_barcode_hints_prompt(sorted(barcode_hints)))
            )
        call1_content += [Content.image(b64, detail="high") for b64 in base64_images]
        if caption and caption.strip():
            call1_content.append(Content.from_text(caption))

        id_result = await call_identification(
            self.llm,
            user_id,
            [(MessageRole.USER, call1_content)],
            chat_id,
            locale,
            on_retry=on_retry,
        )

        if isinstance(id_result, AnalysisResult):
            _record_analysis_done("error", _analysis_t0)
            return id_result

        if isinstance(id_result, FoodItemError):
            is_injection = (
                id_result.error_code == FoodIdentificationErrorCode.PROMPT_INJECTION
            )
            extra = {
                "chat_id": chat_id,
                "user_id": user_id,
                "error_code": id_result.error_code.value,
                "error": id_result.error,
            }
            if is_injection:
                extra["user_input"] = (caption or "")[:_INJECTION_LOG_MAXLEN]
            (logger.warning if is_injection else logger.info)(
                "Call 1 вернул ошибку идентификации", extra=extra
            )
            # Семантический вердикт модели (не еда / несколько блюд / injection):
            # это НЕ системный сбой, поэтому отдельный outcome "rejected", чтобы
            # AnalysisHighErrorRate не считал корректные отказы ошибками.
            _record_analysis_done("rejected", _analysis_t0)
            return _build_food_item_error_result(id_result)

        if isinstance(id_result, FoodItemClarification):
            return await self._handle_identification_clarification(
                id_result,
                user_id=user_id,
                chat_id=chat_id,
                caption=caption,
                base64_images=base64_images,
                telegram_file_ids=telegram_file_ids or [],
                original_msg_ids=original_msg_ids or [],
                locale=locale,
                on_retry=on_retry,
                analysis_t0=_analysis_t0,
            )

        # id_result is FoodItemOk
        food_info = FoodInfo.from_ok(id_result)
        logger.debug(
            "Call 1 результат",
            extra={
                "chat_id": chat_id,
                "food": food_info.to_dict(),
            },
        )

        # ── Call 2: оценка веса ──────────────────────────────────────────────
        session_ctx = {
            "caption": caption,
            "base64_images": base64_images,
            "telegram_file_ids": telegram_file_ids or [],
            "original_msg_ids": original_msg_ids or [],
        }
        w_result = await self._run_weight_estimation(
            user_id=user_id,
            chat_id=chat_id,
            base64_images=base64_images,
            caption=caption,
            food_info=food_info,
            history=[],
            locale=locale,
            on_retry=on_retry,
            session_ctx=session_ctx,
        )
        _record_analysis_done(
            "clarification" if w_result.clarification else (
                "ok" if (w_result.ok and w_result.meals) else "error"
            ),
            _analysis_t0,
        )
        return w_result

    async def analyze_text(
        self, text: str, user_id: int, chat_id: int, locale: str = DEFAULT_LOCALE
    ) -> AnalysisResult:
        """Анализирует текстовое описание блюда без фотографий."""
        logger.debug(
            "Начинаем текстовый анализ",
            extra={"chat_id": chat_id, "text_len": len(text)},
        )

        gauge_inc("fivekcal_analyses_active", help="Currently running photo analyses")
        _analysis_t0 = time.monotonic()

        id_result = await call_identification(
            self.llm,
            user_id,
            [(MessageRole.USER, [Content.from_text(text)])],
            chat_id,
            locale,
        )
        if isinstance(id_result, AnalysisResult):
            _record_analysis_done("error", _analysis_t0)
            return id_result

        if isinstance(id_result, FoodItemError):
            is_injection = (
                id_result.error_code == FoodIdentificationErrorCode.PROMPT_INJECTION
            )
            extra = {
                "chat_id": chat_id,
                "user_id": user_id,
                "error_code": id_result.error_code.value,
                "error": id_result.error,
            }
            if is_injection:
                extra["user_input"] = text[:_INJECTION_LOG_MAXLEN]
            (logger.warning if is_injection else logger.info)(
                "Call 1 вернул ошибку текстовой идентификации", extra=extra
            )
            # Семантический вердикт модели (не еда / несколько блюд / injection):
            # это НЕ системный сбой, поэтому отдельный outcome "rejected", чтобы
            # AnalysisHighErrorRate не считал корректные отказы ошибками.
            _record_analysis_done("rejected", _analysis_t0)
            return _build_food_item_error_result(id_result)

        if isinstance(id_result, FoodItemClarification):
            return await self._handle_identification_clarification(
                id_result,
                user_id=user_id,
                chat_id=chat_id,
                caption=text,
                base64_images=[],
                telegram_file_ids=[],
                original_msg_ids=[],
                locale=locale,
                analysis_t0=_analysis_t0,
            )

        food_info = FoodInfo.from_ok(id_result)
        logger.info(
            "Текстовая идентификация завершена",
            extra={
                "chat_id": chat_id,
                "meal_name": food_info.name,
                "components_count": len(food_info.components),
            },
        )
        session_ctx = {
            "caption": text,
            "base64_images": [],
            "telegram_file_ids": [],
            "original_msg_ids": [],
        }
        w_result = await self._run_weight_estimation(
            user_id=user_id,
            chat_id=chat_id,
            base64_images=[],
            caption=text,
            food_info=food_info,
            history=[],
            locale=locale,
            session_ctx=session_ctx,
        )
        _record_analysis_done(
            "clarification" if w_result.clarification else (
                "ok" if (w_result.ok and w_result.meals) else "error"
            ),
            _analysis_t0,
        )
        return w_result

    async def _run_weight_estimation(
        self,
        user_id: int,
        chat_id: int,
        base64_images: list[str],
        caption: str,
        food_info: FoodInfo,
        history: list[HistoryEntry],
        locale: str,
        on_retry: Callable[[], Awaitable[None]] | None = None,
        allow_question: bool = True,
        session_ctx: dict | None = None,
    ) -> AnalysisResult:
        """Запускает Call 2 (per-component оценка веса) и собирает Meal."""
        messages = _build_two_call_messages(
            base64_images,
            caption,
            history,
            [],
            None,
            food_info=food_info,
        )
        w_result = await call_weight_estimation(
            self.llm,
            user_id,
            messages,
            chat_id,
            locale,
            on_retry=on_retry,
        )

        if isinstance(w_result, AnalysisResult):
            return w_result

        if isinstance(w_result, WeightItemError):
            is_injection = (
                w_result.error_code == WeightEstimationErrorCode.PROMPT_INJECTION
            )
            extra = {
                "chat_id": chat_id,
                "user_id": user_id,
                "error_code": w_result.error_code,
                "error": w_result.error,
            }
            if is_injection:
                extra["user_input"] = (caption or "")[:_INJECTION_LOG_MAXLEN]
            (logger.warning if is_injection else logger.info)(
                "Call 2 вернул ошибку", extra=extra
            )
            if w_result.error_code == WeightEstimationErrorCode.PROMPT_INJECTION:
                return AnalysisResult(error=ErrSvc.MEAL_NOT_RECOGNIZED)
            if w_result.error:
                return AnalysisResult(error_text=w_result.error)
            return AnalysisResult(error=ErrSvc.GENERAL)

        if isinstance(w_result, WeightItemClarification):
            return await self._handle_weight_clarification(
                w_result,
                user_id=user_id,
                chat_id=chat_id,
                base64_images=base64_images,
                caption=caption,
                food_info=food_info,
                history=history,
                locale=locale,
                allow_question=allow_question,
                session_ctx=session_ctx or {},
            )

        # WeightItemOk
        logger.debug(
            "Call 2 результат",
            extra={
                "chat_id": chat_id,
                "total_weight_g": w_result.total_weight_g,
                "components": [
                    {"name": c.name, "weight_g": c.weight_g}
                    for c in w_result.components
                ],
                "reasoning": w_result.reasoning,
            },
        )
        return _assemble_meal_result(chat_id, caption, food_info, w_result)

    async def _handle_identification_clarification(
        self,
        id_result: FoodItemClarification,
        *,
        user_id: int,
        chat_id: int,
        caption: str,
        base64_images: list[str],
        telegram_file_ids: list[str],
        original_msg_ids: list[int],
        locale: str,
        on_retry: Callable[[], Awaitable[None]] | None = None,
        analysis_t0: float,
    ) -> AnalysisResult:
        """Вопрос от Call 1: показать (если разрешён) или молча принять гипотезу.

        Гипотеза принимается без вопроса когда:
        - киллсвитч CLARIFICATION_ENABLED выключен;
        - в Redis живёт сессия с mode != CREATE (edit-flow: barcode-precheck
          в editing.py вызывает analyze_photos при UPDATE-сессии — её нельзя
          затирать CREATE-сессией clarification-а).
        """
        hypothesis = FoodInfo(
            name=id_result.name,
            emoji=id_result.emoji,
            components=[c.model_dump() for c in id_result.components],
            reasoning=id_result.reasoning,
            verification=id_result.verification,
        )

        allow_clarification = state_cfg.CLARIFICATION_ENABLED
        if allow_clarification:
            existing = await self.storage.get_session(chat_id)
            if existing is not None and existing.mode != SessionMode.CREATE:
                # Defense-in-depth: не затирать чужую (UPDATE) сессию
                allow_clarification = False
                logger.info(
                    "Call 1 clarification подавлен: живая не-CREATE сессия",
                    extra={"chat_id": chat_id, "session_mode": existing.mode},
                )

        if allow_clarification:
            await self.storage.save_session(
                chat_id,
                AnalysisSession(
                    mode=SessionMode.CREATE,
                    caption=caption,
                    base64_images=base64_images,
                    telegram_file_ids=telegram_file_ids,
                    original_msg_ids=original_msg_ids,
                    history=[
                        {"role": HistoryRole.ASSISTANT, "text": id_result.question}
                    ],
                    food_info=hypothesis.to_dict(),
                    call_phase=CallPhase.IDENTIFICATION,
                    round=1,
                ),
            )
            _record_analysis_done("clarification", analysis_t0)
            return AnalysisResult(
                clarification=id_result.question,
                clarification_call="identification",
            )

        # Вопрос запрещён — молча принимаем гипотезу и продолжаем пайплайн
        session_ctx = {
            "caption": caption,
            "base64_images": base64_images,
            "telegram_file_ids": telegram_file_ids,
            "original_msg_ids": original_msg_ids,
        }
        w_result = await self._run_weight_estimation(
            user_id=user_id,
            chat_id=chat_id,
            base64_images=base64_images,
            caption=caption,
            food_info=hypothesis,
            history=[],
            locale=locale,
            on_retry=on_retry,
            allow_question=False,
            session_ctx=session_ctx,
        )
        _record_analysis_done(
            "clarification" if w_result.clarification else (
                "ok" if (w_result.ok and w_result.meals) else "error"
            ),
            analysis_t0,
        )
        return w_result

    async def _handle_weight_clarification(
        self,
        item: WeightItemClarification,
        *,
        user_id: int,
        chat_id: int,
        base64_images: list[str],
        caption: str,
        food_info: FoodInfo,
        history: list[HistoryEntry],
        locale: str,
        allow_question: bool,
        session_ctx: dict,
    ) -> AnalysisResult:
        """Вопрос от Call 2: показать (если разрешён) или единое правило."""
        if allow_question and state_cfg.CLARIFICATION_ENABLED:
            session = await self.storage.get_session(chat_id)
            # Defense-in-depth: запрет clarification если текущая сессия — UPDATE
            # (edit-flow не должен превращать UPDATE-сессию в CREATE или затирать её)
            if session is None or session.mode == SessionMode.CREATE:
                weight_info = {
                    "components": [c.model_dump() for c in item.components],
                    "total_weight_g": item.total_weight_g,
                }
                new_history = list(history) + [
                    {"role": HistoryRole.ASSISTANT, "text": item.question}
                ]
                if session is None:
                    session = AnalysisSession(
                        mode=SessionMode.CREATE,
                        caption=caption,
                        base64_images=base64_images,
                        telegram_file_ids=session_ctx.get("telegram_file_ids", []),
                        original_msg_ids=session_ctx.get("original_msg_ids", []),
                        food_info=food_info.to_dict(),
                        history=new_history,
                        call_phase=CallPhase.WEIGHT,
                        weight_info=weight_info,
                    )
                    await self.storage.save_session(chat_id, session)
                else:
                    await self.storage.update_session(
                        chat_id,
                        call_phase=CallPhase.WEIGHT,
                        weight_info=weight_info,
                        history=new_history,
                        food_info=food_info.to_dict(),
                    )
                return AnalysisResult(
                    clarification=item.question, clarification_call="weight"
                )

        # ── Единое правило «вопрос запрещён» ─────────────────────────────────
        if item.total_weight_g > 0:
            w_ok = WeightItemOk(
                components=item.components,
                total_weight_g=item.total_weight_g,
                reasoning="",
                verification="",
            )
            return _assemble_meal_result(chat_id, caption, food_info, w_ok)

        # Гипотезы веса нет — один принудительный повторный Call 2
        forced_history = list(history) + [
            {"role": HistoryRole.ASSISTANT, "text": item.question},
            {
                "role": HistoryRole.USER,
                "text": "Пользователь недоступен. Дай лучшую оценку веса, не задавай вопрос.",
            },
        ]
        messages = _build_two_call_messages(
            base64_images, caption, forced_history, [], None, food_info=food_info
        )
        forced = await call_weight_estimation(
            self.llm, user_id, messages, chat_id, locale
        )
        if isinstance(forced, WeightItemOk):
            return _assemble_meal_result(chat_id, caption, food_info, forced)
        if isinstance(forced, WeightItemClarification) and forced.total_weight_g > 0:
            w_ok = WeightItemOk(
                components=forced.components,
                total_weight_g=forced.total_weight_g,
                reasoning="",
                verification="",
            )
            return _assemble_meal_result(chat_id, caption, food_info, w_ok)
        if isinstance(forced, AnalysisResult):
            return forced
        logger.warning(
            "Принудительный Call 2 не дал оценку веса", extra={"chat_id": chat_id}
        )
        return AnalysisResult(error=ErrSvc.GENERAL)
