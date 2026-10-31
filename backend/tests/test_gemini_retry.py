"""GeminiProvider retries one temporary failure, and nothing else. No network calls."""

import httpx
import pytest
from conftest import build_service
from google.genai import errors

from app.config import Settings
from app.errors import (
    ProviderAuthError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from app.dependencies import get_translation_service
from app.main import app
from app.services.providers.gemini_provider import GeminiProvider

FAKE_KEY = "AIza-test-key-not-real"
NKO = "ߒߌߗ"


class _Response:
    def __init__(self, text):
        self.text = text
        self.candidates = []
        self.prompt_feedback = None


class _SequenceModels:
    """Raises or returns each outcome in turn, one per call."""

    def __init__(self, outcomes, clock=None, call_seconds=0.0):
        self._outcomes = list(outcomes)
        self._clock = clock
        self._call_seconds = call_seconds
        self.calls = 0

    def generate_content(self, **kwargs):
        self.calls += 1
        if self._clock is not None:
            self._clock.now += self._call_seconds
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class _Client:
    def __init__(self, models):
        self.models = models


class _Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def _error(code, status="UNAVAILABLE", details=None, headers=None):
    body = {"error": {"code": code, "message": f"upstream {code}", "status": status}}
    if details:
        body["error"]["details"] = details
    response = httpx.Response(code, headers=headers or {})
    cls = errors.ServerError if code >= 500 else errors.ClientError
    return cls(code, body, response)


def _provider(*outcomes, call_seconds=0.0, **settings):
    clock = _Clock()
    p = GeminiProvider(Settings(_env_file=None, GEMINI_API_KEY=FAKE_KEY, **settings))
    models = _SequenceModels(outcomes, clock, call_seconds)
    p._client = _Client(models)
    p._clock = clock
    p.slept = []
    p._sleep = p.slept.append
    return p, models


# --- Temporary failure, then success ----------------------------------------

@pytest.mark.parametrize("code", [429, 500, 502, 503])
def test_temporary_failure_then_success(code):
    p, models = _provider(_error(code), _Response(NKO))
    result = p.complete("system", "hello")
    assert result.text == NKO
    assert models.calls == 2
    assert p.slept == [1.0]


def test_connection_failure_then_success():
    p, models = _provider(httpx.ConnectError("connection refused"), _Response(NKO))
    assert p.complete("system", "hello").text == NKO
    assert models.calls == 2


def test_retry_after_header_is_honoured():
    p, _ = _provider(_error(503, headers={"Retry-After": "3"}), _Response(NKO))
    p.complete("system", "hello")
    assert p.slept == [3.0]


def test_google_retry_info_is_honoured():
    info = [{"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "2.5s"}]
    p, _ = _provider(_error(429, "RESOURCE_EXHAUSTED", details=info), _Response(NKO))
    p.complete("system", "hello")
    assert p.slept == [2.5]


def test_a_shorter_requested_delay_still_waits_the_minimum():
    p, _ = _provider(_error(503, headers={"Retry-After": "0"}), _Response(NKO))
    p.complete("system", "hello")
    assert p.slept == [1.0]


# --- No retry ---------------------------------------------------------------

def test_a_long_requested_delay_is_not_waited_for():
    info = [{"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "40s"}]
    p, models = _provider(_error(429, "RESOURCE_EXHAUSTED", details=info), _Response(NKO))
    with pytest.raises(ProviderRateLimitError):
        p.complete("system", "hello")
    assert models.calls == 1
    assert p.slept == []


def test_at_most_one_retry():
    p, models = _provider(_error(503), _error(503), _Response(NKO))
    with pytest.raises(ProviderUnavailableError):
        p.complete("system", "hello")
    assert models.calls == 2
    assert p.slept == [1.0]


@pytest.mark.parametrize("error,expected", [
    (_error(401, "UNAUTHENTICATED"), ProviderAuthError),
    (_error(403, "PERMISSION_DENIED"), ProviderAuthError),
    (_error(400, "INVALID_ARGUMENT"), ProviderUnavailableError),
    (_error(404, "NOT_FOUND"), ProviderUnavailableError),  # unsupported model
    (_error(504, "DEADLINE_EXCEEDED"), ProviderUnavailableError),
    (httpx.ReadTimeout("slow"), ProviderTimeoutError),
])
def test_permanent_or_slow_failures_are_not_retried(error, expected):
    p, models = _provider(error, _Response(NKO))
    with pytest.raises(expected):
        p.complete("system", "hello")
    assert models.calls == 1
    assert p.slept == []


def test_a_slow_temporary_failure_is_not_retried():
    """A 503 that took most of the time budget would double the wait."""
    p, models = _provider(_error(503), _Response(NKO), call_seconds=40, REQUEST_TIMEOUT_SECONDS=60)
    with pytest.raises(ProviderUnavailableError):
        p.complete("system", "hello")
    assert models.calls == 1


def test_retry_can_be_disabled():
    p, models = _provider(_error(503), _Response(NKO), PROVIDER_MAX_RETRIES=0)
    with pytest.raises(ProviderUnavailableError):
        p.complete("system", "hello")
    assert models.calls == 1


def test_more_than_one_retry_is_capped():
    p, models = _provider(_error(503), _error(503), _error(503), _Response(NKO), PROVIDER_MAX_RETRIES=5)
    with pytest.raises(ProviderUnavailableError):
        p.complete("system", "hello")
    assert models.calls == 2


def test_errors_after_retry_do_not_expose_details():
    p, _ = _provider(_error(503), _error(503))
    with pytest.raises(ProviderUnavailableError) as info:
        p.complete("system", "hello")
    assert "upstream" not in info.value.message
    assert FAKE_KEY not in info.value.message


# --- Through the API ----------------------------------------------------------

def test_api_response_is_unchanged_after_a_retried_request(client):
    p, models = _provider(_error(503), _Response(NKO))
    service = build_service(p)
    app.dependency_overrides[get_translation_service] = lambda: service
    r = client.post("/api/translate", json={"source_language": "en", "target_language": "nko", "text": "hello"})
    assert r.status_code == 200
    body = r.json()
    assert body["translation"] == NKO
    assert body["human_verified"] is False
    assert models.calls == 2


def test_api_reports_provider_unavailable_after_the_retry(client):
    p, models = _provider(_error(503), _error(503))
    service = build_service(p)
    app.dependency_overrides[get_translation_service] = lambda: service
    r = client.post("/api/translate", json={"source_language": "en", "target_language": "nko", "text": "hello"})
    assert r.status_code == 502
    assert r.json()["error"]["code"] == "provider_unavailable"
    assert "upstream" not in r.text
    assert models.calls == 2
