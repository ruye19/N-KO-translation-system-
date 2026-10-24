"""Unit tests for dictionary services and retrieval."""

import sqlite3
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

import pytest
from app.config import Settings
from app.languages import ENGLISH, FRENCH, NKO
from app.services.dictionary import (
    DictionaryEntry,
    NullDictionaryService,
    SQLiteDictionaryService,
    find_dictionary_db,
    get_dictionary_service,
)


@pytest.fixture
def temp_db(tmp_path: Path) -> Path:
    """Create a temporary SQLite database with known entries for testing."""
    db_file = tmp_path / "test_dict.sqlite"
    conn = sqlite3.connect(str(db_file))
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE dictionary_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            headword TEXT NOT NULL,
            headword_normalized TEXT NOT NULL,
            pos TEXT,
            sense_number INTEGER DEFAULT 1,
            raw_target TEXT NOT NULL,
            verified_nko TEXT NOT NULL DEFAULT '',
            is_verified INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'unverified',
            page_number INTEGER
        )
        """
    )
    # Insert an unverified French entry (standard case from PDF)
    cur.execute(
        """
        INSERT INTO dictionary_entries (
            headword, headword_normalized, pos, sense_number, raw_target, verified_nko, is_verified, status, page_number
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("bonjour", "bonjour", "n.m.", 1, "\uF120\uF121", "", 0, "unverified_pua", 67),
    )
    # Insert a verified French entry
    cur.execute(
        """
        INSERT INTO dictionary_entries (
            headword, headword_normalized, pos, sense_number, raw_target, verified_nko, is_verified, status, page_number
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("arbre", "arbre", "n.m.", 1, "\u07D9\u07CB\u07D9", "\u07D9\u07CB\u07D9", 1, "verified", 42),
    )
    conn.commit()
    conn.close()
    return db_file


def test_null_dictionary_service():
    service = NullDictionaryService()
    assert service.is_available() is False
    assert service.lookup("bonjour", FRENCH, NKO) == []
    assert service.lookup("\u07D9\u07CB\u07D9", NKO, FRENCH) == []
    assert service.format_context([]) is None


def test_sqlite_dictionary_missing_db(tmp_path: Path):
    missing_path = tmp_path / "nonexistent.sqlite"
    service = SQLiteDictionaryService(str(missing_path))
    assert service.is_available() is False
    assert service.lookup("bonjour", FRENCH, NKO) == []


def test_sqlite_dictionary_unverified_lookup(temp_db: Path):
    service = SQLiteDictionaryService(str(temp_db))
    assert service.is_available() is True

    entries = service.lookup("bonjour", FRENCH, NKO)
    assert len(entries) == 1
    entry = entries[0]
    assert entry.source_term == "bonjour"
    assert entry.target_term == ""  # Never fabricates N'Ko
    assert entry.is_verified is False
    assert entry.pos == "n.m."
    assert entry.page_number == 67
    assert "pending font encoding verification" in entry.note


def test_sqlite_dictionary_verified_lookup(temp_db: Path):
    service = SQLiteDictionaryService(str(temp_db))
    entries = service.lookup("arbre", FRENCH, NKO)
    assert len(entries) == 1
    entry = entries[0]
    assert entry.source_term == "arbre"
    assert entry.target_term == "\u07D9\u07CB\u07D9"
    assert entry.is_verified is True
    assert entry.page_number == 42


def test_sqlite_dictionary_reverse_lookup(temp_db: Path):
    service = SQLiteDictionaryService(str(temp_db))

    # Reverse lookup for verified entry succeeds
    entries = service.lookup("\u07D9\u07CB\u07D9", NKO, FRENCH)
    assert len(entries) == 1
    assert entries[0].source_term == "\u07D9\u07CB\u07D9"
    assert entries[0].target_term == "arbre"
    assert entries[0].is_verified is True

    # Reverse lookup for unverified / non-existent N'Ko returns []
    assert service.lookup("\uF120\uF121", NKO, FRENCH) == []


def test_sqlite_dictionary_english_returns_empty(temp_db: Path):
    service = SQLiteDictionaryService(str(temp_db))
    assert service.lookup("tree", ENGLISH, NKO) == []
    assert service.lookup("\u07D9\u07CB\u07D9", NKO, ENGLISH) == []


def test_sqlite_dictionary_tokenization_and_stop_words(temp_db: Path):
    service = SQLiteDictionaryService(str(temp_db))
    # Query with stop words and punctuation: "Le bonjour à vous !"
    entries = service.lookup("Le bonjour à vous !", FRENCH, NKO)
    found_headwords = [e.source_term for e in entries]
    assert "bonjour" in found_headwords


def test_format_context_distinguishes_verified_and_unverified():
    service = NullDictionaryService()
    unverified_entry = DictionaryEntry(
        source_term="bonjour",
        target_term="",
        source_language=FRENCH,
        target_language=NKO,
        is_verified=False,
        pos="n.m.",
        page_number=67,
    )
    verified_entry = DictionaryEntry(
        source_term="arbre",
        target_term="\u07D9\u07CB\u07D9",
        source_language=FRENCH,
        target_language=NKO,
        is_verified=True,
        pos="n.m.",
        page_number=42,
    )

    formatted = service.format_context([unverified_entry, verified_entry])
    assert formatted is not None
    assert "- bonjour [n.m., dictionary ref p.67, N'Ko script undecoded" in formatted
    # The unverified line must never carry N'Ko-looking text.
    assert "" not in formatted
    assert "- arbre (n.m.) = \u07D9\u07CB\u07D9 [Verified N'Ko, p.42]" in formatted


def test_find_dictionary_db_with_custom_path(temp_db: Path):
    settings = Settings(
        _env_file=None,
        ANTHROPIC_API_KEY=None,
        DICTIONARY_DB_PATH=str(temp_db),
    )
    found = find_dictionary_db(settings)
    assert found is not None
    assert found.resolve() == temp_db.resolve()


def test_find_dictionary_db_with_invalid_path():
    settings = Settings(
        _env_file=None,
        ANTHROPIC_API_KEY=None,
        DICTIONARY_DB_PATH="/nonexistent/path/db.sqlite",
    )
    found = find_dictionary_db(settings)
    # If the real data/dictionary.sqlite exists in workspace, it may find the candidate path,
    # or return None if outside workspace.
    # We test that find_dictionary_db returns None or a real existing file
    if found:
        assert found.exists()


def test_get_dictionary_service_toggle(temp_db: Path):
    # Disabled in settings -> NullDictionaryService
    settings_off = Settings(
        _env_file=None,
        ANTHROPIC_API_KEY=None,
        DICTIONARY_ENABLED=False,
        DICTIONARY_DB_PATH=str(temp_db),
    )
    assert isinstance(get_dictionary_service(settings_off), NullDictionaryService)

    # Enabled in settings with valid DB -> SQLiteDictionaryService
    settings_on = Settings(
        _env_file=None,
        ANTHROPIC_API_KEY=None,
        DICTIONARY_ENABLED=True,
        DICTIONARY_DB_PATH=str(temp_db),
    )
    service = get_dictionary_service(settings_on)
    assert isinstance(service, SQLiteDictionaryService)
    assert service.is_available() is True


def test_real_database_lookups_if_present():
    """Verify integration against data/dictionary.sqlite if the file has been generated."""
    # Resolve from the repository root, not the current working directory:
    # pytest runs from backend/, so a bare relative path silently skipped this
    # test even when the database was present.
    db_path = REPO_ROOT / "data" / "dictionary.sqlite"
    if not db_path.exists():
        pytest.skip(f"{db_path} not present; run scripts/extract_dictionary.py")

    service = SQLiteDictionaryService(str(db_path))
    assert service.is_available() is True

    # Lookup common French words
    entries = service.lookup("bonjour", FRENCH, NKO)
    assert len(entries) > 0
    assert entries[0].source_term == "bonjour"
    assert entries[0].is_verified is False
    assert entries[0].target_term == ""

    manger_entries = service.lookup("manger", FRENCH, NKO)
    assert len(manger_entries) > 0
    assert any("manger" in e.source_term for e in manger_entries)

    # Term definitely not in the dictionary
    non_existent = service.lookup("azertyuiop12345", FRENCH, NKO)
    assert non_existent == []
