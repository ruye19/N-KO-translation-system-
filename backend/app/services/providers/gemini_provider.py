"""Google Gemini provider.

The API key is read from settings (environment) and never leaves this process.
It is not logged, not echoed in errors, and not exposed through any route.

Select it with TRANSLATION_PROVIDER=gemini.
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


class GeminiProvider(TranslationProvider):
    name = "gemini"

    def __init__(self, settings: Settings):
        self._settings = settings
        self._client = None

    def is_configured(self) -> bool:
        return bool(self._settings.gemini_api_key)

    def model_name(self) -> str:
        return self._settings.gemini_model.strip()

    def _get_client(self):
        if self._client is not None:
            return self._client
        if not self.is_configured():
            raise ProviderNotConfiguredError(
                "The Gemini provider is not configured. Set GEMINI_API_KEY in "
                "backend/.env and restart the server. See README.md for setup steps."
            )
        try:
            from google import genai
        except ImportError as exc:  # pragma: no cover - dependency is declared
            raise ProviderUnavailableError(
                "The 'google-genai' package is not installed. Run: "
                "pip install -r backend/requirements.txt"
            ) from exc
        self._client = genai.Client(api_key=self._settings.gemini_api_key)
        return self._client

    def _map_client_error(self, exc) -> Exception:
        """Turn a Gemini 4xx into our own error type. Never leaks the key."""
        code = getattr(exc, "code", None)
        message = str(exc)
        key = self._settings.gemini_api_key
        if key and key in message:
            message = message.replace(key, "<redacted>")

        if code == 429:
            return ProviderRateLimitError()
        if code in (401, 403):
            # 403 CONSUMER_SUSPENDED / billing problems land here too, and the
            # distinction matters to whoever has to fix it.
            if "SUSPENDED" in message.upper():
                return ProviderAuthError(
                    "Google has suspended the project behind this API key. Create "
                    "a new key at aistudio.google.com/apikey (or resolve the "
                    "suspension in the Google Cloud console), set GEMINI_API_KEY "
                    "in backend/.env, and restart the server."
                )
            return ProviderAuthError(
                "Google rejected the API key. Check GEMINI_API_KEY in "
                "backend/.env. Create a key at aistudio.google.com/apikey, then "
                "restart the server."
            )
        if code == 404:
            return ProviderUnavailableError(
                f"The configured model '{self.model_name()}' was not found. "
                "Check GEMINI_MODEL in backend/.env."
            )
        if code == 400 and "API key" in message:
            return ProviderAuthError(
                "Google rejected the API key as malformed. Check GEMINI_API_KEY "
                "in backend/.env."
            )
        logger.warning("Gemini client error (status %s).", code)
        return ProviderUnavailableError()

    def complete(self, system_prompt: str, user_prompt: str) -> ProviderResult:
        import httpx
        from google.genai import errors, types

        client = self._get_client()
        model = self.model_name()

        config = types.GenerateContentConfig(
            system_instruction=system_prompt,
            max_output_tokens=self._settings.gemini_max_tokens,
            temperature=self._settings.gemini_temperature,
            http_options=types.HttpOptions(
                timeout=int(self._settings.request_timeout_seconds * 1000)
            ),
        )

        try:
            response = client.models.generate_content(
                model=model,
                contents=user_prompt,
                config=config,
            )
        except errors.ClientError as exc:
            raise self._map_client_error(exc) from exc
        except errors.ServerError as exc:
            logger.warning("Gemini server error (status %s).", getattr(exc, "code", None))
            raise ProviderUnavailableError() from exc
        except errors.APIError as exc:
            logger.warning("Gemini API error.")
            raise ProviderUnavailableError() from exc
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError() from exc
        except httpx.TransportError as exc:
            # google-genai surfaces connection/DNS failures as raw httpx
            # errors rather than APIError, so they must be caught explicitly
            # or they would escape as a generic 500.
            logger.warning("Gemini transport error: %s", type(exc).__name__)
            raise ProviderUnavailableError(
                "Could not reach the translation provider. Check the network "
                "connection and any proxy or firewall settings."
            ) from exc
        except TimeoutError as exc:
            raise ProviderTimeoutError() from exc

        warnings: list[str] = []

        # A blocked prompt comes back as a normal response with no candidates.
        feedback = getattr(response, "prompt_feedback", None)
        if feedback is not None and getattr(feedback, "block_reason", None):
            raise ProviderRefusedError(
                "Google's safety filters blocked this text, so it was not translated."
            )

        candidates = getattr(response, "candidates", None) or []
        if candidates:
            reason = str(getattr(candidates[0], "finish_reason", "") or "")
            if "MAX_TOKENS" in reason:
                warnings.append(
                    "The translation hit the output length limit and may be "
                    "incomplete. Try translating a shorter passage."
                )
            elif "SAFETY" in reason or "BLOCK" in reason or "PROHIBITED" in reason:
                raise ProviderRefusedError(
                    "Google's safety filters blocked the translation of this text."
                )

        text = (getattr(response, "text", None) or "").strip()
        if not text:
            raise EmptyTranslationError()

        return ProviderResult(text=text, model=model, warnings=warnings)


def looks_like_gemini_key(key: str | None) -> bool:
    """Cheap format sanity check used for a startup warning.

    Advisory only -- it never blocks a request. Google AI Studio keys normally
    start with 'AIza'; an 'AQ.' prefix is a short-lived ephemeral token, which
    will stop working after a few minutes.
    """
    return bool(key) and key.strip().startswith("AIza")
