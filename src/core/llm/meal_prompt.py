from pathlib import Path


_PROMPT_DIR = Path(__file__).with_name("prompts")


def _load_prompt(filename: str) -> str:
    return (_PROMPT_DIR / filename).read_text(encoding="utf-8").strip()

FOOD_IDENTIFICATION_PROMPT = _load_prompt("food_identification_v2.txt")
WEIGHT_ESTIMATION_PROMPT = _load_prompt("weight_estimation_v2.txt")
