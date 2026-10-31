import pytest
from conftest import FakeProvider

NKO_HELLO = "ߒߌߗ"  # three N'Ko letters


def _post(c, **kw):
    payload = {"source_language": "en", "target_language": "nko", "text": "hello"}
    payload.update(kw)
    return c.post("/api/translate", json=payload)


def test_empty_text_rejected(client_with_provider):
    c = client_with_provider(FakeProvider(result="x"))
    r = _post(c, text="   ")
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "empty_text"


def test_missing_field_is_a_422(client_with_provider):
    c = client_with_provider(FakeProvider(result="x"))
    r = c.post("/api/translate", json={"source_language": "en"})
    assert r.status_code == 422
    body = r.json()
    assert body["error"]["code"] == "invalid_request"
    assert "text: Field required" in body["error"]["message"]
    assert "target_language: Field required" in body["error"]["message"]


@pytest.mark.parametrize("content,kwargs,fragment", [
    ("wrong type", {"json": {"source_language": "en", "target_language": "nko", "text": 123}},
     "text: Input should be a valid string"),
    ("bad json", {"content": b"{bad", "headers": {"Content-Type": "application/json"}},
     "not valid JSON"),
])
def test_malformed_bodies_use_the_error_envelope_without_echoing_input(client_with_provider, content, kwargs, fragment):
    c = client_with_provider(FakeProvider(result="x"))
    r = c.post("/api/translate", **kwargs)
    assert r.status_code == 422
    assert set(r.json()) == {"error"}
    assert r.json()["error"]["code"] == "invalid_request"
    assert fragment in r.json()["error"]["message"]
    assert "123" not in r.text and "{bad" not in r.text


@pytest.mark.parametrize("method,path,status,code", [
    ("get", "/api/translate", 405, "method_not_allowed"),
    ("get", "/api/nothing-here", 404, "not_found"),
])
def test_routing_errors_use_the_error_envelope(client, method, path, status, code):
    r = getattr(client, method)(path)
    assert r.status_code == status
    assert r.json()["error"]["code"] == code


def test_text_too_long_rejected(client_with_provider):
    c = client_with_provider(FakeProvider(result="x"))
    r = _post(c, text="a" * 5001)
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "text_too_long"


def test_unsupported_language_rejected(client_with_provider):
    c = client_with_provider(FakeProvider(result="x"))
    r = _post(c, source_language="de")
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "unsupported_language"


def test_same_language_rejected(client_with_provider):
    c = client_with_provider(FakeProvider(result="x"))
    r = _post(c, source_language="en", target_language="en")
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "same_language"


def test_english_to_french_is_out_of_scope(client_with_provider):
    c = client_with_provider(FakeProvider(result="x"))
    r = _post(c, source_language="en", target_language="fr")
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "unsupported_direction"


@pytest.mark.parametrize(
    "source,target,text",
    [
        ("en", "nko", "How are you?"),
        ("fr", "nko", "Comment allez-vous ?"),
        ("nko", "en", NKO_HELLO),
        ("nko", "fr", NKO_HELLO),
    ],
)
def test_all_four_supported_directions_are_accepted(client_with_provider, source, target, text):
    expected = NKO_HELLO if target == "nko" else "How are you?"
    c = client_with_provider(FakeProvider(result=expected))
    r = c.post(
        "/api/translate",
        json={"source_language": source, "target_language": target, "text": text},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["source_language"] == source
    assert body["target_language"] == target
    assert body["translation"] == expected


def test_language_codes_are_case_insensitive(client_with_provider):
    c = client_with_provider(FakeProvider(result=NKO_HELLO))
    r = _post(c, source_language="EN", target_language="NKO")
    assert r.status_code == 200
