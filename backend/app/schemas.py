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
    # True when dictionary reference context was included in the prompt.
    # NOTE: this means a French headword matched, NOT that a usable N'Ko
    # translation was supplied. See dictionary_nko_verified.
    dictionary_used: bool = False
    # How many dictionary entries were included as reference context.
    dictionary_entries_found: int = 0
    # True only if verified Unicode N'Ko from the dictionary reached the model.
    # Always False while the legacy font encoding is unresolved.
    dictionary_nko_verified: bool = False
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
