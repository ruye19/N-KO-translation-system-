"""N'Ko Unicode helpers.

Official N'Ko occupies U+07C0..U+07FF. The supplied dictionary PDF instead uses
a legacy font whose characters land in the Private Use Area (U+E000..U+F8FF).
PUA characters are meaningless outside that one font, so they must never be
presented to a user or sent to a model as if they were N'Ko.
"""

NKO_START, NKO_END = 0x07C0, 0x07FF
PUA_START, PUA_END = 0xE000, 0xF8FF


def is_nko_char(ch: str) -> bool:
    return NKO_START <= ord(ch) <= NKO_END


def is_pua_char(ch: str) -> bool:
    return PUA_START <= ord(ch) <= PUA_END


def contains_nko(text: str) -> bool:
    return any(is_nko_char(c) for c in text)


def contains_pua(text: str) -> bool:
    return any(is_pua_char(c) for c in text)


def strip_pua(text: str) -> str:
    return "".join(c for c in text if not is_pua_char(c))


def nko_ratio(text: str) -> float:
    """Share of non-space characters that are N'Ko. 0.0 for empty input."""
    meaningful = [c for c in text if not c.isspace()]
    if not meaningful:
        return 0.0
    return sum(1 for c in meaningful if is_nko_char(c)) / len(meaningful)
