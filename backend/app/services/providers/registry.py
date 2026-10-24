"""Provider lookup.

Register new providers here; the rest of the app selects one by name via the
TRANSLATION_PROVIDER environment variable.
"""

from typing import Callable, Dict

from app.config import Settings
from app.errors import ProviderUnknownError
from app.services.providers.anthropic_provider import AnthropicProvider
from app.services.providers.base import TranslationProvider
from app.services.providers.gemini_provider import GeminiProvider

_BUILDERS: Dict[str, Callable[[Settings], TranslationProvider]] = {
    "anthropic": AnthropicProvider,
    "gemini": GeminiProvider,
}


def available_providers() -> list[str]:
    return sorted(_BUILDERS)


def get_provider(settings: Settings) -> TranslationProvider:
    name = (settings.translation_provider or "").strip().lower()
    builder = _BUILDERS.get(name)
    if builder is None:
        raise ProviderUnknownError(
            f"Unknown TRANSLATION_PROVIDER '{settings.translation_provider}'. "
            f"Available: {', '.join(available_providers())}."
        )
    return builder(settings)
