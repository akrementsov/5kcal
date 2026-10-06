from dataclasses import dataclass
from enum import StrEnum
from typing import Optional


class BarcodeSource(StrEnum):
    OPEN_FOOD_FACTS = "open_food_facts"
    FATSECRET = "fatsecret"
    BARCODE_LOOKUP = "barcode_lookup"
    DIETAGRAM = "dietagram"


@dataclass
class BarcodeProduct:
    barcode: str
    name: str
    brand: Optional[str]
    source: BarcodeSource
    nutrition_raw: str = ""  # сырые данные о КБЖУ (текст или JSON-строка)
