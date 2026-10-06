"""LLMClient Protocol — контракт для всех LLM-провайдеров."""

from typing import Protocol, Optional

from pydantic import BaseModel

from src.core.llm.models import MessageRole, Content


class LLMClient(Protocol):
    """Контракт LLM-клиента.

    Каждый провайдер реализует get_response(), внутри транслируя
    канонический формат (MessageRole, Content) в свой API-формат.
    """

    provider: str

    async def get_response(
        self,
        system_prompt: Optional[str],
        messages: list[tuple[MessageRole, list[Content]]],
        response_schema: type[BaseModel],
        response_schema_name: str,
        user_id: str,
        prompt_cache_scope: Optional[str] = None,
    ) -> str: ...

    async def close(self) -> None: ...
