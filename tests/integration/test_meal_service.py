"""Тесты MealService — анализ фото, текста, ошибки LLM, редактирование (V2)."""

import pytest

from src.core.ui.texts import ErrSvc
from src.core.user_state.session import AnalysisSession, SessionMode
from tests.helpers import save_test_meal
from tests.mocks import MockOpenAIClient


# ─── V2-фикстуры (компонентная схема) ────────────────────────────────────────


def make_component(
    name: str = "Тестовое блюдо",
    calories_per_100g: float = 200.0,
    protein_per_100g: float = 10.0,
    fat_per_100g: float = 5.0,
    carbs_per_100g: float = 30.0,
) -> dict:
    return {
        "name": name,
        "description": "тестовый компонент",
        "placement": "separate",
        "attached_to": "",
        "calories_per_100g": calories_per_100g,
        "protein_per_100g": protein_per_100g,
        "fat_per_100g": fat_per_100g,
        "carbs_per_100g": carbs_per_100g,
    }


def make_identification_v2(
    name: str = "Тестовое блюдо",
    emoji: str = "🍽️",
    components: list[dict] | None = None,
    **component_kwargs,
) -> dict:
    if components is None:
        components = [make_component(name=name, **component_kwargs)]
    return {
        "reasoning": "test",
        "verification": "test",
        "status": "ok",
        "name": name,
        "emoji": emoji,
        "components": components,
        "error_code": "",
        "error": "",
    }


def make_identification_error_v2(
    error: str, error_code: str = "meal_not_recognized"
) -> dict:
    return {
        "reasoning": "",
        "verification": "",
        "status": "error",
        "name": "",
        "emoji": "",
        "components": [],
        "error_code": error_code,
        "error": error,
    }


def make_weight_v2(
    name: str = "Тестовое блюдо",
    weight_g: float = 150.0,
    components: list[dict] | None = None,
) -> dict:
    if components is None:
        components = [{"name": name, "weight_g": weight_g}]
    return {
        "reasoning": "test",
        "verification": "test",
        "status": "ok",
        "components": components,
        "total_weight_g": sum(c["weight_g"] for c in components),
        "error_code": "",
        "error": "",
    }


def make_v2_mock(**kwargs) -> MockOpenAIClient:
    """Мок с валидными V2-ответами обоих вызовов (дефолт: 150г × 200 ккал/100г)."""
    name = kwargs.pop("name", "Тестовое блюдо")
    weight_g = kwargs.pop("weight_g", 150.0)
    return MockOpenAIClient(
        identification=make_identification_v2(name=name, **kwargs),
        weight=make_weight_v2(name=name, weight_g=weight_g),
    )


# ─── analyze_photos ──────────────────────────────────────────────────────────


class TestAnalyzePhotos:
    async def test_success(self, meal_service_factory):
        svc = meal_service_factory(make_v2_mock())

        result = await svc.analyze_photos(
            [b"fake_jpg"], user_id=1, chat_id=1, caption="завтрак"
        )

        assert result.ok is True
        assert len(result.meals) == 1
        assert result.meals[0].name == "Тестовое блюдо"
        assert result.caption == "завтрак"
        assert result.error is None

        # Вес = сумма компонентов Call 2 (150г), точечное значение
        meal = result.meals[0]
        assert meal.estimated_weight_g == pytest.approx(150.0)
        # Калории = 150 × 200/100 = 300
        assert meal.calories_kcal == pytest.approx(300.0)
        assert meal.confidence == 15

    async def test_multiple_images(self, meal_service_factory):
        svc = meal_service_factory(make_v2_mock())

        result = await svc.analyze_photos(
            [b"img1", b"img2", b"img3"], user_id=1, chat_id=1, caption=""
        )

        assert result.ok is True

    async def test_component_arithmetic(self, meal_service_factory):
        """Вес — сумма компонентов Call 2, калории — взвешенная сумма КБЖУ Call 1."""
        identification = make_identification_v2(
            name="Комбо",
            components=[
                make_component(name="Комбо", calories_per_100g=200.0),
                make_component(name="Гарнир", calories_per_100g=100.0),
            ],
        )
        weight = make_weight_v2(
            components=[
                {"name": "Комбо", "weight_g": 150.0},
                {"name": "Гарнир", "weight_g": 100.0},
            ]
        )
        svc = meal_service_factory(
            MockOpenAIClient(identification=identification, weight=weight)
        )

        result = await svc.analyze_photos([b"img"], user_id=1, chat_id=1, caption="")

        assert result.ok is True
        meal = result.meals[0]
        # Вес = 150 + 100 = 250
        assert meal.estimated_weight_g == pytest.approx(250.0)
        # Калории = 150×200/100 + 100×100/100 = 400
        assert meal.calories_kcal == pytest.approx(400.0)

    async def test_error_with_text(self, meal_service_factory):
        mock = MockOpenAIClient(
            identification=make_identification_error_v2("Не вижу еды на фото")
        )
        svc = meal_service_factory(mock)

        result = await svc.analyze_photos([b"img"], user_id=1, chat_id=1, caption="")

        assert result.ok is False
        assert result.error_text == "Не вижу еды на фото"
        assert result.error is None
        assert result.meals == []

    async def test_error_empty(self, meal_service_factory):
        mock = MockOpenAIClient(identification=make_identification_error_v2(""))
        svc = meal_service_factory(mock)

        result = await svc.analyze_photos([b"img"], user_id=1, chat_id=1, caption="")

        assert result.ok is False
        assert result.error == ErrSvc.MEAL_NOT_RECOGNIZED

    async def test_multiple_meals(self, meal_service_factory):
        """Двухвызовная архитектура возвращает одно блюдо за раз."""
        svc = meal_service_factory(make_v2_mock(name="Суп", weight_g=300.0))

        result = await svc.analyze_photos([b"img"], user_id=1, chat_id=1, caption="")

        assert result.ok is True
        assert len(result.meals) == 1
        assert result.meals[0].name == "Суп"


# ─── analyze_text ─────────────────────────────────────────────────────────────


class TestAnalyzeText:
    async def test_success(self, meal_service_factory):
        svc = meal_service_factory(make_v2_mock())

        result = await svc.analyze_text("овсянка с бананом", user_id=1, chat_id=1)

        assert result.ok is True
        assert result.caption == "овсянка с бананом"
        assert len(result.meals) == 1


# ─── start_editing ────────────────────────────────────────────────────────────


class TestEditing:
    class RecordingMockOpenAIClient(MockOpenAIClient):
        def __init__(self, response=None, *, identification=None, weight=None):
            super().__init__(response, identification=identification, weight=weight)
            self.last_messages = None

        async def get_response(
            self,
            system_prompt=None,
            messages=None,
            response_schema=None,
            response_schema_name="",
            user_id="",
            prompt_cache_scope=None,
            **kwargs,
        ):
            self.last_messages = messages
            return await super().get_response(
                system_prompt=system_prompt,
                messages=messages,
                response_schema=response_schema,
                response_schema_name=response_schema_name,
                user_id=user_id,
                prompt_cache_scope=prompt_cache_scope,
            )

    async def test_start_editing_success(
        self, meal_service_factory, user_service, test_db
    ):
        user_service.get_or_create(user_id=1)
        meal_id = save_test_meal(test_db, user_id=1)

        svc = meal_service_factory(make_v2_mock())
        result = await svc.start_editing(
            meal_id=meal_id,
            user_text="убрать хлеб",
            extra_photo_bytes=None,
            chat_id=1,
            user_id=1,
            loading_msg_id=None,
            meal_card_msg_id=None,
            original_base64_images=["base64data"],
        )

        assert result.ok is True
        assert len(result.meals) >= 1

    async def test_start_editing_extra_only_without_originals(
        self, meal_service_factory, user_service, test_db
    ):
        """Без original_base64_images, но с extra_photo_bytes — анализ на одних extra.

        Регрессия: раньше fallback читал базовые фото с диска (meal_record.filenames).
        После рефакторинга оригиналов нет — должен работать только на extra.
        """
        user_service.get_or_create(user_id=1)
        meal_id = save_test_meal(test_db, user_id=1)

        svc = meal_service_factory(make_v2_mock())
        result = await svc.start_editing(
            meal_id=meal_id,
            user_text=None,
            extra_photo_bytes=[b"new-photo-bytes"],
            chat_id=1,
            user_id=1,
            loading_msg_id=None,
            meal_card_msg_id=None,
            original_base64_images=None,
        )

        assert result.ok is True

    async def test_start_editing_meal_not_found(self, meal_service_factory):
        svc = meal_service_factory(MockOpenAIClient())
        result = await svc.start_editing(
            meal_id=99999,
            user_text="text",
            extra_photo_bytes=None,
            chat_id=1,
            user_id=1,
            loading_msg_id=None,
            meal_card_msg_id=None,
        )

        assert result.ok is False
        assert result.error == ErrSvc.MEAL_NOT_RECOGNIZED

    async def test_start_editing_no_content(
        self, meal_service_factory, user_service, test_db
    ):
        user_service.get_or_create(user_id=1)
        meal_id = save_test_meal(test_db, user_id=1)

        svc = meal_service_factory(MockOpenAIClient())
        result = await svc.start_editing(
            meal_id=meal_id,
            user_text=None,
            extra_photo_bytes=None,
            chat_id=1,
            user_id=1,
            loading_msg_id=None,
            meal_card_msg_id=None,
        )

        assert result.ok is False
        assert result.error == ErrSvc.PHOTO_PROCESSING

    async def test_start_editing_with_extra_photos_sends_full_context(
        self, meal_service_factory, user_service, test_db
    ):
        """LLM получает USER_CONTEXT и все фото: оригиналы + extra."""
        user_service.get_or_create(user_id=1)
        meal_id = save_test_meal(
            test_db,
            user_id=1,
            caption="старое описание",
        )

        mock = self.RecordingMockOpenAIClient(
            identification=make_identification_v2(),
            weight=make_weight_v2(),
        )
        svc = meal_service_factory(mock)

        result = await svc.start_editing(
            meal_id=meal_id,
            user_text="вот этикетка",
            extra_photo_bytes=[b"new-photo"],
            chat_id=1,
            user_id=1,
            loading_msg_id=None,
            meal_card_msg_id=None,
            original_base64_images=["base64-orig"],
        )

        assert result.ok is True

        # messages — list[tuple[MessageRole, list[Content]]]
        first_user_contents = mock.last_messages[0][1]
        user_context = next(
            c.text for c in first_user_contents
            if c.type == "input_text" and (c.text or "").startswith("USER_CONTEXT")
        )
        assert "language=ru" in user_context

        # Оригинальные и extra-фото переданы в LLM вместе
        image_urls = [
            c.image_url for c in first_user_contents if c.type == "input_image"
        ]
        assert image_urls == [
            "data:image/jpeg;base64,base64-orig",
            "data:image/jpeg;base64,bmV3LXBob3Rv",
        ]

