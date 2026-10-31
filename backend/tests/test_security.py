"""Access key and rate limit on POST /api/translate. No network calls."""

import logging

import pytest
from conftest import TEST_ACCESS_KEY, FakeProvider

from app.config import Settings, get_settings
from app.main import app
from app.security import RateLimiter, get_rate_limiter, key_matches

NKO = "ߒߌߗ"
BODY = {"source_language": "en", "target_language": "nko", "text": "hello"}


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def _use_settings(**values):
    settings = Settings(_env_file=None, ANTHROPIC_API_KEY=None, **values)
    app.dependency_overrides[get_settings] = lambda: settings
    return settings


def _anonymous(client):
    """The shared clients send the test key by default; drop it."""
    client.headers.pop("Authorization", None)
    return client


# --- Access key -------------------------------------------------------------

def test_missing_key_is_rejected_before_the_provider_is_called(client_with_provider):
    provider = FakeProvider(result=NKO)
    c = _anonymous(client_with_provider(provider))
    r = c.post("/api/translate", json=BODY)
    assert r.status_code == 401
    assert r.json() == {"error": {"code": "unauthorized", "message": r.json()["error"]["message"]}}
    assert "Bearer" in r.json()["error"]["message"]
    assert r.headers["www-authenticate"] == "Bearer"
    assert provider.calls == []


@pytest.mark.parametrize("header", [
    "Bearer wrong-key-0123456789abcdef0123456789",
    f"Bearer {TEST_ACCESS_KEY}x",
    f"Bearer {TEST_ACCESS_KEY[:-1]}",
    f"Basic {TEST_ACCESS_KEY}",  # right secret, wrong scheme
    TEST_ACCESS_KEY,             # no scheme at all
    "Bearer ",
])
def test_invalid_key_is_rejected(client_with_provider, header):
    provider = FakeProvider(result=NKO)
    c = _anonymous(client_with_provider(provider))
    r = c.post("/api/translate", json=BODY, headers={"Authorization": header})
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "unauthorized"
    assert provider.calls == []


def test_valid_key_is_accepted(client_with_provider):
    c = _anonymous(client_with_provider(FakeProvider(result=NKO)))
    r = c.post("/api/translate", json=BODY, headers={"Authorization": f"Bearer {TEST_ACCESS_KEY}"})
    assert r.status_code == 200
    assert r.json()["translation"] == NKO


def test_scheme_is_case_insensitive(client_with_provider):
    c = _anonymous(client_with_provider(FakeProvider(result=NKO)))
    r = c.post("/api/translate", json=BODY, headers={"Authorization": f"bearer {TEST_ACCESS_KEY}"})
    assert r.status_code == 200


def test_secrets_never_appear_in_responses_or_logs(client_with_provider, caplog):
    c = _anonymous(client_with_provider(FakeProvider(result=NKO)))
    guess = "Bearer guessed-secret-value-0123456789abcdef"
    with caplog.at_level(logging.DEBUG):
        r = c.post("/api/translate", json=BODY, headers={"Authorization": guess})
    assert r.status_code == 401
    for secret in (TEST_ACCESS_KEY, "guessed-secret-value"):
        assert secret not in r.text
        assert secret not in caplog.text
    assert "Rejected an invalid access key" in caplog.text


def test_several_keys_allow_rotation(client_with_provider):
    c = _anonymous(client_with_provider(FakeProvider(result=NKO)))
    _use_settings(TRANSLATOR_API_KEY=" old-key-0123456789abcdef0123456789 , new-key-0123456789abcdef0123456789 ")
    for key in ("old-key-0123456789abcdef0123456789", "new-key-0123456789abcdef0123456789"):
        r = c.post("/api/translate", json=BODY, headers={"Authorization": f"Bearer {key}"})
        assert r.status_code == 200, key
    r = c.post("/api/translate", json=BODY, headers={"Authorization": f"Bearer {TEST_ACCESS_KEY}"})
    assert r.status_code == 401


def test_no_configured_key_fails_closed(client_with_provider):
    provider = FakeProvider(result=NKO)
    c = client_with_provider(provider)
    _use_settings(TRANSLATOR_API_KEY="")
    r = c.post("/api/translate", json=BODY)
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "access_not_configured"
    assert provider.calls == []


def test_key_can_be_switched_off_for_local_development(client_with_provider):
    c = _anonymous(client_with_provider(FakeProvider(result=NKO)))
    _use_settings(TRANSLATOR_API_KEY="", REQUIRE_API_KEY=False)
    assert c.post("/api/translate", json=BODY).status_code == 200


def test_auth_is_checked_before_the_body(client_with_provider):
    """An unauthenticated caller learns nothing about request validation."""
    c = _anonymous(client_with_provider(FakeProvider(result=NKO)))
    r = c.post("/api/translate", json={"text": 1})
    assert r.status_code == 401


def test_health_and_languages_stay_public(client):
    c = _anonymous(client)
    assert c.get("/api/health").status_code == 200
    assert c.get("/api/languages").status_code == 200


def test_key_matches_checks_every_key():
    assert key_matches("b", ["a", "b"])
    assert not key_matches("c", ["a", "b"])
    assert not key_matches("", ["a"])
    assert not key_matches("a", [])


def test_settings_key_list_ignores_blanks():
    s = Settings(_env_file=None, TRANSLATOR_API_KEY=" k1 ,, k2 ,")
    assert s.translator_api_key_list == ["k1", "k2"]
    assert Settings(_env_file=None, TRANSLATOR_API_KEY=None).translator_api_key_list == []


def test_access_key_is_required_by_default(monkeypatch):
    for name in ("TRANSLATOR_API_KEY", "REQUIRE_API_KEY", "RATE_LIMIT_REQUESTS", "RATE_LIMIT_WINDOW_SECONDS"):
        monkeypatch.delenv(name, raising=False)
    s = Settings(_env_file=None)
    assert (s.rate_limit_requests, s.rate_limit_window_seconds) == (30, 60.0)
    assert s.require_api_key is True
    assert s.translator_api_key_list == []


# --- Rate limit -------------------------------------------------------------

@pytest.fixture
def limited(client_with_provider):
    """A client limited to 2 requests per 60 s, with a clock the test moves."""
    clock = FakeClock()
    limiter = RateLimiter(clock=clock)
    provider = FakeProvider(result=NKO)
    c = client_with_provider(provider)
    _use_settings(TRANSLATOR_API_KEY=TEST_ACCESS_KEY, RATE_LIMIT_REQUESTS=2, RATE_LIMIT_WINDOW_SECONDS=60)
    app.dependency_overrides[get_rate_limiter] = lambda: limiter
    return c, clock, provider


def test_rate_limit_exceeded_returns_429(limited):
    c, clock, provider = limited
    assert c.post("/api/translate", json=BODY).status_code == 200
    clock.now += 10
    assert c.post("/api/translate", json=BODY).status_code == 200
    r = c.post("/api/translate", json=BODY)
    assert r.status_code == 429
    assert r.json()["error"]["code"] == "rate_limited"
    assert "2 per 60 seconds" in r.json()["error"]["message"]
    assert r.headers["retry-after"] == "50"  # the first request leaves the window at t+60
    assert len(provider.calls) == 2


def test_rate_limit_window_expires(limited):
    c, clock, _ = limited
    c.post("/api/translate", json=BODY)
    clock.now += 30
    c.post("/api/translate", json=BODY)
    assert c.post("/api/translate", json=BODY).status_code == 429
    clock.now += 29.5  # first request still inside the window
    assert c.post("/api/translate", json=BODY).status_code == 429
    clock.now += 0.5  # now it has left: one slot frees up
    assert c.post("/api/translate", json=BODY).status_code == 200
    assert c.post("/api/translate", json=BODY).status_code == 429
    clock.now += 60
    assert c.post("/api/translate", json=BODY).status_code == 200


def test_failed_key_guesses_are_rate_limited_too(limited):
    c, _, provider = limited
    _anonymous(c)
    bad = {"Authorization": "Bearer guess-0123456789abcdef0123456789"}
    assert c.post("/api/translate", json=BODY, headers=bad).status_code == 401
    assert c.post("/api/translate", json=BODY, headers=bad).status_code == 401
    assert c.post("/api/translate", json=BODY, headers=bad).status_code == 429
    assert provider.calls == []


def test_forwarded_headers_do_not_reset_the_limit(limited):
    """The app never trusts X-Forwarded-For; a caller cannot pick a new identity."""
    c, _, _ = limited
    for i in range(2):
        c.post("/api/translate", json=BODY, headers={"X-Forwarded-For": f"203.0.113.{i}"})
    r = c.post("/api/translate", json=BODY, headers={"X-Forwarded-For": "198.51.100.7"})
    assert r.status_code == 429


def test_rate_limit_can_be_disabled(limited):
    c, _, _ = limited
    _use_settings(TRANSLATOR_API_KEY=TEST_ACCESS_KEY, RATE_LIMIT_REQUESTS=0)
    for _ in range(5):
        assert c.post("/api/translate", json=BODY).status_code == 200


def test_health_is_not_rate_limited(limited):
    c, _, _ = limited
    for _ in range(5):
        assert c.get("/api/health").status_code == 200


def test_limiter_counts_each_client_separately():
    clock = FakeClock()
    limiter = RateLimiter(clock=clock)
    assert limiter.hit("a", 1, 60) is None
    assert limiter.hit("a", 1, 60) == 60
    assert limiter.hit("b", 1, 60) is None


def test_limiter_forgets_idle_clients():
    clock = FakeClock()
    limiter = RateLimiter(clock=clock)
    for i in range(100):
        limiter.hit(f"client-{i}", 5, 60)
    clock.now += 61
    limiter.hit("late", 5, 60)
    assert list(limiter._hits) == ["late"]
