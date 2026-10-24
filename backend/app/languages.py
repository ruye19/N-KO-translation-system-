"""Supported languages and translation directions for version 1."""

from typing import Dict, FrozenSet, Tuple

# Language codes used by the API. "nko" is N'Ko (ISO 639-3: nqo).
ENGLISH = "en"
FRENCH = "fr"
NKO = "nko"

LANGUAGE_NAMES: Dict[str, str] = {
    ENGLISH: "English",
    FRENCH: "French",
    NKO: "N'Ko",
}

SUPPORTED_LANGUAGES: FrozenSet[str] = frozenset(LANGUAGE_NAMES)

# Version 1 deliberately supports only these four directions. English<->French
# is out of scope: this is an N'Ko translator, not a general translator.
SUPPORTED_DIRECTIONS: FrozenSet[Tuple[str, str]] = frozenset(
    {
        (ENGLISH, NKO),
        (FRENCH, NKO),
        (NKO, ENGLISH),
        (NKO, FRENCH),
    }
)


def language_name(code: str) -> str:
    return LANGUAGE_NAMES.get(code, code)


def is_supported_direction(source: str, target: str) -> bool:
    return (source, target) in SUPPORTED_DIRECTIONS


def directions_payload():
    """Serialisable list of directions, used by the frontend to build its menus."""
    return [
        {
            "source_language": s,
            "target_language": t,
            "source_name": language_name(s),
            "target_name": language_name(t),
        }
        for s, t in sorted(SUPPORTED_DIRECTIONS)
    ]
