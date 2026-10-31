"""CORS: only origins listed in CORS_ORIGINS may call the API from a browser.

The suite runs with the default list (the local Vite dev server). An external
website must be added to CORS_ORIGINS explicitly; nothing is open to "*".
"""

from app.config import Settings


def preflight(client, origin):
    return client.options("/api/translate", headers={
        "Origin": origin,
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type",
    })


def test_listed_origin_may_post_json(client):
    r = preflight(client, "http://localhost:5173")
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert "POST" in r.headers["access-control-allow-methods"]
    assert "access-control-allow-credentials" not in r.headers


def test_unlisted_origin_is_refused(client):
    r = preflight(client, "https://example.org")
    assert r.status_code == 400
    assert "access-control-allow-origin" not in r.headers


def test_origins_are_read_as_a_comma_separated_list():
    s = Settings(_env_file=None, CORS_ORIGINS=" https://a.example , https://b.example ,")
    assert s.cors_origin_list == ["https://a.example", "https://b.example"]
