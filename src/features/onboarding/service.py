from dataclasses import dataclass
from pathlib import Path

from src.core.database import db as db_funcs
from src.core.database.database import Database
from src.core.database.models import DemoExample
from src.core.llm.meal_model import Meal as MealModel, MealComponent
from src.core.utils import get_logger

logger = get_logger()

# assets/demo/ в корне репозитория: service.py -> onboarding -> features -> src -> repo
ASSETS_DIR = Path(__file__).resolve().parents[3] / "assets" / "demo"


@dataclass
class DemoExampleDTO:
    id: int
    sort_order: int
    asset_filename: str
    telegram_file_id: str | None
    emoji: str
    name_ru: str
    name_en: str
    calories_kcal: int
    protein_g: float
    fat_g: float
    carbs_g: float
    count: int
    components: list[str]


def _to_dto(row: DemoExample) -> DemoExampleDTO:
    return DemoExampleDTO(
        id=row.id,
        sort_order=row.sort_order,
        asset_filename=row.asset_filename,
        telegram_file_id=row.telegram_file_id,
        emoji=row.emoji or "",
        name_ru=row.name_ru,
        name_en=row.name_en,
        calories_kcal=row.calories_kcal,
        protein_g=row.protein_g,
        fat_g=row.fat_g,
        carbs_g=row.carbs_g,
        count=row.count or 1,
        components=list(row.components or []),
    )


class DemoService:
    """Читает статичные demo_examples и мапит их в Pydantic Meal для рендера
    существующим format_meal_for_user. Данные статичны → кэш в памяти."""

    def __init__(self, db: Database):
        self.db = db
        self._cache: list[DemoExampleDTO] | None = None

    def _load(self) -> list[DemoExampleDTO]:
        if self._cache is not None:
            return self._cache
        with self.db.session() as session:
            rows = (
                session.query(DemoExample).order_by(DemoExample.sort_order.asc()).all()
            )
            dtos = [_to_dto(r) for r in rows]
        # Пустой результат НЕ кэшируем: миграция могла засеять строки позже
        # (или ассеты дозальют) — иначе пустой список залипнет до рестарта.
        if dtos:
            self._cache = dtos
        return dtos

    def _is_available(self, ex: DemoExampleDTO) -> bool:
        """Пример отдаём только если реально можем показать фото: есть кэш file_id
        ИЛИ файл на диске. Иначе (строка засеяна миграцией, но assets/demo/*.jpg
        ещё не залиты) FSInputFile бросил бы FileNotFoundError и сломал /start —
        fail-safe: такой пример «не существует» → деградация к show_start."""
        return bool(ex.telegram_file_id) or self.asset_path(ex).exists()

    def list_examples(self) -> list[DemoExampleDTO]:
        return [e for e in self._load() if self._is_available(e)]

    def has_examples(self) -> bool:
        return len(self.list_examples()) > 0

    def get_example(self, example_id: int) -> DemoExampleDTO | None:
        return next((e for e in self.list_examples() if e.id == example_id), None)

    def get_hero(self) -> DemoExampleDTO | None:
        examples = self.list_examples()
        return examples[0] if examples else None

    def asset_path(self, ex: DemoExampleDTO) -> Path:
        return ASSETS_DIR / ex.asset_filename

    def to_meal_model(self, ex: DemoExampleDTO, locale: str) -> MealModel:
        name = ex.name_en if locale == "en" and ex.name_en else ex.name_ru
        return MealModel(
            name=name,
            emoji=ex.emoji,
            count=ex.count,
            estimated_weight_g=0,  # вес в демо не хранится и не показывается
            calories_kcal=float(ex.calories_kcal),
            protein_g=ex.protein_g,
            fat_g=ex.fat_g,
            carbs_g=ex.carbs_g,
            confidence=15,  # фиксированный «доверительный» процент как у боевой карточки
            confidence_reason="",
            components=[
                MealComponent(
                    name=n,
                    weight_g=0,
                    calories_kcal=0,
                    protein_g=0,
                    fat_g=0,
                    carbs_g=0,
                    confidence=15,
                )
                for n in ex.components
            ],  # карточка показывает только имена, нули невидимы
        )

    def save_demo_meal(
        self,
        user_id: int,
        meal_model: MealModel,
        message_id: int,
        telegram_file_id: str | None = None,
    ) -> int | None:
        """Сохраняет демо-блюдо как реальный Meal с excluded=True (не в статистике).
        Владелец — user_id (== from_user.id), поэтому боевые кнопки карточки
        (edit/delete/дата/порции/тумблер) работают по anti-IDOR-проверке владельца.
        Возвращает meal_id или None при сбое (fail-safe: карточка без кнопок)."""
        try:
            with self.db.session() as session:
                meal = db_funcs.save_meal_data(
                    session,
                    user_id,
                    meal_model,
                    caption="",
                    message_id=message_id,
                    telegram_file_id=telegram_file_id,
                )
                meal.excluded = True
                session.flush()
                return meal.id
        except Exception as e:
            logger.warning(
                "Не удалось сохранить демо-блюдо",
                extra={"user_id": user_id, "error": str(e)},
            )
            return None

    def count_user_meals(self, user_id: int) -> int:
        """Тонкая обёртка над db-слоем: подсчёт блюд юзера без открытия сессии
        в хендлере (первое-блюдо nudge проверяет == 1)."""
        with self.db.session() as session:
            return db_funcs.count_user_meals(session, user_id)

    def update_file_id(self, example_id: int, file_id: str) -> None:
        """Кэширует file_id после первой отправки (в БД + in-memory)."""
        try:
            with self.db.session() as session:
                row = (
                    session.query(DemoExample)
                    .filter(DemoExample.id == example_id)
                    .first()
                )
                if row is not None:
                    row.telegram_file_id = file_id
        except Exception as e:
            logger.warning(
                "Не удалось закэшировать demo file_id",
                extra={"example_id": example_id, "error": str(e)},
            )
            return
        for e in self._cache or []:
            if e.id == example_id:
                e.telegram_file_id = file_id
