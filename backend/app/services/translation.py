"""Translation orchestration: validate -> retrieve -> prompt -> provider -> check."""

import logging

from app.config import Settings
from app.errors import InvalidOutputEncodingError, ProviderNotConfiguredError
from app.languages import NKO
from app.schemas import TranslateResponse
from app.services import nko_text
from app.services.dictionary import get_dictionary_service
from app.services.prompt import build_system_prompt, build_user_prompt
from app.services.providers.registry import get_provider

logger = logging.getLogger(__name__)


class TranslationService:
    def __init__(self, settings: Settings):
        self._settings = settings
        self._provider = get_provider(settings)
        self._dictionary = get_dictionary_service(settings)

    @property
    def provider_name(self) -> str:
        return self._provider.name

    def provider_configured(self) -> bool:
        return self._provider.is_configured()

    def model_name(self) -> str:
        return self._provider.model_name()

    def translate(self, source: str, target: str, text: str) -> TranslateResponse:
        if not self._provider.is_configured():
            raise ProviderNotConfiguredError()

        entries = self._dictionary.lookup(text, source, target)
        context = self._dictionary.format_context(entries)
        # A matched headword is not a usable N'Ko translation. Report the two
        # separately so callers cannot mistake one for the other.
        verified_nko_supplied = any(e.is_verified and e.target_term for e in entries)

        system_prompt = build_system_prompt(source, target)
        user_prompt = build_user_prompt(source, target, text, context)

        # Never log `text` or the prompts: user content is not ours to retain.
        logger.info("translate %s->%s chars=%d", source, target, len(text))

        result = self._provider.complete(system_prompt, user_prompt)
        translation = result.text
        warnings = list(result.warnings)

        # Output sanity checks. These never fabricate or silently repair a
        # translation. Private Use Area characters cannot be valid N'Ko, and
        # deleting them would change the meaning while still looking like a
        # success, so the whole result is rejected instead.
        if nko_text.contains_pua(translation):
            offending = sorted({f"U+{ord(c):04X}" for c in translation if nko_text.is_pua_char(c)})
            logger.warning(
                "Rejected %s->%s output containing %d Private Use Area codepoint(s): %s",
                source,
                target,
                len(offending),
                ", ".join(offending[:8]),
            )
            raise InvalidOutputEncodingError()

        if target == NKO and not nko_text.contains_nko(translation):
            warnings.append(
                "The result contains no N'Ko characters. The model may have "
                "failed to produce N'Ko script for this input."
            )

        return TranslateResponse(
            translation=translation,
            source_language=source,
            target_language=target,
            provider=self._provider.name,
            model=result.model,
            dictionary_used=bool(context),
            dictionary_entries_found=len(entries),
            dictionary_nko_verified=verified_nko_supplied,
            human_verified=False,
            warnings=warnings,
        )
