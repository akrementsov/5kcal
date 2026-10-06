import json
from typing import List
from enum import StrEnum

from pydantic import ValidationError

from src.i18n import DEFAULT_LOCALE

from src.core.llm.two_call_models import (
    FoodIdentificationItem,
    FoodIdentificationErrorCode,
    WeightEstimationItem,
    WeightEstimationErrorCode,
    parse_food_identification,
    parse_weight_estimation,
    FoodItemOk,
    FoodItemError,
    WeightItemOk,
    WeightItemError,
)
from src.core.llm.models import MessageRole, Content
from src.core.llm.meal_prompt import (
    FOOD_IDENTIFICATION_PROMPT,
    WEIGHT_ESTIMATION_PROMPT,
)
from src.core.llm.protocol import LLMClient
from src.core.utils import get_logger

logger = get_logger()


class PromptId(StrEnum):
    FOOD_IDENTIFICATION = "food_identification"
    WEIGHT_ESTIMATION = "weight_estimation"


def _get_prompt_text(prompt_id: PromptId) -> str:
    if prompt_id == PromptId.FOOD_IDENTIFICATION:
        return FOOD_IDENTIFICATION_PROMPT
    if prompt_id == PromptId.WEIGHT_ESTIMATION:
        return WEIGHT_ESTIMATION_PROMPT
    raise ValueError(f"Неизвестный prompt_id: {prompt_id}")


def _build_user_context(locale: str) -> Content:
    context_text = (
        "USER_CONTEXT\n"
        f"language={locale}"
    )
    return Content.from_text(context_text)


def _inject_user_context(
    messages: List[tuple[MessageRole, List[Content]]],
    locale: str,
) -> List[tuple[MessageRole, List[Content]]]:
    """Добавляет USER_CONTEXT в первое user-сообщение."""
    if not messages:
        return messages

    result = list(messages)
    user_context = _build_user_context(locale)

    for i, (role, contents) in enumerate(result):
        if role == MessageRole.USER:
            result[i] = (role, list(contents) + [user_context])
            break

    return result


async def get_food_identification_data(
    llm_client: LLMClient,
    user_id: str,
    messages: List[tuple[MessageRole, List[Content]]],
    locale: str = DEFAULT_LOCALE,
) -> FoodItemOk | FoodItemError:
    enriched = _inject_user_context(messages, locale)

    text = await llm_client.get_response(
        system_prompt=_get_prompt_text(PromptId.FOOD_IDENTIFICATION),
        messages=enriched,
        response_schema=FoodIdentificationItem,
        response_schema_name="food_identification_response",
        user_id=user_id,
        prompt_cache_scope=PromptId.FOOD_IDENTIFICATION,
    )

    return parse_food_identification_response(text)


async def get_weight_estimation_data(
    llm_client: LLMClient,
    user_id: str,
    messages: List[tuple[MessageRole, List[Content]]],
    locale: str = DEFAULT_LOCALE,
) -> WeightItemOk | WeightItemError:
    enriched = _inject_user_context(messages, locale)

    text = await llm_client.get_response(
        system_prompt=_get_prompt_text(PromptId.WEIGHT_ESTIMATION),
        messages=enriched,
        response_schema=WeightEstimationItem,
        response_schema_name="weight_estimation_response",
        user_id=user_id,
        prompt_cache_scope=PromptId.WEIGHT_ESTIMATION,
    )

    return parse_weight_estimation_response(text)


def parse_food_identification_response(
    text: str,
) -> FoodItemOk | FoodItemError:
    try:
        payload = json.loads(text)
        # Нормализуем error_code до валидации Pydantic (Literal)
        raw_code = payload.get("error_code", "")
        if raw_code and raw_code not in FoodIdentificationErrorCode.__members__.values():
            payload["error_code"] = "other"
        # Поле question обязательно в schema, но может быть пусто для ok/error
        if "question" not in payload:
            payload["question"] = ""
        item = FoodIdentificationItem(**payload)
        return parse_food_identification(item)
    except (json.JSONDecodeError, ValidationError) as e:
        logger.error(
            "Не удалось распарсить ответ идентификации",
            extra={"error": str(e), "raw_text": text[:500]},
        )
        raise ValueError("Некорректный результат идентификации блюда") from e


def parse_weight_estimation_response(
    text: str,
) -> WeightItemOk | WeightItemError:
    try:
        payload = json.loads(text)
        # Нормализуем error_code до валидации Pydantic (Literal)
        raw_code = payload.get("error_code", "")
        if raw_code and raw_code not in WeightEstimationErrorCode.__members__.values():
            payload["error_code"] = "other"
        # Поле question обязательно в schema, но может быть пусто для ok/error
        if "question" not in payload:
            payload["question"] = ""
        item = WeightEstimationItem(**payload)
        return parse_weight_estimation(item)
    except (json.JSONDecodeError, ValidationError) as e:
        logger.error(
            "Не удалось распарсить ответ оценки веса",
            extra={"error": str(e), "raw_text": text[:500]},
        )
        raise ValueError("Некорректный результат оценки веса") from e
