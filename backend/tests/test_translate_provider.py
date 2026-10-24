"""Provider configuration, failure handling, and response shape."""

from conftest import FakeProvider

from app.errors import (
    ProviderAuthError,
    ProviderNotConfiguredError,
    ProviderRateLimitError,
    ProviderRefusedError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)

NKO_HELLO = "ߒߌߗ"
PUA_TEXT = ""  # legacy dictionary-font characters, not valid N'Ko


def _post(c, text="hello", source="en", target="nko"):
    return c.post(
        "/api/translate",
        json={"source_language": source, "target_language": target, "text": text},
    )


def test_missing_credentials_gives_a_setup_message_not_a_crash(client):
    # No override: the real (unconfigured) Anthropic provider is used.
    r = _post(client)
    assert r.status_code == 503
    body = r.json()["error"]
    assert body["code"] == "provider_not_configured"
    assert "ANTHROPIC_API_KEY" in body["message"]


def test_app_starts_without_credentials(client):
    # If the app had crashed on a missing key, this call could not succeed.
    assert client.get("/api/health").json()["provider_configured"] is False


def test_provider_unconfigured_flag_is_respected(client_with_provider):
    c = client_with_provider(FakeProvider(configured=False))
    assert _post(c).status_code == 503


def test_provider_failures_map_to_sensible_statuses(client_with_provider):
    cases = [
        (ProviderAuthError(), 502, "provider_auth_failed"),
        (ProviderRateLimitError(), 429, "provider_rate_limited"),
        (ProviderTimeoutError(), 504, "provider_timeout"),
        (ProviderUnavailableError(), 502, "provider_unavailable"),
        (ProviderRefusedError(), 422, "provider_refused"),
        (ProviderNotConfiguredError(), 503, "provider_not_configured"),
    ]
    for error, status, code in cases:
        c = client_with_provider(FakeProvider(error=error))
        r = _post(c)
        assert r.status_code == status, f"{code}: {r.text}"
        assert r.json()["error"]["code"] == code


def test_provider_failure_never_returns_the_input_as_a_translation(client_with_provider):
    c = client_with_provider(FakeProvider(error=ProviderUnavailableError()))
    r = _post(c, text="hello")
    assert r.status_code >= 400
    assert "translation" not in r.json()


def test_response_structure_is_complete(client_with_provider):
    c = client_with_provider(FakeProvider(result=NKO_HELLO))
    body = _post(c).json()
    for key in (
        "translation",
        "source_language",
        "target_language",
        "provider",
        "model",
        "dictionary_used",
        "human_verified",
        "notice",
        "warnings",
    ):
        assert key in body, f"missing {key}"
    assert body["human_verified"] is False
    assert body["dictionary_used"] is False  # dictionary is disabled in v1


def test_pua_characters_are_stripped_and_flagged(client_with_provider):
    c = client_with_provider(FakeProvider(result=NKO_HELLO + PUA_TEXT))
    body = _post(c).json()
    assert body["translation"] == NKO_HELLO
    assert any("Private Use Area" in w for w in body["warnings"])


def test_pua_only_output_is_an_error_not_a_translation(client_with_provider):
    c = client_with_provider(FakeProvider(result=PUA_TEXT))
    r = _post(c)
    assert r.status_code == 502
    assert r.json()["error"]["code"] == "empty_translation"


def test_missing_nko_in_nko_output_is_flagged(client_with_provider):
    c = client_with_provider(FakeProvider(result="hello there"))
    body = _post(c).json()
    assert any("no N'Ko characters" in w for w in body["warnings"])


def test_prompt_requests_unicode_nko_and_forbids_pua(client_with_provider):
    provider = FakeProvider(result=NKO_HELLO)
    c = client_with_provider(provider)
    _post(c)
    system_prompt, user_prompt = provider.calls[0]
    assert "U+07C0" in system_prompt
    assert "U+E000" in system_prompt
    assert "hello" in user_prompt
