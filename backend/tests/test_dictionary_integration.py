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
