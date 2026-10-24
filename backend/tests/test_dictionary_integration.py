"""Integration tests for dictionary usage within TranslationService."""

import sqlite3
from pathlib import Path

from conftest import FakeProvider
from app.config import Settings
from app.languages import FRENCH, NKO
from app.services.dictionary import SQLiteDictionaryService
from app.services.translation import TranslationService

NKO_HELLO = "ߒߌߗ"


def test_translation_service_uses_dictionary_when_available(tmp_path: Path):
    db_file = tmp_path / "dict.sqlite"
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
    cur.execute(
        """
        INSERT INTO dictionary_entries (
            headword, headword_normalized, pos, sense_number, raw_target, verified_nko, is_verified, status, page_number
        ) VALUES ('bonjour', 'bonjour', 'n.m.', 1, '\uF120', '', 0, 'unverified', 67)
        """
    )
    conn.commit()
    conn.close()

    settings = Settings(
        _env_file=None,
        ANTHROPIC_API_KEY="dummy",
        DICTIONARY_ENABLED=True,
        DICTIONARY_DB_PATH=str(db_file),
    )
    service = TranslationService(settings)
    provider = FakeProvider(result=NKO_HELLO)
    service._provider = provider

    resp = service.translate(source=FRENCH, target=NKO, text="Bonjour tout le monde")
    assert resp.dictionary_used is True
    assert resp.translation == NKO_HELLO

    # Ensure context was included in the user prompt to the provider
    assert len(provider.calls) == 1
    system_prompt, user_prompt = provider.calls[0]
    assert "bonjour" in user_prompt
    assert "dictionary ref" in user_prompt


def test_translation_service_dictionary_disabled_by_default():
    settings = Settings(
        _env_file=None,
        ANTHROPIC_API_KEY="dummy",
        DICTIONARY_ENABLED=False,
    )
    service = TranslationService(settings)
    provider = FakeProvider(result=NKO_HELLO)
    service._provider = provider

    resp = service.translate(source=FRENCH, target=NKO, text="Bonjour tout le monde")
    assert resp.dictionary_used is False


# --- accurate reporting of what the dictionary actually contributed --------


def _service_with_entries(entries):
    """Build a TranslationService whose dictionary returns `entries`."""
    from app.config import Settings
    from app.services.dictionary import DictionaryService
    from app.services.translation import TranslationService
    from conftest import FakeProvider

    class StubDictionary(DictionaryService):
        def is_available(self):
            return True

        def lookup(self, text, source_language, target_language):
            return list(entries)

    service = TranslationService(Settings(_env_file=None, ANTHROPIC_API_KEY=None))
    service._provider = FakeProvider(result="ߒߌߗ")
    service._dictionary = StubDictionary()
    return service


def _unverified_entry():
    from app.languages import FRENCH, NKO
    from app.services.dictionary import DictionaryEntry

    return DictionaryEntry(
        source_term="pain",
        target_term="",
        source_language=FRENCH,
        target_language=NKO,
        is_verified=False,
        pos="n.m.",
        page_number=307,
    )


def test_headword_match_does_not_claim_verified_nko():
    """dictionary_used means 'a headword matched', not 'N'Ko was supplied'."""
    service = _service_with_entries([_unverified_entry()])
    response = service.translate("fr", "nko", "du pain")

    assert response.dictionary_used is True
    assert response.dictionary_entries_found == 1
    assert response.dictionary_nko_verified is False
    assert response.human_verified is False


def test_no_dictionary_match_reports_nothing_used():
    service = _service_with_entries([])
    response = service.translate("fr", "nko", "xyzzy")

    assert response.dictionary_used is False
    assert response.dictionary_entries_found == 0
    assert response.dictionary_nko_verified is False


def test_verified_entry_would_set_the_verified_flag():
    """Guards the flag's meaning for when decoded N'Ko eventually exists."""
    from app.languages import FRENCH, NKO
    from app.services.dictionary import DictionaryEntry

    verified = DictionaryEntry(
        source_term="arbre",
        target_term="ߙߋߙ",
        source_language=FRENCH,
        target_language=NKO,
        is_verified=True,
        pos="n.m.",
        page_number=42,
    )
    response = _service_with_entries([verified]).translate("fr", "nko", "arbre")
    assert response.dictionary_nko_verified is True


def test_undecoded_entries_never_reach_the_prompt_as_nko():
    """The prompt must carry the label and no N'Ko-looking characters."""
    from app.services.nko_mapping import is_pua

    service = _service_with_entries([_unverified_entry()])
    service.translate("fr", "nko", "du pain")

    _system_prompt, user_prompt = service._provider.calls[0]
    assert "undecoded" in user_prompt
    assert "do not treat as N'Ko" in user_prompt
    assert not any(is_pua(ord(ch)) for ch in user_prompt)
    # And the model is told not to reconstruct N'Ko from the reference.
    assert "not" in user_prompt.lower() and "authoritative" in user_prompt.lower()


def test_dictionary_failure_does_not_break_translation():
    """A broken dictionary must degrade to a normal translation, not a 500."""
    from app.config import Settings
    from app.services.dictionary import DictionaryService
    from app.services.translation import TranslationService
    from conftest import FakeProvider

    class BrokenDictionary(DictionaryService):
        def is_available(self):
            return True

        def lookup(self, text, source_language, target_language):
            return []  # mirrors the service's own swallow-and-return-[] on error

    service = TranslationService(Settings(_env_file=None, ANTHROPIC_API_KEY=None))
    service._provider = FakeProvider(result="ߒߌߗ")
    service._dictionary = BrokenDictionary()

    response = service.translate("fr", "nko", "du pain")
    assert response.translation == "ߒߌߗ"
    assert response.dictionary_used is False
