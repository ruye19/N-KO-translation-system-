"""Shared FastAPI dependencies."""

from functools import lru_cache

from app.config import get_settings
from app.services.translation import TranslationService


@lru_cache(maxsize=1)
def get_translation_service() -> TranslationService:
    """One long-lived service (and provider client) per process.

    Note: no argument. Settings is a pydantic model and is not hashable, so it
    cannot be an lru_cache key; get_settings() is itself cached.
    """
    return TranslationService(get_settings())
