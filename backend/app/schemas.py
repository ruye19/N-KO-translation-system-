"""Request/response models for the public API."""

from typing import Optional

from pydantic import BaseModel, Field


class TranslateRequest(BaseModel):
    source_language: str = Field(..., examples=["en"])
    target_language: str = Field(..., examples=["nko"])
    text: str = Field(..., examples=["How are you?"])


class TranslateResponse(BaseModel):
    translation: str
    source_language: str
    target_language: str
    provider: str
    model: str
    # True only if verified dictionary context was actually supplied.
    dictionary_used: bool = False
    # Always False in version 1: nothing here has been checked by a human.
    human_verified: bool = False
    notice: str = (
        "AI-assisted translation. Not reviewed by a human N'Ko speaker; "
        "accuracy is not guaranteed."
    )
    warnings: list[str] = Field(default_factory=list)


class ErrorBody(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorBody


class HealthResponse(BaseModel):
    status: str
    provider: str
    provider_configured: bool
    model: Optional[str] = None
    dictionary_enabled: bool
    max_input_chars: int
