from conftest import FakeProvider


def test_health_reports_ok_and_never_leaks_a_key(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["provider"] == "anthropic"
    assert body["provider_configured"] is False  # no key in the test env
    assert body["dictionary_enabled"] is False
    assert "api_key" not in str(body).lower()


def test_health_reports_configured_provider(client_with_provider):
    c = client_with_provider(FakeProvider(result="x"))
    body = c.get("/api/health").json()
    assert body["provider_configured"] is True
    assert body["model"] == "fake-model-1"


def test_languages_lists_exactly_the_four_directions(client):
    r = client.get("/api/languages")
    assert r.status_code == 200
    pairs = {(d["source_language"], d["target_language"]) for d in r.json()["directions"]}
    assert pairs == {("en", "nko"), ("fr", "nko"), ("nko", "en"), ("nko", "fr")}


def test_root_is_reachable(client):
    assert client.get("/").status_code == 200
