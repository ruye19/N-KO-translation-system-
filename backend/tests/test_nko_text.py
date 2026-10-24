from app.services import nko_text

NKO = "ߒߌ"
PUA = ""


def test_detects_nko():
    assert nko_text.contains_nko(NKO)
    assert not nko_text.contains_nko("hello")


def test_detects_and_strips_pua():
    assert nko_text.contains_pua(PUA)
    assert nko_text.strip_pua(NKO + PUA) == NKO
    assert not nko_text.contains_pua(nko_text.strip_pua(PUA))


def test_nko_ratio():
    assert nko_text.nko_ratio("") == 0.0
    assert nko_text.nko_ratio(NKO) == 1.0
    assert 0 < nko_text.nko_ratio(NKO + "ab") < 1
