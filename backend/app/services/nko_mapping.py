"""N'Ko character and legacy font encoding mapping.

Distinguishes three different things that are easy to conflate:

1. RECOVERY   - a legacy codepoint whose glyph in the PDF font has been shown
                to be a particular Unicode N'Ko character. Only the digits
                qualify (see EVIDENCE below).
2. PASSTHROUGH - a character that is already valid and is kept exactly as it
                is (ASCII, French accents, Arabic punctuation). This is NOT
                recovery of N'Ko and must never, on its own, make text count
                as verified N'Ko.
3. UNRESOLVED - Private Use Area glyphs from the legacy font, which have no
                known Unicode equivalent.

CRITICAL PRINCIPLE
Never claim an unverified PUA code point is valid Unicode N'Ko without
deterministic encoding evidence.

EVIDENCE (measured 2026-10-24, reproducible with scripts/verify_glyph_mappings.py)
Glyphs were rendered from the PDF's embedded `N'ko2Manden-1saDofanen` subset
and compared by shape (intersection-over-union, best of a translation search)
against Ebrima, a Microsoft font with genuine Unicode N'Ko coverage.

Digits - legacy U+0660..U+0669 carry N'Ko digit glyphs:

    legacy    vs U+07Cx (N'Ko)   vs U+066x (Arabic-Indic)
    U+0660          0.602                 0.198
    U+0661          0.591                 0.126
    U+0662          0.526                 0.195
    U+0663          0.653                 0.183
    U+0664          0.636                 0.211
    U+0665          0.775                 0.124
    U+0666          0.606                 0.129
    U+0667          0.774                 0.279
    U+0668          0.695                 0.227
    U+0669          0.784                 0.230

All ten favour the N'Ko digit decisively and unanimously, so the digit
mapping is genuine recovery.

Punctuation - NOT recovered. A previous revision of this file claimed
U+060C -> U+07F8 (N'Ko comma) as "verified". Shape comparison refutes it:

    U+060C glyph vs U+07F8 (N'KO COMMA)      0.261
    U+060C glyph vs U+060C (ARABIC COMMA)    0.582   <- the actual glyph

The PDF's U+060C is an Arabic comma and rendering it as U+07F8 would silently
substitute a different character. U+061B and U+061F were likewise marked
"verified" without evidence (their PDF glyphs do not match the Arabic
semicolon/question mark cleanly either). All three are therefore passthrough
only, and U+061B's ToUnicode value is not trustworthy at all.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

NKO_BLOCK_START, NKO_BLOCK_END = 0x07C0, 0x07FF
PUA_START, PUA_END = 0xE000, 0xF8FF


class MappingStatus(str, Enum):
    #: Legacy codepoint deterministically recovered to Unicode N'Ko.
    VERIFIED = "verified"
    #: Already-valid character kept as-is. Not evidence of N'Ko.
    PASSTHROUGH = "passthrough"
    #: Legacy Private Use Area glyph with no known Unicode equivalent.
    UNVERIFIED_PUA = "unverified_pua"
    #: Anything else.
    UNKNOWN = "unknown"


@dataclass
class MappingEntry:
    source_char: str
    source_codepoint: int
    target_unicode: Optional[str]
    status: MappingStatus
    confidence: float
    description: str

    @property
    def is_resolved(self) -> bool:
        """True when the character can be emitted safely (recovered or kept)."""
        return (
            self.status in (MappingStatus.VERIFIED, MappingStatus.PASSTHROUGH)
            and self.target_unicode is not None
        )


@dataclass
class ConversionResult:
    raw_text: str
    converted_text: str
    is_verified: bool
    status: MappingStatus
    unresolved_chars: list[str] = field(default_factory=list)


# --- Recovery -------------------------------------------------------------
# The legacy font stores N'Ko digit glyphs at the Arabic-Indic digit
# codepoints. Shape-verified; see EVIDENCE in the module docstring.
VERIFIED_DIGIT_MAP: dict[int, str] = {
    0x0660 + i: chr(0x07C0 + i) for i in range(10)
}

# --- Passthrough ----------------------------------------------------------
# Characters kept exactly as they are. Mapping a character to itself is
# normalisation, not recovery, so none of these can make text "verified N'Ko".
PASSTHROUGH_PUNCTUATION: dict[int, str] = {
    cp: chr(cp)
    for cp in (
        0x060C,  # Arabic comma - the PDF glyph really is an Arabic comma
        0x061B,  # Arabic semicolon - ToUnicode value is NOT trustworthy here
        0x061F,  # Arabic question mark
        0x066A,  # Arabic percent sign
    )
}

#: Retained for backwards compatibility with earlier imports. These are
#: passthrough characters, despite the historical name.
VERIFIED_PUNCTUATION_MAP = PASSTHROUGH_PUNCTUATION


def is_pua(cp: int) -> bool:
    """True if codepoint is in the BMP Private Use Area (U+E000..U+F8FF)."""
    return PUA_START <= cp <= PUA_END


def is_unicode_nko(cp: int) -> bool:
    """True if codepoint is in the official Unicode N'Ko block (U+07C0..U+07FF)."""
    return NKO_BLOCK_START <= cp <= NKO_BLOCK_END


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
            description=(
                f"Legacy Arabic-Indic digit recovered to Unicode N'Ko digit "
                f"U+{ord(target):04X} (shape-verified)"
            ),
        )

    if cp in PASSTHROUGH_PUNCTUATION:
        return MappingEntry(
            source_char=char,
            source_codepoint=cp,
            target_unicode=char,
            status=MappingStatus.PASSTHROUGH,
            confidence=1.0,
            description="Punctuation kept unchanged (not recovered N'Ko)",
        )

    if is_pua(cp):
        return MappingEntry(
            source_char=char,
            source_codepoint=cp,
            target_unicode=None,
            status=MappingStatus.UNVERIFIED_PUA,
            confidence=0.0,
            description=(
                "Legacy Private Use Area glyph (unresolved without the "
                "original font layout)"
            ),
        )

    if cp < 128:
        return MappingEntry(
            source_char=char,
            source_codepoint=cp,
            target_unicode=char,
            status=MappingStatus.PASSTHROUGH,
            confidence=1.0,
            description="ASCII kept unchanged (not recovered N'Ko)",
        )

    # Everything else (e.g. French accents, Hebrew/Arabic letters that appear
    # in the extraction) is kept but never counts as N'Ko evidence.
    return MappingEntry(
        source_char=char,
        source_codepoint=cp,
        target_unicode=char,
        status=MappingStatus.PASSTHROUGH,
        confidence=1.0,
        description="Non-ASCII character kept unchanged (not recovered N'Ko)",
    )


def convert_nko_token(text: str) -> ConversionResult:
    """Convert a token or string extracted from the dictionary.

    `is_verified` is True only when BOTH hold:
      * every character resolved (no Private Use Area glyphs), and
      * at least one character is genuine N'Ko - either already in the N'Ko
        block or recovered from the evidence-backed digit map.

    Punctuation and ASCII alone can never satisfy the second condition, so a
    stray comma cannot masquerade as a verified N'Ko translation.

    When not verified, `converted_text` is empty: callers must fall back to the
    preserved `raw_text` rather than display a partial conversion.
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
    has_nko_evidence = False

    for char in text:
        entry = get_mapping_entry(char)
        if not entry.is_resolved:
            unresolved.append(f"U+{ord(char):04X}")
            converted_chars.append(char)
            continue
        converted_chars.append(entry.target_unicode)
        if entry.status is MappingStatus.VERIFIED:
            # Only native N'Ko or a recovered digit counts as evidence.
            has_nko_evidence = True

    final_text = "".join(converted_chars).strip()
    is_verified = not unresolved and has_nko_evidence

    if is_verified:
        status = MappingStatus.VERIFIED
    elif unresolved:
        status = MappingStatus.UNVERIFIED_PUA
    else:
        status = MappingStatus.UNKNOWN

    return ConversionResult(
        raw_text=text,
        converted_text=final_text if is_verified else "",
        is_verified=is_verified,
        status=status,
        unresolved_chars=unresolved,
    )
