"""Тесты анализа с barcode-контекстом — через MealService.analyze_photos(barcode_products=...)."""

from src.core.ui.texts import ErrSvc
from tests.helpers import make_barcode_product
from tests.mocks import MockOpenAIClient


# ─── V2-фикстуры (компонентная схема) ─────────────────────────────────────────


def _id_ok(
    name: str = "Тестовое блюдо",
    emoji: str = "🍽️",
    calories_per_100g: float = 200.0,
    protein_per_100g: float = 10.0,
    fat_per_100g: float = 5.0,
    carbs_per_100g: float = 30.0,
) -> dict:
    """Ответ Call 1 (identification) в V2-схеме: status=ok + компоненты."""
    return {
        "reasoning": "test",
        "verification": "test",
        "status": "ok",
        "name": name,
        "emoji": emoji,
        "components": [
            {
                "name": name,
                "description": "тестовое блюдо",
                "placement": "separate",
                "attached_to": "",
                "calories_per_100g": calories_per_100g,
                "protein_per_100g": protein_per_100g,
                "fat_per_100g": fat_per_100g,
                "carbs_per_100g": carbs_per_100g,
            }
        ],
        "error_code": "",
        "error": "",
    }


def _id_error(error: str, error_code: str = "meal_not_recognized") -> dict:
    """Ответ Call 1 (identification) в V2-схеме: status=error."""
    return {
        "reasoning": "test",
        "verification": "test",
        "status": "error",
        "name": "",
        "emoji": "",
        "components": [],
        "error_code": error_code,
        "error": error,
    }


def _weight_ok(name: str = "Тестовое блюдо", weight_g: float = 150.0) -> dict:
    """Ответ Call 2 (weight estimation) в V2-схеме: status=ok + компоненты."""
    return {
        "reasoning": "test",
        "verification": "test",
        "status": "ok",
        "components": [{"name": name, "weight_g": weight_g}],
        "total_weight_g": weight_g,
        "error_code": "",
        "error": "",
    }


class TestAnalyzeWithBarcodes:
    async def test_success(self, meal_service_factory, test_redis):
        """Enriched-анализ возвращает блюда с данными этикетки."""
        svc = meal_service_factory(
            MockOpenAIClient(
                identification=_id_ok(
                    name="Молоко 3.2%",
                    calories_per_100g=58.0,
                    protein_per_100g=2.9,
                    fat_per_100g=3.2,
                    carbs_per_100g=4.7,
                ),
                weight=_weight_ok(name="Молоко 3.2%", weight_g=200.0),
            )
        )
        product = make_barcode_product()

        result = await svc.analyze_photos(
            [b"photo"], user_id=1, chat_id=1, caption="",
            barcode_products=[product],
        )

        assert result.ok is True
        assert len(result.meals) == 1
        assert result.meals[0].name == "Молоко 3.2%"

    async def test_multiple_products(self, meal_service_factory):
        """Несколько продуктов по штрихкодам — двухвызовная архитектура возвращает одно блюдо."""
        svc = meal_service_factory(
            MockOpenAIClient(
                identification=_id_ok(name="Молоко"),
                weight=_weight_ok(name="Молоко", weight_g=200.0),
            )
        )
        products = [
            make_barcode_product(barcode="111", name="Молоко"),
            make_barcode_product(barcode="222", name="Хлеб"),
        ]

        result = await svc.analyze_photos(
            [b"photo"], user_id=1, chat_id=1, caption="",
            barcode_products=products,
        )

        assert result.ok is True
        assert len(result.meals) == 1

    async def test_with_caption(self, meal_service_factory):
        """Caption пользователя передаётся вместе с barcode-контекстом."""
        svc = meal_service_factory(
            MockOpenAIClient(identification=_id_ok(), weight=_weight_ok())
        )

        result = await svc.analyze_photos(
            [b"photo"], user_id=1, chat_id=1, caption="200мл",
            barcode_products=[make_barcode_product()],
        )

        assert result.ok is True
        assert result.caption == "200мл"

    async def test_error_with_text(self, meal_service_factory):
        """AI вернул ошибку other с произвольным текстом — возвращает error_text."""
        svc = meal_service_factory(
            MockOpenAIClient(
                identification=_id_error("Не вижу порцию", error_code="other"),
            )
        )

        result = await svc.analyze_photos(
            [b"photo"], user_id=1, chat_id=1, caption="",
            barcode_products=[make_barcode_product()],
        )

        assert result.ok is False
        assert result.error_text == "Не вижу порцию"

    async def test_error_empty_fallback(self, meal_service_factory, test_redis):
        """AI вернул пустой error с meal_not_recognized — возвращает стандартную ошибку."""
        svc = meal_service_factory(
            MockOpenAIClient(
                identification=_id_error(""),
            )
        )

        result = await svc.analyze_photos(
            [b"photo"], user_id=1, chat_id=1, caption="",
            barcode_products=[make_barcode_product()],
        )

        assert result.ok is False
        assert result.error == ErrSvc.MEAL_NOT_RECOGNIZED
