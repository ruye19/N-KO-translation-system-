"""Dictionary retrieval interface.

Status in version 1: DISABLED, deliberately.

The supplied French-N'Ko dictionary PDF stores its N'Ko in a legacy embedded
font (N'ko2Manden-1saDofanen) whose characters map to the Private Use Area,
not to Unicode N'Ko. No verified PUA -> Unicode mapping exists yet, so any
"N'Ko" extracted from the PDF today would be unusable text. Feeding it to the
model would silently corrupt translations.

See docs/DICTIONARY_ENCODING_INVESTIGATION.md for the evidence.

`NullDictionaryService` is the active implementation. When a verified mapping
exists, add a real implementation of `DictionaryService` (e.g. SQLite FTS5
over extracted entries) and select it in `get_dictionary_service`.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.config import Settings


@dataclass
class DictionaryEntry:
    source_term: str
    target_term: str
    source_language: str
    target_language: str
    note: str | None = None


class DictionaryService(ABC):
    @abstractmethod
    def is_available(self) -> bool:
        """True when this service can return trustworthy entries."""

    @abstractmethod
    def lookup(self, text: str, source_language: str, target_language: str) -> list[DictionaryEntry]:
        """Return entries relevant to `text`. Must return [] when unavailable."""

    def format_context(self, entries: list[DictionaryEntry]) -> str | None:
        if not entries:
            return None
        return "\n".join(
            f"- {e.source_term} = {e.target_term}" + (f"  ({e.note})" if e.note else "")
            for e in entries
        )


class NullDictionaryService(DictionaryService):
    """Returns nothing. Never invents entries."""

    reason = (
        "Dictionary retrieval is disabled: the source PDF's N'Ko uses an "
        "unverified Private Use Area font encoding."
    )

    def is_available(self) -> bool:
        return False

    def lookup(self, text, source_language, target_language) -> list[DictionaryEntry]:
        return []


def get_dictionary_service(settings: Settings) -> DictionaryService:
    # Only the null implementation exists today. DICTIONARY_ENABLED is honoured
    # so that a future real implementation can be switched on without code
    # changes here, but enabling it now still yields no entries.
    return NullDictionaryService()
