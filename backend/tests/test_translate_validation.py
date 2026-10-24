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
