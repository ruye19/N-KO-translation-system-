from fastapi import APIRouter, Depends

from app.config import Settings, get_settings
from app.dependencies import get_translation_service
from app.languages import directions_payload
from app.schemas import HealthResponse
from app.services.translation import TranslationService

router = APIRouter(tags=["meta"])


@router.get("/health", response_model=HealthResponse)
def health(
    settings: Settings = Depends(get_settings),
    service: TranslationService = Depends(get_translation_service),
) -> HealthResponse:
    """Liveness + configuration status. Never returns any secret value."""
    return HealthResponse(
        status="ok",
        provider=service.provider_name,
        provider_configured=service.provider_configured(),
        model=service.model_name(),
        dictionary_enabled=settings.dictionary_enabled,
        max_input_chars=settings.max_input_chars,
    )


@router.get("/languages")
def languages():
    """The four supported directions, so the UI never offers an invalid pair."""
    return {"directions": directions_payload()}
