from typing import Literal, Optional

from pydantic import BaseModel
from enum import StrEnum


class Content(BaseModel):
    type: str
    image_url: Optional[str] = None
    text: Optional[str] = None
    detail: Optional[Literal["high", "low", "auto"]] = None

    @classmethod
    def image(
        cls,
        base64str: str,
        detail: Literal["high", "low", "auto"] = "low",
    ) -> "Content":
        return cls(
            type="input_image",
            image_url=f"data:image/jpeg;base64,{base64str}",
            detail=detail,
        )

    @classmethod
    def from_text(cls, value: str) -> "Content":
        if not value or not value.strip():
            raise ValueError("Text cannot be empty or None")
        return cls(type="input_text", text=value.strip())

    @classmethod
    def output_text(cls, value: str) -> "Content":
        if not value or not value.strip():
            raise ValueError("Text cannot be empty or None")
        return cls(type="output_text", text=value.strip())


class MessageRole(StrEnum):
    DEVELOPER = "developer"
    USER = "user"
    SYSTEM = "system"
    ASSISTANT = "assistant"
