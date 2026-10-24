"""Dictionary retrieval interface and SQLite implementation.

Supports searching French headwords, retrieving verified N'Ko equivalents when
available, providing grammatical/provenance metadata, and clearly distinguishing
verified entries from entries whose N'Ko script is pending legacy font decoding.
Never invents entries or presents unverified PUA characters as N'Ko.
"""

import logging
import re
import sqlite3
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from app.config import Settings
from app.languages import FRENCH, NKO

logger = logging.getLogger(__name__)

# Common French stop words to skip during multi-word tokenization
FRENCH_STOP_WORDS = {
    "le", "la", "les", "l", "un", "une", "des", "du", "de", "d", "et", "ou",
    "en", "a", "à", "au", "aux", "ce", "cette", "ces", "dans", "par", "pour",
    "sur", "avec", "sans", "est", "sont", "qui", "que", "quoi", "dont", "où",
}


@dataclass
class DictionaryEntry:
    source_term: str
    target_term: str
    source_language: str
    target_language: str
    note: str | None = None
    is_verified: bool = False
    pos: str | None = None
    page_number: int | None = None


class DictionaryService(ABC):
    @abstractmethod
    def is_available(self) -> bool:
        """True when this service can access its data store."""

    @abstractmethod
    def lookup(self, text: str, source_language: str, target_language: str) -> list[DictionaryEntry]:
        """Return entries relevant to `text`. Must return [] when unavailable."""

    def format_context(self, entries: list[DictionaryEntry]) -> str | None:
        """Render entries as reference lines for the prompt.

        Unverified entries deliberately carry no N'Ko text: their raw script is
        undecoded legacy-font data, so emitting it would hand the model
        meaningless characters that look like N'Ko.

        Because the N'Ko is withheld, several senses of one headword would
        otherwise render as identical lines, so they are collapsed into one
        with a sense count.
        """
        if not entries:
            return None

        lines: list[str] = []
        seen_unverified: dict[tuple, int] = {}
        placeholders: list[tuple] = []

        for e in entries:
            if e.is_verified and e.target_term:
                pos_str = f" ({e.pos})" if e.pos else ""
                pg_str = f", p.{e.page_number}" if e.page_number else ""
                lines.append(
                    f"- {e.source_term}{pos_str} = {e.target_term} [Verified N'Ko{pg_str}]"
                )
            else:
                key = (e.source_term, e.pos, e.page_number)
                if key not in seen_unverified:
                    seen_unverified[key] = 0
                    placeholders.append(key)
                seen_unverified[key] += 1

        for source_term, pos, page_number in placeholders:
            count = seen_unverified[(source_term, pos, page_number)]
            pos_str = f"{pos}, " if pos else ""
            pg_str = f" p.{page_number}," if page_number else ""
            senses = f" {count} senses," if count > 1 else ""
            lines.append(
                f"- {source_term} [{pos_str}dictionary ref{pg_str}{senses} "
                "N'Ko script undecoded - do not treat as N'Ko]"
            )

        return "\n".join(lines) if lines else None


class NullDictionaryService(DictionaryService):
    """Returns nothing. Never invents entries."""

    reason = (
        "Dictionary retrieval is disabled or database is not configured."
    )

    def is_available(self) -> bool:
        return False

    def lookup(self, text: str, source_language: str, target_language: str) -> list[DictionaryEntry]:
        return []


class SQLiteDictionaryService(DictionaryService):
    """SQLite-backed searchable store for the French-N'Ko dictionary."""

    def __init__(self, db_path: str):
        self._db_path = Path(db_path)
        self._available = False
        self._verify_db()

    def _verify_db(self):
        if not self._db_path.exists():
            logger.warning("Dictionary database does not exist: %s", self._db_path)
            self._available = False
            return
        try:
            conn = sqlite3.connect(str(self._db_path))
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM dictionary_entries")
            count = cur.fetchone()[0]
            conn.close()
            self._available = True
            logger.info("SQLiteDictionaryService loaded %d entries from %s", count, self._db_path)
        except Exception as e:
            logger.error("Failed to connect to dictionary database: %s", e)
            self._available = False

    def is_available(self) -> bool:
        return self._available

    def _normalize(self, term: str) -> str:
        term = term.lower().strip()
        term = re.sub(r"[^\w\s\'-]", " ", term)
        return " ".join(term.split())

    def _extract_french_tokens(self, text: str) -> list[str]:
        words = re.findall(r"[a-zA-ZÀ-ÿœŒæÆ'’-]+", text.lower())
        candidates = []
        # Entire phrase first if under 50 chars
        full = self._normalize(text)
        if full and len(full) <= 50:
            candidates.append(full)
        for w in words:
            cleaned = w.strip("'’ -")
            if len(cleaned) >= 2 and cleaned not in FRENCH_STOP_WORDS and cleaned not in candidates:
                candidates.append(cleaned)
        return candidates[:8]

    def lookup(self, text: str, source_language: str, target_language: str) -> list[DictionaryEntry]:
        if not self.is_available() or not text:
            return []

        results: list[DictionaryEntry] = []
        seen_keys: set[str] = set()

        if source_language == FRENCH and target_language == NKO:
            tokens = self._extract_french_tokens(text)
            if not tokens:
                return []

            try:
                conn = sqlite3.connect(str(self._db_path))
                cur = conn.cursor()
                for token in tokens:
                    cur.execute(
                        """
                        SELECT headword, pos, sense_number, raw_target, verified_nko, is_verified, page_number
                        FROM dictionary_entries
                        WHERE headword_normalized = ?
                        ORDER BY is_verified DESC, sense_number ASC
                        LIMIT 3
                        """,
                        (token,),
                    )
                    rows = cur.fetchall()
                    for hw, pos, sense, raw_tgt, ver_nko, is_ver, pnum in rows:
                        key = f"{hw}_{pos}_{sense}"
                        if key in seen_keys:
                            continue
                        seen_keys.add(key)
                        is_verified_bool = bool(is_ver)
                        target_term = ver_nko if is_verified_bool else ""
                        note = (
                            f"POS: {pos}, verified N'Ko equivalent, p.{pnum}"
                            if is_verified_bool
                            else f"POS: {pos}, entry found in French-N'Ko dictionary p.{pnum} (N'Ko script pending font encoding verification)"
                        )
                        results.append(
                            DictionaryEntry(
                                source_term=hw,
                                target_term=target_term,
                                source_language=FRENCH,
                                target_language=NKO,
                                note=note,
                                is_verified=is_verified_bool,
                                pos=pos,
                                page_number=pnum,
                            )
                        )
                conn.close()
            except Exception as e:
                logger.error("Error querying dictionary database: %s", e)
                return []

        elif source_language == NKO and target_language == FRENCH:
            # Reverse lookup supported only for verified Unicode N'Ko
            try:
                conn = sqlite3.connect(str(self._db_path))
                cur = conn.cursor()
                cur.execute(
                    """
                    SELECT headword, pos, sense_number, verified_nko, page_number
                    FROM dictionary_entries
                    WHERE verified_nko = ? AND is_verified = 1
                    LIMIT 3
                    """,
                    (text.strip(),),
                )
                for hw, pos, sense, ver_nko, pnum in cur.fetchall():
                    results.append(
                        DictionaryEntry(
                            source_term=ver_nko,
                            target_term=hw,
                            source_language=NKO,
                            target_language=FRENCH,
                            note=f"POS: {pos}, French equivalent from dictionary p.{pnum}",
                            is_verified=True,
                            pos=pos,
                            page_number=pnum,
                        )
                    )
                conn.close()
            except Exception as e:
                logger.error("Error querying dictionary database: %s", e)
                return []

        # Directions involving English: no direct coverage in French-N'Ko dictionary; return []
        return results


def find_dictionary_db(settings: Settings) -> Optional[Path]:
    """Find dictionary sqlite database path from settings or candidate standard paths."""
    candidates = []
    if settings.dictionary_db_path:
        candidates.append(Path(settings.dictionary_db_path))

    # Standard candidate paths
    candidates.extend([
        Path("data/dictionary.sqlite"),
        Path("../data/dictionary.sqlite"),
        Path(__file__).resolve().parent.parent.parent.parent / "data" / "dictionary.sqlite",
    ])

    for path in candidates:
        if path.exists() and path.is_file():
            return path
    return None


def get_dictionary_service(settings: Settings) -> DictionaryService:
    if not settings.dictionary_enabled:
        return NullDictionaryService()

    db_path = find_dictionary_db(settings)
    if db_path:
        service = SQLiteDictionaryService(str(db_path))
        if service.is_available():
            return service

    logger.warning("Dictionary enabled in settings, but dictionary.sqlite database was not found.")
    return NullDictionaryService()
