"""Google Gemini provider.

The API key is read from settings (environment) and never leaves this process.
It is not logged, not echoed in errors, and not exposed through any route.

Select it with TRANSLATION_PROVIDER=gemini.
"""

import logging
import time
from email.utils import parsedate_to_datetime

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

# Temporary failures worth one more attempt. 504 is left out on purpose: it
# arrives only after the provider's own deadline, so a retry would double an
# already long wait. Auth (401/403), bad request (400) and unknown model (404)
# are permanent and never retried.
RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503})


class GeminiProvider(TranslationProvider):
    name = "gemini"

    def __init__(self, settings: Settings):
        self._settings = settings
        self._client = None
        self._sleep = time.sleep
        self._clock = time.monotonic

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

    def _call_with_retry(self, call):
        """Run `call`, retrying at most once after a temporary failure."""
        import httpx
        from google.genai import errors

        retries = min(max(self._settings.provider_max_retries, 0), 1)
        for attempt in range(retries + 1):
            started = self._clock()
            try:
                return call()
            except (errors.APIError, httpx.ConnectError) as exc:
                if attempt == retries:
                    raise
                delay = self._retry_delay(exc, self._clock() - started)
                if delay is None:
                    raise
                logger.info(
                    "Gemini temporary failure (%s); retrying once in %.1f s.",
                    getattr(exc, "code", None) or type(exc).__name__,
                    delay,
                )
                self._sleep(delay)

    def _retry_delay(self, exc, elapsed: float) -> float | None:
        """Seconds to wait before the retry, or None if it should not happen."""
        s = self._settings
        # A connection error means the request never reached Google, so a
        # retry cannot cause a duplicate generation.
        if getattr(exc, "code", None) not in RETRYABLE_STATUS_CODES and not _is_connect_error(exc):
            return None
        # A slow failure has already used much of the caller's time budget.
        if elapsed > s.request_timeout_seconds / 2:
            return None
        requested = _requested_retry_delay(exc)
        if requested is None:
            return s.provider_retry_delay_seconds
        if requested > s.provider_retry_max_delay_seconds:
            return None
        return max(requested, s.provider_retry_delay_seconds)

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
            response = self._call_with_retry(
                lambda: client.models.generate_content(
                    model=model,
                    contents=user_prompt,
                    config=config,
                )
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


def _is_connect_error(exc) -> bool:
    import httpx

    return isinstance(exc, httpx.ConnectError)


def _parse_seconds(value) -> float | None:
    """Parse a delay given as seconds ("2", "1.5s") or an HTTP date."""
    text = str(value).strip().removesuffix("s")
    try:
        return max(float(text), 0.0)
    except ValueError:
        pass
    try:
        when = parsedate_to_datetime(str(value))
    except (TypeError, ValueError):
        return None
    return max(when.timestamp() - time.time(), 0.0)


def _requested_retry_delay(exc) -> float | None:
    """The wait the provider asked for: a Retry-After header, or the
    RetryInfo detail Google puts in a 429 body."""
    headers = getattr(getattr(exc, "response", None), "headers", None)
    if headers is not None:
        value = headers.get("retry-after")
        if value:
            return _parse_seconds(value)
    details = getattr(exc, "details", None)
    if isinstance(details, dict):
        error = details.get("error", details)
        items = error.get("details") if isinstance(error, dict) else None
        for item in items or []:
            if isinstance(item, dict) and str(item.get("@type", "")).endswith("RetryInfo"):
                return _parse_seconds(item.get("retryDelay", ""))
    return None


def looks_like_gemini_key(key: str | None) -> bool:
    """Cheap format sanity check used for a startup warning.

    Advisory only -- it never blocks a request. Google AI Studio keys normally
    start with 'AIza'; an 'AQ.' prefix is a short-lived ephemeral token, which
    will stop working after a few minutes.
    """
    return bool(key) and key.strip().startswith("AIza")
