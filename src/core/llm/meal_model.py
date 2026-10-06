from pydantic import BaseModel, ConfigDict


class MealComponent(BaseModel):
    """Компонент блюда с посчитанным весом и КБЖУ (вес × КБЖУ/100г из Call 1+2).

    Хранится только точечное значение. Диапазон для UI (± confidence%, см. build_range)
    считается на лету при показе — хранить min/max избыточно, они выводятся из value+confidence.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    weight_g: float
    calories_kcal: float
    protein_g: float
    fat_g: float
    carbs_g: float
    confidence: int  # процент, на который растягивается диапазон при показе (см. build_range)


class Meal(BaseModel):
    """Хранится только точечное значение (см. MealComponent) — диапазон для UI/графиков
    считается на лету из value+confidence через build_range(), а не хранится отдельно."""

    name: str
    emoji: str
    count: int
    estimated_weight_g: float
    calories_kcal: float
    protein_g: float
    fat_g: float
    carbs_g: float
    confidence: int
    confidence_reason: str
    components: list[MealComponent] = []

    model_config = ConfigDict(extra="forbid")
