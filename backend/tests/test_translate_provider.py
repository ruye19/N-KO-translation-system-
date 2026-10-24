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


def test_mixed_valid_and_pua_output_is_rejected_not_silently_stripped(client_with_provider):
    """Deleting the bad characters would change the meaning of the rest.

    The whole response is rejected instead, so a corrupted translation is never
    presented as a success.
    """
    c = client_with_provider(FakeProvider(result=NKO_HELLO + PUA_TEXT))
    r = _post(c)
    assert r.status_code == 502
    assert r.json()["error"]["code"] == "invalid_output_encoding"
    assert "translation" not in r.json()


def test_pua_only_output_is_an_error_not_a_translation(client_with_provider):
    c = client_with_provider(FakeProvider(result=PUA_TEXT))
    r = _post(c)
    assert r.status_code == 502
    assert r.json()["error"]["code"] == "invalid_output_encoding"


def test_valid_unicode_nko_output_is_accepted(client_with_provider):
    c = client_with_provider(FakeProvider(result=NKO_HELLO))
    body = _post(c).json()
    assert body["translation"] == NKO_HELLO
    assert body["warnings"] == []


def test_french_accents_are_not_mistaken_for_bad_encoding(client_with_provider):
    """French output is ordinary Latin-1; accents must pass through intact."""
    french = "Comment allez-vous ? J'ai mangé du pain à l'hôtel, ça va très bien."
    c = client_with_provider(FakeProvider(result=french))
    r = c.post(
        "/api/translate",
        json={"source_language": "nko", "target_language": "fr", "text": NKO_HELLO},
    )
    assert r.status_code == 200
    assert r.json()["translation"] == french


def test_english_output_is_accepted_without_nko_warning(client_with_provider):
    c = client_with_provider(FakeProvider(result="How are you?"))
    r = c.post(
        "/api/translate",
        json={"source_language": "nko", "target_language": "en", "text": NKO_HELLO},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["translation"] == "How are you?"
    # The "no N'Ko characters" warning applies only when N'Ko is the target.
    assert not any("no N'Ko characters" in w for w in body["warnings"])


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
