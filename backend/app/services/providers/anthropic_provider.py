"""Anthropic Claude provider.

The API key is read from settings (environment) and never leaves this process.
It is not logged, not echoed in errors, and not exposed through any route.
"""

import logging

from app.config import Settings
from app.errors import (
    EmptyTranslationError,
    ProviderAuthError,
    ProviderNotConfiguredError,
    ProviderRateLimitError,
    ProviderRefusedError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from app.services.providers.base import ProviderResult, TranslationProvider

logger = logging.getLogger(__name__)


class AnthropicProvider(TranslationProvider):
    name = "anthropic"

    def __init__(self, settings: Settings):
        self._settings = settings
        self._client = None

    def is_configured(self) -> bool:
        return bool(self._settings.anthropic_api_key)

    def model_name(self) -> str:
        return self._settings.anthropic_model

    def _get_client(self):
        if self._client is not None:
            return self._client
        if not self.is_configured():
            raise ProviderNotConfiguredError()
        try:
            import anthropic
        except ImportError as exc:  # pragma: no cover - dependency is declared
            raise ProviderUnavailableError(
                "The 'anthropic' package is not installed. Run: "
                "pip install -r backend/requirements.txt"
            ) from exc
        self._client = anthropic.Anthropic(
            api_key=self._settings.anthropic_api_key,
            timeout=self._settings.request_timeout_seconds,
        )
        return self._client

    def complete(self, system_prompt: str, user_prompt: str) -> ProviderResult:
        import anthropic

        client = self._get_client()
        model = self.model_name()

        try:
            response = client.messages.create(
                model=model,
                max_tokens=self._settings.anthropic_max_tokens,
                system=system_prompt,
                output_config={"effort": self._settings.anthropic_effort},
                messages=[{"role": "user", "content": user_prompt}],
            )
        except anthropic.AuthenticationError as exc:
            logger.warning("Anthropic rejected credentials (request failed auth).")
            raise ProviderAuthError() from exc
        except anthropic.PermissionDeniedError as exc:
            raise ProviderAuthError(
                "The provider credentials lack permission for this model."
            ) from exc
        except anthropic.NotFoundError as exc:
            raise ProviderUnavailableError(
                f"The configured model '{model}' was not found. "
                "Check ANTHROPIC_MODEL in backend/.env."
            ) from exc
        except anthropic.RateLimitError as exc:
            raise ProviderRateLimitError() from exc
        except anthropic.APITimeoutError as exc:
            raise ProviderTimeoutError() from exc
        except anthropic.APIConnectionError as exc:
            raise ProviderUnavailableError(
                "Could not reach the translation provider. Check the network connection."
            ) from exc
        except anthropic.APIStatusError as exc:
            # Log the status only. exc.message can carry request echoes.
            logger.warning("Anthropic API returned status %s", exc.status_code)
            raise ProviderUnavailableError() from exc

        # A refusal is an HTTP 200 with stop_reason == "refusal". Check it
        # before reading content, which may be empty.
        if getattr(response, "stop_reason", None) == "refusal":
            raise ProviderRefusedError()

        warnings: list[str] = []
        if getattr(response, "stop_reason", None) == "max_tokens":
            warnings.append(
                "The translation hit the output length limit and may be incomplete. "
                "Try translating a shorter passage."
            )

        parts = [
            block.text
            for block in (response.content or [])
            if getattr(block, "type", None) == "text"
        ]
        text = "".join(parts).strip()
        if not text:
            raise EmptyTranslationError()

        return ProviderResult(text=text, model=model, warnings=warnings)


def looks_like_anthropic_key(key: str | None) -> bool:
    """Cheap format sanity check used for a startup warning.

    Advisory only: it never blocks a request, because Anthropic also accepts
    other credential forms. It exists to catch the common case of pasting a
    token from a different service into ANTHROPIC_API_KEY.
    """
    return bool(key) and key.strip().startswith("sk-ant-")
