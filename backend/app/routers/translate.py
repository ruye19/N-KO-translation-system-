from fastapi import APIRouter, Depends, HTTPException

from app.config import Settings, get_settings
from app.dependencies import get_translation_service
from app.errors import TranslationError
from app.languages import (
    SUPPORTED_LANGUAGES,
    is_supported_direction,
    language_name,
)
from app.schemas import TranslateRequest, TranslateResponse
from app.security import enforce_rate_limit, require_api_key
from app.services.translation import TranslationService

router = APIRouter(tags=["translation"])


def _bad_request(code: str, message: str) -> HTTPException:
    return HTTPException(status_code=400, detail={"code": code, "message": message})


# The rate limit runs first, so failed key guesses are throttled too.
@router.post(
    "/translate",
    response_model=TranslateResponse,
    dependencies=[Depends(enforce_rate_limit), Depends(require_api_key)],
)
def translate(
    payload: TranslateRequest,
    settings: Settings = Depends(get_settings),
    service: TranslationService = Depends(get_translation_service),
) -> TranslateResponse:
    source = (payload.source_language or "").strip().lower()
    target = (payload.target_language or "").strip().lower()
    text = payload.text or ""

    if source not in SUPPORTED_LANGUAGES:
        raise _bad_request(
            "unsupported_language",
            f"Unsupported source language '{payload.source_language}'. "
            f"Supported: {', '.join(sorted(SUPPORTED_LANGUAGES))}.",
        )
    if target not in SUPPORTED_LANGUAGES:
        raise _bad_request(
            "unsupported_language",
            f"Unsupported target language '{payload.target_language}'. "
            f"Supported: {', '.join(sorted(SUPPORTED_LANGUAGES))}.",
        )
    if source == target:
        raise _bad_request(
            "same_language",
            "Source and target language must be different.",
        )
    if not is_supported_direction(source, target):
        raise _bad_request(
            "unsupported_direction",
            f"{language_name(source)} to {language_name(target)} is not supported "
            "in this version. Supported directions: English/French to N'Ko, and "
            "N'Ko to English/French.",
        )
    if not text.strip():
        raise _bad_request("empty_text", "Enter some text to translate.")
    if len(text) > settings.max_input_chars:
        raise _bad_request(
            "text_too_long",
            f"Text is {len(text)} characters; the limit is "
            f"{settings.max_input_chars}. Translate a shorter passage.",
        )

    try:
        return service.translate(source, target, text)
    except TranslationError as exc:
        raise HTTPException(
            status_code=exc.http_status,
            detail={"code": exc.code, "message": exc.message},
        ) from exc
