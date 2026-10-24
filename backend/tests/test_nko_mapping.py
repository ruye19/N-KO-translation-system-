"""Unit tests for N'Ko character and font encoding mapping."""

import pytest
from app.services.nko_mapping import (
    MappingStatus,
    VERIFIED_DIGIT_MAP,
    VERIFIED_PUNCTUATION_MAP,
    convert_nko_token,
    get_mapping_entry,
    is_pua,
    is_unicode_nko,
)


def test_is_pua_detects_bmp_private_use_area():
    assert is_pua(0xE000) is True
    assert is_pua(0xF120) is True
    assert is_pua(0xF1E1) is True
    assert is_pua(0xF8FF) is True

    # Outside PUA
    assert is_pua(0x07C0) is False  # Unicode N'Ko
    assert is_pua(0x0041) is False  # 'A'
    assert is_pua(0xDFFF) is False
    assert is_pua(0xF900) is False


def test_is_unicode_nko_detects_official_block():
    assert is_unicode_nko(0x07C0) is True  # N'KO DIGIT ZERO
    assert is_unicode_nko(0x07CA) is True  # N'KO LETTER A
    assert is_unicode_nko(0x07FF) is True  # End of N'Ko block

    # Outside block
    assert is_unicode_nko(0x07BF) is False
    assert is_unicode_nko(0x0800) is False
    assert is_unicode_nko(0x0660) is False


def test_get_mapping_entry_native_unicode():
    entry = get_mapping_entry("\u07CA")  # N'Ko letter A
    assert entry.status == MappingStatus.VERIFIED
    assert entry.target_unicode == "\u07CA"
    assert entry.confidence == 1.0


def test_get_mapping_entry_arabic_indic_digit():
    # 0x0660 -> \u07C0
    entry0 = get_mapping_entry("\u0660")
    assert entry0.status == MappingStatus.VERIFIED
    assert entry0.target_unicode == "\u07C0"

    # 0x0669 -> \u07C9
    entry9 = get_mapping_entry("\u0669")
    assert entry9.status == MappingStatus.VERIFIED
    assert entry9.target_unicode == "\u07C9"


def test_get_mapping_entry_punctuation():
    # Arabic comma (U+060C) -> N'Ko comma (U+07F8)
    comma_entry = get_mapping_entry("\u060C")
    assert comma_entry.status == MappingStatus.VERIFIED
    assert comma_entry.target_unicode == "\u07F8"


def test_get_mapping_entry_pua_is_unverified():
    entry = get_mapping_entry("\uF120")
    assert entry.status == MappingStatus.UNVERIFIED_PUA
    assert entry.target_unicode is None
    assert entry.confidence == 0.0


def test_convert_nko_token_with_pure_unicode():
    unicode_nko = "\u07CA\u07D2\u07CC"
    res = convert_nko_token(unicode_nko)
    assert res.is_verified is True
    assert res.converted_text == unicode_nko
    assert res.status == MappingStatus.VERIFIED
    assert len(res.unresolved_chars) == 0


def test_convert_nko_token_with_arabic_indic_digits():
    res = convert_nko_token("\u0661\u0662\u0663")
    assert res.is_verified is True
    assert res.converted_text == "\u07C1\u07C2\u07C3"
    assert res.status == MappingStatus.VERIFIED


def test_convert_nko_token_with_pua_fails_verification():
    # Contains legacy font PUA characters
    pua_text = "\uF120\uF121"
    res = convert_nko_token(pua_text)
    assert res.is_verified is False
    assert res.status == MappingStatus.UNVERIFIED_PUA
    assert len(res.unresolved_chars) == 2


def test_convert_nko_token_empty_string():
    res = convert_nko_token("")
    assert res.is_verified is False
    assert res.status == MappingStatus.UNKNOWN
