"""Integrity checks against the real extracted dictionary database.

These assert the properties the application relies on, and guard the central
safety claim: nothing in the database is presented as verified N'Ko while the
legacy font encoding is unresolved.

Skipped (not silently passed) when the database has not been generated.
"""

import sqlite3
from pathlib import Path

import pytest

from app.languages import FRENCH, NKO
from app.services.dictionary import SQLiteDictionaryService
from app.services.nko_mapping import is_pua, is_unicode_nko

REPO_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = REPO_ROOT / "data" / "dictionary.sqlite"
RAW_JSONL = REPO_ROOT / "data" / "raw_extraction.jsonl"

pytestmark = pytest.mark.skipif(
    not DB_PATH.exists(),
    reason=f"{DB_PATH} not present; run: python scripts/extract_dictionary.py",
)


@pytest.fixture(scope="module")
def conn():
    connection = sqlite3.connect(str(DB_PATH))
    yield connection
    connection.close()


def scalar(conn, sql: str):
    return conn.execute(sql).fetchone()[0]


def test_schema_has_the_columns_the_service_queries(conn):
    cols = {r[1] for r in conn.execute("PRAGMA table_info(dictionary_entries)")}
    required = {
        "headword",
        "headword_normalized",
        "pos",
        "sense_number",
        "raw_target",
        "verified_nko",
        "is_verified",
        "status",
        "page_number",
    }
    assert required <= cols, f"missing columns: {required - cols}"


def test_entry_counts_are_plausible(conn):
    total = scalar(conn, "SELECT COUNT(*) FROM dictionary_entries")
    distinct = scalar(conn, "SELECT COUNT(DISTINCT headword_normalized) FROM dictionary_entries")
    assert total > 30000, f"expected a full extraction, found {total} entries"
    assert distinct > 25000
    assert distinct <= total


def test_pages_cover_the_dictionary_body(conn):
    lo, hi = conn.execute(
        "SELECT MIN(page_number), MAX(page_number) FROM dictionary_entries"
    ).fetchone()
    pages = scalar(conn, "SELECT COUNT(DISTINCT page_number) FROM dictionary_entries")
    assert lo >= 1 and hi <= 498
    assert pages > 400, f"only {pages} pages represented"


def test_no_entry_claims_verified_nko(conn):
    """The core safety invariant while the font encoding is unresolved."""
    assert scalar(conn, "SELECT COUNT(*) FROM dictionary_entries WHERE is_verified = 1") == 0
    assert (
        scalar(
            conn,
            "SELECT COUNT(*) FROM dictionary_entries "
            "WHERE verified_nko IS NOT NULL AND TRIM(verified_nko) <> ''",
        )
        == 0
    )


def test_no_headword_is_empty(conn):
    assert scalar(conn, "SELECT COUNT(*) FROM dictionary_entries WHERE TRIM(headword) = ''") == 0
    assert (
        scalar(conn, "SELECT COUNT(*) FROM dictionary_entries WHERE TRIM(headword_normalized) = ''")
        == 0
    )


def test_status_values_are_from_the_known_set(conn):
    statuses = {r[0] for r in conn.execute("SELECT DISTINCT status FROM dictionary_entries")}
    assert statuses <= {"unverified_pua", "unknown", "verified", "passthrough"}, statuses
    # Nothing may be recorded as verified while is_verified is 0 everywhere.
    assert "verified" not in statuses


def test_raw_target_is_preserved_for_future_decoding(conn):
    """Raw legacy text must survive: it is the only record of the N'Ko."""
    total = scalar(conn, "SELECT COUNT(*) FROM dictionary_entries")
    empty = scalar(
        conn,
        "SELECT COUNT(*) FROM dictionary_entries WHERE raw_target IS NULL OR raw_target = ''",
    )
    assert empty / total < 0.01, f"{empty} of {total} entries lost their raw text"


def test_raw_target_really_does_contain_undecoded_pua(conn):
    """Confirms the blocker is real, not a mislabelling."""
    sample = [
        r[0]
        for r in conn.execute(
            "SELECT raw_target FROM dictionary_entries "
            "WHERE raw_target IS NOT NULL AND raw_target <> '' LIMIT 300"
        )
    ]
    with_pua = [s for s in sample if any(is_pua(ord(ch)) for ch in s)]
    assert len(with_pua) > len(sample) * 0.8, (
        "expected most raw targets to contain Private Use Area characters"
    )


def test_headword_normalization_is_lowercase_and_trimmed(conn):
    rows = [
        r[0]
        for r in conn.execute("SELECT headword_normalized FROM dictionary_entries LIMIT 2000")
    ]
    assert all(r == r.strip() for r in rows)
    assert all(r == r.lower() for r in rows)


def test_raw_extraction_file_is_preserved():
    assert RAW_JSONL.exists(), "raw extraction JSONL must be kept for future decoding"
    assert RAW_JSONL.stat().st_size > 0


# --- behaviour of the service against the real database -------------------


@pytest.fixture(scope="module")
def service():
    return SQLiteDictionaryService(str(DB_PATH))


def test_service_reports_available(service):
    assert service.is_available() is True


@pytest.mark.parametrize("word", ["bonjour", "manger", "eau", "maison"])
def test_common_french_words_are_found(service, word):
    entries = service.lookup(word, FRENCH, NKO)
    assert entries, f"{word!r} should exist in a 32k-entry French dictionary"
    assert all(e.is_verified is False for e in entries)
    assert all(e.target_term == "" for e in entries)


def test_unknown_word_returns_nothing(service):
    assert service.lookup("azertyuiop12345", FRENCH, NKO) == []


def test_lookup_never_returns_pua_text(service):
    """No undecoded glyph may escape the service in any field."""
    entries = service.lookup("Je veux manger du pain et boire de l'eau", FRENCH, NKO)
    assert entries
    for entry in entries:
        for field in (entry.source_term, entry.target_term, entry.note or ""):
            assert not any(is_pua(ord(ch)) for ch in field), f"PUA leaked in {field!r}"


def test_context_sent_to_the_model_is_free_of_pua_and_labelled(service):
    entries = service.lookup("Je veux manger du pain", FRENCH, NKO)
    context = service.format_context(entries)
    assert context
    assert not any(is_pua(ord(ch)) for ch in context)
    assert "undecoded" in context
    # No N'Ko block characters either: we have none to offer yet.
    assert not any(is_unicode_nko(ord(ch)) for ch in context)


def test_repeated_senses_collapse_into_one_reference_line(service):
    """'eau' has five senses; withholding the N'Ko would make them identical."""
    entries = service.lookup("eau", FRENCH, NKO)
    assert len(entries) > 1
    context = service.format_context(entries)
    eau_lines = [ln for ln in context.splitlines() if ln.startswith("- eau ")]
    assert len(eau_lines) == 1, f"expected one collapsed line, got {eau_lines}"
    assert "senses" in eau_lines[0]


def test_reverse_nko_lookup_yields_nothing_while_unverified(service):
    """No verified N'Ko exists, so N'Ko -> French cannot match anything."""
    assert service.lookup("ߒߌߗ", NKO, FRENCH) == []
