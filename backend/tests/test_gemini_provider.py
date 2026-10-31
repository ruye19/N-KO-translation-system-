"""Exercise GeminiProvider's mapping of SDK outcomes. No network calls."""

# pyrefly: ignore[missing-import]
import pytest
from google.genai import errors

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
from app.services.providers.gemini_provider import GeminiProvider, looks_like_gemini_key
from app.services.providers.registry import get_provider

FAKE_KEY = "AIza-test-key-not-real"


class _Candidate:
    def __init__(self, finish_reason=None):
        self.finish_reason = finish_reason


class _Feedback:
    def __init__(self, block_reason=None):
        self.block_reason = block_reason


class _Response:
    def __init__(self, text="", candidates=None, prompt_feedback=None):
        self.text = text
        self.candidates = candidates if candidates is not None else [_Candidate("STOP")]
        self.prompt_feedback = prompt_feedback


class _StubModels:
    def __init__(self, result=None, error=None):
        self._result = result
        self._error = error
        self.kwargs = None

    def generate_content(self, **kwargs):
        self.kwargs = kwargs
        if self._error is not None:
            raise self._error
        return self._result


class _StubClient:
    def __init__(self, result=None, error=None):
        self.models = _StubModels(result, error)


def _client_error(code, message):
    """Build a google-genai ClientError without touching the network."""
    err = errors.ClientError.__new__(errors.ClientError)
    Exception.__init__(err, message)
    err.code = code
    err.message = message
    return err


def _provider(result=None, error=None, key=FAKE_KEY):
    p = GeminiProvider(Settings(_env_file=None, GEMINI_API_KEY=key))
    if key:
        p._client = _StubClient(result, error)
    return p


def test_registry_can_select_gemini():
    settings = Settings(_env_file=None, TRANSLATION_PROVIDER="gemini", GEMINI_API_KEY=FAKE_KEY)
    provider = get_provider(settings)
    assert provider.name == "gemini"
    assert provider.is_configured() is True


def test_unconfigured_provider_reports_it():
    p = GeminiProvider(Settings(_env_file=None, GEMINI_API_KEY=None))
    assert p.is_configured() is False
    with pytest.raises(ProviderNotConfiguredError):
        p.complete("sys", "user")


def test_successful_completion_returns_text():
    p = _provider(result=_Response(text="bonjour"))
    out = p.complete("sys", "user")
    assert out.text == "bonjour"
    assert out.warnings == []


def test_request_carries_model_system_prompt_and_contents():
    p = _provider(result=_Response(text="x"))
    p.complete("SYSTEM", "USER")
    kwargs = p._client.models.kwargs
    assert kwargs["model"] == "gemini-3.8-flash"
    assert kwargs["contents"] == "USER"
    assert kwargs["config"].system_instruction == "SYSTEM"


def test_suspended_project_gives_an_actionable_message():
    err = _client_error(403, "Permission denied: Consumer 'api_key:X' has been SUSPENDED.")
    p = _provider(error=err)
    with pytest.raises(ProviderAuthError) as exc:
        p.complete("sys", "user")
    assert "suspended" in str(exc.value).lower()
    assert "aistudio.google.com" in str(exc.value)


def test_plain_auth_failure_maps_to_auth_error():
    p = _provider(error=_client_error(401, "Unauthorized"))
    with pytest.raises(ProviderAuthError):
        p.complete("sys", "user")


def test_rate_limit_maps_to_rate_limit_error():
    p = _provider(error=_client_error(429, "Too many requests"))
    with pytest.raises(ProviderRateLimitError):
        p.complete("sys", "user")


def test_missing_model_maps_to_unavailable():
    p = _provider(error=_client_error(404, "model not found"))
    with pytest.raises(ProviderUnavailableError):
        p.complete("sys", "user")


def test_error_message_never_leaks_the_api_key():
    p = _provider(error=_client_error(403, f"Consumer 'api_key:{FAKE_KEY}' denied."))
    with pytest.raises(ProviderAuthError) as exc:
        p.complete("sys", "user")
    assert FAKE_KEY not in str(exc.value)


def test_blocked_prompt_is_a_refusal_not_a_translation():
    p = _provider(result=_Response(text="", prompt_feedback=_Feedback("SAFETY")))
    with pytest.raises(ProviderRefusedError):
        p.complete("sys", "user")


def test_safety_finish_reason_is_a_refusal():
    p = _provider(result=_Response(text="", candidates=[_Candidate("SAFETY")]))
    with pytest.raises(ProviderRefusedError):
        p.complete("sys", "user")


def test_max_tokens_finish_reason_adds_a_warning():
    p = _provider(result=_Response(text="partial", candidates=[_Candidate("MAX_TOKENS")]))
    out = p.complete("sys", "user")
    assert out.text == "partial"
    assert any("incomplete" in w for w in out.warnings)


def test_empty_text_raises_rather_than_returning_blank():
    p = _provider(result=_Response(text="   "))
    with pytest.raises(EmptyTranslationError):
        p.complete("sys", "user")


def test_key_format_check_is_advisory_only():
    assert looks_like_gemini_key("AIzaSyAbc123") is True
    assert looks_like_gemini_key("  AIzaSyAbc123  ") is True
    # An ephemeral 'AQ.' token: flagged, but still treated as configured.
    assert looks_like_gemini_key("AQ.Ab8RN6Lsomething") is False
    assert looks_like_gemini_key("") is False
    assert looks_like_gemini_key(None) is False

    p = GeminiProvider(Settings(_env_file=None, GEMINI_API_KEY="AQ.Ab8RN6L"))
    assert p.is_configured() is True


def test_network_failure_maps_to_unavailable_not_a_500():
    """google-genai raises raw httpx errors for DNS/connection problems."""
    import httpx

    p = _provider(error=httpx.ConnectError("getaddrinfo failed"))
    with pytest.raises(ProviderUnavailableError) as exc:
        p.complete("sys", "user")
    assert "network" in str(exc.value).lower()


def test_network_timeout_maps_to_provider_timeout():
    import httpx

    p = _provider(error=httpx.ReadTimeout("timed out"))
    with pytest.raises(ProviderTimeoutError):
        p.complete("sys", "user")
