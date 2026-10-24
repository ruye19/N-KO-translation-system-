"""Exercise AnthropicProvider's own translation of SDK outcomes.

The FakeProvider used elsewhere bypasses this file entirely, so these tests
cover the real mapping logic with a stub client. No network calls are made.
"""

import anthropic
import pytest

from app.config import Settings
from app.errors import (
    EmptyTranslationError,
    ProviderNotConfiguredError,
    ProviderRefusedError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from app.services.providers.anthropic_provider import AnthropicProvider


class _Block:
    def __init__(self, text, type="text"):
        self.text = text
        self.type = type


class _Response:
    def __init__(self, content, stop_reason="end_turn"):
        self.content = content
        self.stop_reason = stop_reason


class _StubMessages:
    def __init__(self, result=None, error=None):
        self._result = result
        self._error = error
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        if self._error is not None:
            raise self._error
        return self._result


class _StubClient:
    def __init__(self, result=None, error=None):
        self.messages = _StubMessages(result, error)


def _provider(result=None, error=None, key="test-key-not-real"):
    settings = Settings(_env_file=None, ANTHROPIC_API_KEY=key)
    p = AnthropicProvider(settings)
    if key:
        p._client = _StubClient(result, error)
    return p


def test_unconfigured_provider_reports_it():
    p = AnthropicProvider(Settings(_env_file=None, ANTHROPIC_API_KEY=None))
    assert p.is_configured() is False
    with pytest.raises(ProviderNotConfiguredError):
        p.complete("sys", "user")


def test_successful_completion_returns_text():
    p = _provider(result=_Response([_Block("bonjour")]))
    out = p.complete("sys", "user")
    assert out.text == "bonjour"
    assert out.warnings == []


def test_request_carries_model_system_and_effort():
    p = _provider(result=_Response([_Block("x")]))
    p.complete("SYSTEM", "USER")
    kwargs = p._client.messages.kwargs
    assert kwargs["model"] == "claude-opus-5"
    assert kwargs["system"] == "SYSTEM"
    assert kwargs["messages"] == [{"role": "user", "content": "USER"}]
    assert kwargs["output_config"] == {"effort": "medium"}


def test_refusal_is_not_treated_as_a_translation():
    p = _provider(result=_Response([], stop_reason="refusal"))
    with pytest.raises(ProviderRefusedError):
        p.complete("sys", "user")


def test_empty_content_raises_rather_than_returning_blank():
    p = _provider(result=_Response([]))
    with pytest.raises(EmptyTranslationError):
        p.complete("sys", "user")


def test_max_tokens_stop_reason_adds_a_warning():
    p = _provider(result=_Response([_Block("partial")], stop_reason="max_tokens"))
    out = p.complete("sys", "user")
    assert out.text == "partial"
    assert any("incomplete" in w for w in out.warnings)


def test_non_text_blocks_are_ignored():
    p = _provider(result=_Response([_Block("", "thinking"), _Block("real")]))
    assert p.complete("sys", "user").text == "real"


def test_timeout_maps_to_provider_timeout():
    err = anthropic.APITimeoutError(request=None)
    p = _provider(error=err)
    with pytest.raises(ProviderTimeoutError):
        p.complete("sys", "user")


def test_connection_error_maps_to_unavailable():
    err = anthropic.APIConnectionError(request=None)
    p = _provider(error=err)
    with pytest.raises(ProviderUnavailableError):
        p.complete("sys", "user")


def test_key_format_check_is_advisory_only():
    from app.services.providers.anthropic_provider import looks_like_anthropic_key

    assert looks_like_anthropic_key("sk-ant-api03-abc") is True
    assert looks_like_anthropic_key("  sk-ant-api03-abc  ") is True
    assert looks_like_anthropic_key("AQ.Ab8RN6Lsomethingelse") is False
    assert looks_like_anthropic_key("") is False
    assert looks_like_anthropic_key(None) is False

    # A non-standard key must still be treated as "configured": the check
    # warns, it never blocks a request.
    p = AnthropicProvider(Settings(_env_file=None, ANTHROPIC_API_KEY="AQ.Ab8RN6L"))
    assert p.is_configured() is True
