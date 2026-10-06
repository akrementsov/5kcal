"""Регрессионные тесты для photo cleanup (commit 03c94a6).

Фото больше не сохраняются на диск — живут только в Telegram (photo_file_ids).
Эти тесты ловят попытки вернуть legacy-функционал.
"""

import pytest
from pydantic import ValidationError

from src.core.llm.meal_model import Meal


# ─── Контракт LLM-схемы ─────────────────────────────────────────────────────


class TestMealSchemaForbidsImageFilenames:
    """LLM не должен возвращать image_filenames. Pydantic с extra=forbid гарантирует retry."""

    def test_pydantic_rejects_image_filenames(self):
        with pytest.raises(ValidationError) as exc_info:
            Meal(
                name="X",
                emoji="🍽",
                count=1,
                estimated_weight_g=150,
                calories_kcal=250,
                protein_g=12,
                fat_g=7,
                carbs_g=35,
                confidence=10,
                confidence_reason="",
                image_filenames=[],
            )
        assert "image_filenames" in str(exc_info.value)

    def test_json_schema_has_no_image_filenames(self):
        """Схема, которая уходит в OpenAI/Gemini, не должна содержать image_filenames."""
        schema = Meal.model_json_schema()
        assert "image_filenames" not in schema.get("properties", {})


# ─── Dead code не возвращается ──────────────────────────────────────────────


class TestPhotoSaverDeadCodeStaysDead:
    """Если функции снова появятся — тест упадёт."""

    def test_saver_module_does_not_exist(self):
        with pytest.raises(ImportError):
            from src.core.image_processing import saver  # noqa: F401

    def test_image_processing_does_not_export_disk_helpers(self):
        from src.core import image_processing

        assert not hasattr(image_processing, "save_image_bytes")
        assert not hasattr(image_processing, "delete_image")
        assert not hasattr(image_processing, "read_image_as_base64")


# ─── ORM-модель: legacy-колонки удалены ─────────────────────────────────────


class TestMealOrmHasNoLegacyColumns:
    """SQLAlchemy Meal не должен иметь filenames / image_filenames."""

    def test_no_legacy_photo_columns(self):
        from src.core.database.models import Meal

        column_names = {c.name for c in Meal.__table__.columns}
        assert "filenames" not in column_names
        assert "image_filenames" not in column_names

    def test_meal_has_photo_file_ids_column(self):
        """photo_file_ids остаётся — это новый канонический способ."""
        from src.core.database.models import Meal

        column_names = {c.name for c in Meal.__table__.columns}
        assert "photo_file_ids" in column_names


# ─── Session не несёт legacy-поля ───────────────────────────────────────────


class TestSessionHasNoFilenamesField:
    """AnalysisSession (Pydantic) не должна иметь filenames."""

    def test_no_filenames_field(self):
        from src.core.user_state.session import AnalysisSession

        fields = AnalysisSession.model_fields
        assert "filenames" not in fields
        assert "base64_images" in fields  # canonical способ
