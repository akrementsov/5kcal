"""Сервисный слой clarification: сессии, единое правило «вопрос запрещён»."""

import pytest
from unittest.mock import patch

from src.core.user_state import config as state_cfg
from src.core.user_state.session import CallPhase, SessionMode
from tests.helpers import (
    make_identification_response,
    make_weight_response,
    make_component,
)
from tests.mocks import MockOpenAIClient, SequentialMockOpenAIClient


def _clarify_identification(question="Похоже на творог 5%. Верно?"):
    return make_identification_response(
        status="clarification",
        name="Творог",
        emoji="🥛",
        components=[make_component(name="Творог 5%")],
        question=question,
    )


def _clarify_weight(question="На вид ~180 г. Верно?", total=180.0):
    components = (
        [{"name": "Творог 5%", "weight_g": total}] if total > 0 else []
    )
    return make_weight_response(
        status="clarification",
        components=components,
        total_weight_g=total,
        question=question,
    )


@pytest.fixture(autouse=True)
def _enable_clarification(monkeypatch):
    monkeypatch.setattr(state_cfg, "CLARIFICATION_ENABLED", True)


class TestCall1Clarification:
    async def test_photo_clarification_saves_session_and_returns_question(
        self, test_redis, meal_service_factory
    ):
        svc = meal_service_factory(
            MockOpenAIClient(identification=_clarify_identification())
        )
        result = await svc.analyze_photos(
            [b"photo"], user_id=1, chat_id=1, caption="творог",
            original_msg_ids=[42], telegram_file_ids=["f1"],
        )

        assert result.clarification == "Похоже на творог 5%. Верно?"
        assert result.clarification_call == "identification"
        assert result.ok and result.meals == []

        s = await test_redis.get_session(1)
        assert s.mode == SessionMode.CREATE
        assert s.call_phase == CallPhase.IDENTIFICATION
        assert s.food_info["name"] == "Творог"
        assert s.history[0]["role"] == "assistant"
        assert s.original_msg_ids == [42]
        assert s.telegram_file_ids == ["f1"]
        assert s.round == 1

    async def test_killswitch_accepts_hypothesis_silently(
        self, test_redis, meal_service_factory, monkeypatch
    ):
        monkeypatch.setattr(state_cfg, "CLARIFICATION_ENABLED", False)
        svc = meal_service_factory(
            MockOpenAIClient(identification=_clarify_identification())
        )
        result = await svc.analyze_photos([b"p"], 1, 1, "творог")

        assert result.clarification is None
        assert result.ok and len(result.meals) == 1  # гипотеза → Call 2 → карточка
        assert await test_redis.get_session(1) is None

    async def test_photo_call1_clarification_with_update_session_returns_meal(
        self, test_redis, meal_service_factory
    ):
        """Call 1 возвращает clarification при живой UPDATE-сессии →
        clarification запрещён, гипотеза принимается, UPDATE-сессия не тронута.
        Путь-триггер: barcode-precheck при редактировании (editing.py) вызывает
        analyze_photos при mode=UPDATE.
        """
        from src.core.user_state.session import AnalysisSession

        # Предустановим UPDATE-сессию (edit-flow)
        update_session = AnalysisSession(
            mode=SessionMode.UPDATE,
            meal_id=42,
            loading_msg_id=10,
            meal_card_msg_id=20,
        )
        await test_redis.save_session(1, update_session)

        client = SequentialMockOpenAIClient(
            identification=[_clarify_identification()],
            weight=[make_weight_response()],
        )
        svc = meal_service_factory(client)

        result = await svc.analyze_photos(
            [b"photo"], user_id=1, chat_id=1, caption="творог",
        )

        # Clarification запрещён при UPDATE-сессии
        assert result.clarification is None, (
            f"clarification НЕ должен вернуться при UPDATE-сессии: {result.clarification!r}"
        )
        assert result.ok is True
        assert len(result.meals) > 0, "ожидается карточка из гипотезы"

        # UPDATE-сессия не тронута
        session = await test_redis.get_session(1)
        assert session is not None, "UPDATE-сессия должна остаться в Redis"
        assert session.mode == SessionMode.UPDATE, (
            f"режим сессии не должен измениться: {session.mode!r}"
        )
        assert session.meal_id == 42, "meal_id UPDATE-сессии не тронут"

    async def test_text_call1_clarification_with_update_session_returns_meal(
        self, test_redis, meal_service_factory
    ):
        """analyze_text: тот же guard — UPDATE-сессия не затирается Call 1-вопросом."""
        from src.core.user_state.session import AnalysisSession

        await test_redis.save_session(
            1, AnalysisSession(mode=SessionMode.UPDATE, meal_id=7)
        )

        client = SequentialMockOpenAIClient(
            identification=[_clarify_identification()],
            weight=[make_weight_response()],
        )
        svc = meal_service_factory(client)

        result = await svc.analyze_text("творог", user_id=1, chat_id=1)

        assert result.clarification is None
        assert result.ok and len(result.meals) > 0
        session = await test_redis.get_session(1)
        assert session is not None and session.mode == SessionMode.UPDATE
        assert session.meal_id == 7


class TestCall2Clarification:
    async def test_weight_question_extends_session(
        self, test_redis, meal_service_factory
    ):
        svc = meal_service_factory(MockOpenAIClient(weight=_clarify_weight()))
        result = await svc.analyze_photos([b"p"], 1, 1, "")

        assert result.clarification_call == "weight"
        s = await test_redis.get_session(1)
        assert s.call_phase == CallPhase.WEIGHT
        assert s.weight_info["total_weight_g"] == 180.0

    async def test_forbidden_with_hypothesis_assembles(
        self, test_redis, meal_service_factory, monkeypatch
    ):
        """Киллсвитч выключен: Call 2 clarification с total>0 → карточка молча."""
        monkeypatch.setattr(state_cfg, "CLARIFICATION_ENABLED", False)
        svc = meal_service_factory(MockOpenAIClient(weight=_clarify_weight()))
        result = await svc.analyze_photos([b"p"], 1, 1, "")

        assert result.clarification is None
        assert result.ok and result.meals[0].estimated_weight_g == 180.0

    async def test_forbidden_zero_total_forces_one_recall(
        self, test_redis, meal_service_factory, monkeypatch
    ):
        """total=0 без права вопроса → ровно один принудительный Call 2."""
        monkeypatch.setattr(state_cfg, "CLARIFICATION_ENABLED", False)
        client = SequentialMockOpenAIClient(
            weight=[_clarify_weight(total=0.0), make_weight_response()]
        )
        svc = meal_service_factory(client)
        result = await svc.analyze_photos([b"p"], 1, 1, "")

        assert result.ok and len(result.meals) == 1
        assert client._w_index == 1  # оба ответа израсходованы: 1 clarification + 1 форс


class TestAnswerClarification:
    async def test_answer_to_call1_reruns_and_displays(
        self, test_redis, meal_service_factory
    ):
        """Ответ на вопрос Call 1 → повторный Call 1 (ok) → Call 2 → карточка."""
        client = SequentialMockOpenAIClient(
            identification=[_clarify_identification(), make_identification_response()],
            weight=[make_weight_response()],
        )
        svc = meal_service_factory(client)
        await svc.analyze_photos([b"p"], 1, 1, "творог")

        result = await svc.answer_clarification(1, "обычный 5%", user_id=1)

        assert result.ok and len(result.meals) == 1
        assert await test_redis.get_session(1) is None  # сессия очищена
        assert client._id_index == 1  # Call 1 вызван дважды

    async def test_answer_to_call2_reruns_weight_only(
        self, test_redis, meal_service_factory
    ):
        client = SequentialMockOpenAIClient(
            identification=[make_identification_response()],
            weight=[_clarify_weight(), make_weight_response(total_weight_g=250.0,
                components=[{"name": "Тестовый компонент", "weight_g": 250.0}])],
        )
        svc = meal_service_factory(client)
        await svc.analyze_photos([b"p"], 1, 1, "")

        result = await svc.answer_clarification(1, "250 грамм", user_id=1)

        assert result.ok and result.meals[0].estimated_weight_g == 250.0
        assert client._id_index == 0  # Call 1 повторно НЕ вызывался

    async def test_second_call1_clarification_forced_to_hypothesis(
        self, test_redis, meal_service_factory
    ):
        """Повторный вопрос от Call 1 после ответа — запрещён, гипотеза принимается."""
        client = SequentialMockOpenAIClient(
            identification=[_clarify_identification(), _clarify_identification("Ещё вопрос?")],
            weight=[make_weight_response()],
        )
        svc = meal_service_factory(client)
        await svc.analyze_photos([b"p"], 1, 1, "")

        result = await svc.answer_clarification(1, "не знаю", user_id=1)

        assert result.clarification is None
        assert result.ok and len(result.meals) == 1

    async def test_no_session_returns_session_expired(self, test_redis, meal_service_factory):
        from src.core.ui.texts import ErrSvc

        svc = meal_service_factory(MockOpenAIClient())
        result = await svc.answer_clarification(1, "текст", user_id=1)
        assert result.error == ErrSvc.SESSION_EXPIRED


class TestEditFlowClarificationGuard:
    """Фикс 1: clarification не должен проникать в edit-flow (UPDATE-сессия)."""

    async def test_edit_flow_weight_clarification_returns_meal_not_clarification(
        self, test_redis, meal_service_factory, user_service, test_db, monkeypatch
    ):
        """start_editing: Call 2 возвращает weight-clarification с гипотезой →
        результат ok=True, meals непустой, clarification=None.
        UPDATE-сессия в Redis не превращается в CREATE и не затирается.
        """
        from tests.helpers import save_test_meal, make_weight_response, make_component
        from tests.mocks import SequentialMockOpenAIClient
        from src.core.user_state.session import AnalysisSession, SessionMode
        from tests.integration.test_meal_service import make_identification_v2

        monkeypatch.setattr(state_cfg, "CLARIFICATION_ENABLED", True)

        user_service.get_or_create(user_id=1)
        meal_id = save_test_meal(test_db, user_id=1)

        # Предустановим UPDATE-сессию в Redis (как если бы пользователь нажал «редактировать»)
        update_session = AnalysisSession(
            mode=SessionMode.UPDATE,
            meal_id=meal_id,
            loading_msg_id=10,
            meal_card_msg_id=20,
        )
        await test_redis.save_session(1, update_session)

        # Call 2 возвращает clarification с непустой гипотезой (total_weight_g > 0)
        # Компоненты Call 2 имеют только name+weight_g (не description/placement и т.д.)
        weight_clarification = make_weight_response(
            status="clarification",
            components=[{"name": "Тестовый компонент", "weight_g": 150.0}],
            total_weight_g=150.0,
            question="На вид ~150 г. Верно?",
        )
        client = SequentialMockOpenAIClient(
            identification=[make_identification_v2()],
            weight=[weight_clarification],
        )
        svc = meal_service_factory(client)

        result = await svc.start_editing(
            meal_id=meal_id,
            user_text="уточни вес",
            extra_photo_bytes=None,
            chat_id=1,
            user_id=1,
            loading_msg_id=10,
            meal_card_msg_id=20,
            original_base64_images=["base64data"],
        )

        # Clarification запрещён в edit-flow — должна вернуться карточка
        assert result.ok is True, f"expected ok=True, got error={result.error}"
        assert len(result.meals) > 0, "ожидается непустой список meals"
        assert result.clarification is None, (
            f"clarification НЕ должен быть в edit-flow, получили: {result.clarification!r}"
        )

        # UPDATE-сессия НЕ должна быть превращена в CREATE
        session = await test_redis.get_session(1)
        if session is not None:
            assert session.mode == SessionMode.UPDATE, (
                f"сессия не должна стать CREATE, получили mode={session.mode!r}"
            )


class TestProceedClarification:
    async def test_proceed_weight_assembles_without_llm(
        self, test_redis, meal_service_factory
    ):
        """Таймаут по вопросу Call 2 → карточка из черновика, ноль LLM-вызовов."""
        client = SequentialMockOpenAIClient(
            identification=[make_identification_response()],
            weight=[_clarify_weight(total=180.0)],
        )
        svc = meal_service_factory(client)
        await svc.analyze_photos([b"p"], 1, 1, "")
        id_calls, w_calls = client._id_index, client._w_index

        result = await svc.proceed_clarification(1, user_id=1)

        assert result.ok and result.meals[0].estimated_weight_g == 180.0
        assert (client._id_index, client._w_index) == (id_calls, w_calls)  # без LLM
        assert await test_redis.get_session(1) is None

    async def test_proceed_identification_runs_call2_without_question(
        self, test_redis, meal_service_factory
    ):
        """Таймаут по вопросу Call 1 → Call 2; его вопрос подавлен (allow_question=False)."""
        client = SequentialMockOpenAIClient(
            identification=[_clarify_identification()],
            weight=[_clarify_weight(total=175.0)],  # Call 2 пытается спросить
        )
        svc = meal_service_factory(client)
        await svc.analyze_photos([b"p"], 1, 1, "")

        result = await svc.proceed_clarification(1, user_id=1)

        assert result.clarification is None  # вопрос Call 2 подавлен
        assert result.ok and result.meals[0].estimated_weight_g == 175.0


class TestCall2ClarificationMetric:
    """Фикс 2: метрика outcome='clarification' при Call 2 weight-clarification."""

    async def test_call2_clarification_records_clarification_outcome(
        self, test_redis, meal_service_factory
    ):
        """analyze_photos: Call 2 возвращает clarification → _record_analysis_done('clarification')."""
        svc = meal_service_factory(MockOpenAIClient(weight=_clarify_weight()))

        recorded_outcomes = []

        with patch(
            "src.features.meals._analysis_mixin._record_analysis_done",
            side_effect=lambda outcome, t0: recorded_outcomes.append(outcome),
        ):
            result = await svc.analyze_photos([b"p"], 1, 1, "")

        assert result.clarification is not None, "ожидается clarification"
        assert recorded_outcomes == ["clarification"], (
            f"ожидался outcome='clarification', получили: {recorded_outcomes}"
        )

    async def test_call2_ok_still_records_ok_outcome(
        self, test_redis, meal_service_factory
    ):
        """Нормальный Call 2 (ok) по-прежнему пишет outcome='ok'."""
        from tests.helpers import make_weight_response

        svc = meal_service_factory(MockOpenAIClient(weight=make_weight_response()))

        recorded_outcomes = []

        with patch(
            "src.features.meals._analysis_mixin._record_analysis_done",
            side_effect=lambda outcome, t0: recorded_outcomes.append(outcome),
        ):
            result = await svc.analyze_photos([b"p"], 1, 1, "")

        assert result.ok and result.meals, "ожидается успешный результат"
        assert recorded_outcomes == ["ok"], (
            f"ожидался outcome='ok', получили: {recorded_outcomes}"
        )
