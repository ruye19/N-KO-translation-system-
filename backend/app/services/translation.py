"""Translation orchestration: validate -> retrieve -> prompt -> provider -> check."""

import logging

from app.config import Settings
from app.errors import EmptyTranslationError, ProviderNotConfiguredError
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

        system_prompt = build_system_prompt(source, target)
        user_prompt = build_user_prompt(source, target, text, context)

        # Never log `text` or the prompts: user content is not ours to retain.
        logger.info("translate %s->%s chars=%d", source, target, len(text))

        result = self._provider.complete(system_prompt, user_prompt)
        translation = result.text
        warnings = list(result.warnings)

        # Output sanity checks. These never fabricate a translation; they only
        # clean obviously-invalid characters and tell the caller what happened.
        if nko_text.contains_pua(translation):
            cleaned = nko_text.strip_pua(translation).strip()
            warnings.append(
                "The model emitted Private Use Area characters, which are not "
                "valid N'Ko. They were removed; review this result carefully."
            )
            translation = cleaned
            if not translation:
                raise EmptyTranslationError(
                    "The provider returned only invalid (Private Use Area) characters."
                )

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
            human_verified=False,
            warnings=warnings,
        )
