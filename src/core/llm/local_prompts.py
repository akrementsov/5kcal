from __future__ import annotations

from pathlib import Path
import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.features.barcode.models import BarcodeProduct
    from src.core.llm.two_call_models import FoodInfo


_PROMPT_DIR = Path(__file__).with_name("prompts")


def _load_prompt(filename: str) -> str:
    return (_PROMPT_DIR / filename).read_text(encoding="utf-8").strip()

_BARCODE_HINTS_PROMPT = _load_prompt("barcode_hints_v1.txt")
_PRODUCT_CONTEXT_PROMPT = _load_prompt("barcode_context_v1.txt")


def render_barcode_hints_prompt(codes: list[str]) -> str:
    return _BARCODE_HINTS_PROMPT.format(codes=", ".join(codes))


def render_product_context_prompt(products: list[BarcodeProduct]) -> str:
    lines = []
    for index, p in enumerate(products, start=1):
        brand = f" ({p.brand})" if p.brand else ""
        nutrition = p.nutrition_raw if p.nutrition_raw else "КБЖУ неизвестны"
        lines.append(
            f"{index}. {p.name}{brand} — "
            f"{nutrition}; "
            f"штрихкод: {p.barcode}; источник: {p.source}"
        )
    return _PRODUCT_CONTEXT_PROMPT.format(products_block="\n".join(lines))


def render_food_info_context(items: list[FoodInfo]) -> str:
    """Строит FOOD_INFO блок для Call 2 (per-component оценка веса).

    КБЖУ компонентов в Call 2 не передаются — они нужны только
    для сборки калорий после оценки весов.
    """
    def _components(item: FoodInfo) -> list[dict]:
        return [
            {
                "name": c.get("name", ""),
                "description": c.get("description", ""),
                "placement": c.get("placement", "separate"),
                "attached_to": c.get("attached_to", ""),
            }
            for c in item.components
        ]

    if len(items) == 1:
        payload: dict | list = {
            "dish": items[0].name,
            "components": _components(items[0]),
        }
    else:
        payload = [
            {"dish": item.name, "components": _components(item)}
            for item in items
        ]
    return (
        "FOOD_INFO\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=2)}"
    )
