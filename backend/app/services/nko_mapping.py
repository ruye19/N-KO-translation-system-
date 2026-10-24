"""N'Ko Character and Font Encoding Mapping.

Records verified character mappings between legacy PDF font representations
and official Unicode N'Ko (U+07C0..U+07FF), and clearly marks unverified PUA
(Private Use Area) code points as UNKNOWN.

CRITICAL PRINCIPLE:
Never claim an unverified PUA code point is valid Unicode N'Ko without
deterministic encoding specification or verified ground-truth evidence.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class MappingStatus(str, Enum):
    VERIFIED = "verified"
    UNVERIFIED_PUA = "unverified_pua"
    UNKNOWN = "unknown"


@dataclass
class MappingEntry:
    source_char: str
    source_codepoint: int
    target_unicode: Optional[str]
    status: MappingStatus
    confidence: float
    description: str


@dataclass
class ConversionResult:
    raw_text: str
    converted_text: str
    is_verified: bool
    status: MappingStatus
    unresolved_chars: list[str] = field(default_factory=list)


# Verified digit mappings: The legacy N'ko2Manden font mapped N'Ko digits to
# Arabic-Indic digit codepoints U+0660..U+0669. In official Unicode N'Ko, these
# correspond to U+07C0..U+07C9.
VERIFIED_DIGIT_MAP: dict[int, str] = {
    0x0660: "\u07C0",  # ߀ N'KO DIGIT ZERO
    0x0661: "\u07C1",  # ߁ N'KO DIGIT ONE
    0x0662: "\u07C2",  # ߂ N'KO DIGIT TWO
    0x0663: "\u07C3",  # ߃ N'KO DIGIT THREE
    0x0664: "\u07C4",  # ߄ N'KO DIGIT FOUR
    0x0665: "\u07C5",  # ߅ N'KO DIGIT FIVE
    0x0666: "\u07C6",  # ߆ N'KO DIGIT SIX
    0x0667: "\u07C7",  # ߇ N'KO DIGIT SEVEN
    0x0668: "\u07C8",  # ߈ N'KO DIGIT EIGHT
    0x0669: "\u07C9",  # ߉ N'KO DIGIT NINE
}

# Verified punctuation mappings:
VERIFIED_PUNCTUATION_MAP: dict[int, str] = {
    0x060C: "\u07F8",  # ߸ N'KO COMMA (Arabic comma in legacy font)
    0x061B: "\u061B",  # Arabic semicolon (used in N'Ko typography)
    0x061F: "\u061F",  # Arabic question mark
    0x002E: ".",       # Full stop
    0x003A: ":",       # Colon
    0x0028: "(",       # Parentheses
    0x0029: ")",
    0x002F: "/",       # Slash
    0x002D: "-",       # Hyphen
    0x0020: " ",       # Space
}


def is_pua(cp: int) -> bool:
    """True if codepoint is in BMP Private Use Area (U+E000..U+F8FF)."""
    return 0xE000 <= cp <= 0xF8FF


def is_unicode_nko(cp: int) -> bool:
    """True if codepoint is in the official Unicode N'Ko block (U+07C0..U+07FF)."""
    return 0x07C0 <= cp <= 0x07FF


def get_mapping_entry(char: str) -> MappingEntry:
    cp = ord(char)
    if is_unicode_nko(cp):
        return MappingEntry(
            source_char=char,
            source_codepoint=cp,
            target_unicode=char,
            status=MappingStatus.VERIFIED,
            confidence=1.0,
            description="Native Unicode N'Ko character (U+07C0..U+07FF)",
        )
    if cp in VERIFIED_DIGIT_MAP:
        target = VERIFIED_DIGIT_MAP[cp]
        return MappingEntry(
            source_char=char,
            source_codepoint=cp,
            target_unicode=target,
            status=MappingStatus.VERIFIED,
            confidence=1.0,
            description=f"Arabic-Indic digit to Unicode N'Ko digit ({target})",
        )
    if cp in VERIFIED_PUNCTUATION_MAP:
        target = VERIFIED_PUNCTUATION_MAP[cp]
        return MappingEntry(
            source_char=char,
            source_codepoint=cp,
            target_unicode=target,
            status=MappingStatus.VERIFIED,
            confidence=1.0,
            description=f"Punctuation mapping ({target})",
        )
    if is_pua(cp):
        return MappingEntry(
            source_char=char,
            source_codepoint=cp,
            target_unicode=None,
            status=MappingStatus.UNVERIFIED_PUA,
            confidence=0.0,
            description="Legacy Private Use Area glyph (unresolved without original font layout)",
        )
    return MappingEntry(
        source_char=char,
        source_codepoint=cp,
        target_unicode=char if cp < 128 else None,
        status=MappingStatus.VERIFIED if cp < 128 else MappingStatus.UNKNOWN,
        confidence=1.0 if cp < 128 else 0.0,
        description="Standard ASCII" if cp < 128 else "Unknown non-ASCII character",
    )


def convert_nko_token(text: str) -> ConversionResult:
    """Convert a token or string from the dictionary.

    Returns a ConversionResult indicating whether all non-space characters
    were deterministically resolved into official Unicode N'Ko / verified text.
    If ANY character is an unverified PUA codepoint, `is_verified` is False,
    the raw text is preserved, and `unresolved_chars` lists the unknown codes.
    """
    if not text:
        return ConversionResult(
            raw_text="",
            converted_text="",
            is_verified=False,
            status=MappingStatus.UNKNOWN,
            unresolved_chars=[],
        )

    converted_chars: list[str] = []
    unresolved: list[str] = []
    all_verified = True

    for char in text:
        entry = get_mapping_entry(char)
        if entry.status == MappingStatus.VERIFIED and entry.target_unicode is not None:
            converted_chars.append(entry.target_unicode)
        else:
            all_verified = False
            unresolved.append(f"U+{ord(char):04X}")
            converted_chars.append(char)

    # Check if there is any actual N'Ko content in the converted text
    final_text = "".join(converted_chars).strip()
    has_nko = any(is_unicode_nko(ord(c)) for c in final_text)

    # If all chars were verified AND we have valid characters
    is_verified = all_verified and has_nko

    status = (
        MappingStatus.VERIFIED
        if is_verified
        else (MappingStatus.UNVERIFIED_PUA if unresolved else MappingStatus.UNKNOWN)
    )

    return ConversionResult(
        raw_text=text,
        converted_text=final_text if is_verified else "",
        is_verified=is_verified,
        status=status,
        unresolved_chars=unresolved,
    )
