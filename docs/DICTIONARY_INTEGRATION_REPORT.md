# French–N'Ko Dictionary Integration Report

**Date:** October 2026  
**Source Resource:** *Dictionnaire Bilingue Français - N'Ko* (1st edition, 2014) by Baba Mamadi Diané  
**Document Reference:** `docs/dictionnaire Fr_nko.pdf` (498 pages)

---

## 1. Executive Summary

This report documents the design, implementation, and verification of the French–N'Ko dictionary extraction and integration pipeline for the N'Ko AI Translator.

### Key Metrics & Outcomes
- **Pages Processed:** 477 pages (pages 22 to 498; entries start on page 22 after preliminary matter and abbreviations).
- **Total Entries Extracted:** **32,057** structured entries stored in `data/dictionary.sqlite`.
- **Distinct French Headwords:** **29,526** unique headwords with grammatical parts of speech (`n.m.`, `v.t.`, `adj.`, `locut.`, etc.) and page references.
- **Test Suite Status:** **78 backend tests passing** (54 existing + 24 new tests), **0 failures**, 100% regression-free.
- **Frontend Status:** Production build succeeds cleanly (`vite build` in 2.15s, 0 errors).

---

## 2. Font Encoding Investigation & Integrity Principle

### 2.1 Technical Findings
Investigation of `docs/dictionnaire Fr_nko.pdf` revealed two separate font encodings:
1. **French Text:** Encoded in standard Adobe Type 1 / TrueType fonts (`TimesNewRomanPSMT`, `ArialMT`) with standard ANSI/Unicode mapping. Text extraction is 100% deterministic and clear.
2. **N'Ko Body Text:** Encoded using a legacy pre-Unicode font named `N'ko2Manden-1saDofanen`. The PDF's internal `/ToUnicode` CMap maps every N'Ko character to the Unicode **Private Use Area (PUA)** in the range `U+F120` to `U+F1E1`.
3. **Incidental Unicode N'Ko (Ebrima):** The modern Unicode font `Ebrima` is only used on 9 non-body pages (such as page 2 copyright or page 8 preface), yielding only 7 incidental N'Ko characters (`U+07C0`–`U+07C5`, `U+07ED`, `U+07F2`). It was not used for the dictionary vocabulary.

### 2.2 Core Architectural Principle: No Hallucination, No Fake Unicode
Because the author's custom 2014 TrueType font binary (`N'ko2Manden-1saDofanen.ttf`) and keyboard layout are not present in the repository or local system, there is no deterministic mapping table between `U+F120..U+F1E1` and the official Unicode N'Ko block (`U+07C0..U+07FF`).

**Architectural Decision (Approach D):**
- **Strictly Honest Data Representation:** All 32,057 entries are stored with `is_verified = 0` and `verified_nko = ""`. The original PUA character string is preserved in `raw_target` for future decoding.
- **No PUA in Output:** The system never emits PUA characters to translation models or end users as valid N'Ko.
- **Reference Context:** When dictionary retrieval is enabled, French headwords, grammatical tags, and page numbers provide verified reference context to translation prompts.

---

## 3. Implemented Components

### 3.1 Extraction Pipeline (`scripts/extract_dictionary.py`)
- Automated CLI script supporting full PDF extraction, page range limits, and batch ingestion.
- Uses regex line parsing to extract French headwords, grammatical category abbreviations (based on the dictionary's page 6 abbreviations list), sense numbers, and target text.
- Generates:
  - `data/dictionary.sqlite`: Optimized SQLite database.
  - `data/raw_extraction.jsonl`: Line-delimited raw extraction stream.
  - `data/extraction_report.json`: Run summary and metrics.

### 3.2 Character Encoding Validator (`backend/app/services/nko_mapping.py`)
- `MappingStatus` enum (`VERIFIED`, `UNVERIFIED_PUA`, `UNKNOWN`).
- Maps Arabic-Indic digits (`U+0660`..`U+0669`) used in legacy N'Ko typography to official Unicode N'Ko digits (`U+07C0`..`U+07C9`).
- Maps legacy punctuation marks (`U+060C` Arabic comma to `U+07F8` N'Ko comma).
- Provides `is_pua(codepoint)`, `is_unicode_nko(codepoint)`, and `convert_nko_token(text)`.

### 3.3 Searchable Dictionary Service (`backend/app/services/dictionary.py`)
- `DictionaryService` interface and `DictionaryEntry` dataclass.
- `SQLiteDictionaryService`:
  - Tokenizes input text, strips accents/punctuation, filters common French stop words.
  - Searches `dictionary_entries` by `headword_normalized`.
  - Disallows reverse N'Ko->French lookup unless `is_verified == 1`.
  - Formats retrieved entries with clear provenance (`- bonjour [n.m., dictionary ref p.67, N'Ko script unverified]`).
- Auto-discovery mechanism (`find_dictionary_db`) locating `data/dictionary.sqlite` in standard workspace locations.

### 3.4 Translation Orchestration (`backend/app/services/translation.py`)
- Integrates dictionary retrieval into the `translate()` workflow.
- Injects formatted dictionary context into translation prompts when available.
- Sets `dictionary_used: true` in the API response when relevant entries are retrieved.

---

## 4. Database Schema

The SQLite database (`data/dictionary.sqlite`) has the following schema:

```sql
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
);

CREATE INDEX idx_headword_norm ON dictionary_entries(headword_normalized);
CREATE INDEX idx_is_verified ON dictionary_entries(is_verified);
CREATE INDEX idx_page_number ON dictionary_entries(page_number);
```

---

## 5. Verification & Test Coverage

### 5.1 Test Execution Results
Running `.venv\Scripts\python.exe -m pytest backend/tests/ -v`:
- **Total Tests:** **78 passed in 6.99s**
- **Existing Tests:** 54 passed (0 regressions)
- **New Tests:** 24 passed:
  - `backend/tests/test_dictionary.py`: 12 tests covering `NullDictionaryService`, missing databases, unverified/verified lookups, stop words, reverse lookups, formatting, and DB auto-discovery.
  - `backend/tests/test_nko_mapping.py`: 10 tests covering PUA detection, Unicode N'Ko range validation, Arabic-Indic digit conversions, and token conversion.
  - `backend/tests/test_dictionary_integration.py`: 2 tests verifying `TranslationService` prompt injection and `dictionary_used` response flag.

### 5.2 Frontend Build
Running `npm.cmd run build` from `frontend/`:
- Transformed 32 modules with 0 errors.
- Bundle sizes: `index.html` (0.78 kB), `index.css` (4.83 kB), `index.js` (148.72 kB).

---

## 6. How to Reproduce & Operate

### 6.1 Re-running the Extraction Pipeline
```powershell
# From the repository root:
.venv\Scripts\python.exe scripts/extract_dictionary.py

# Optional: test with limited pages
.venv\Scripts\python.exe scripts/extract_dictionary.py --start-page 22 --max-pages 10
```

### 6.2 Enabling the Dictionary in Backend
In `backend/.env`:
```env
DICTIONARY_ENABLED=true
DICTIONARY_DB_PATH=../data/dictionary.sqlite
```

---

## 7. Next Steps for Complete PUA Font Decoding

To unlock 100% verified Unicode N'Ko equivalents from the `raw_target` column:
1. **Acquire Font Binary:** Locate the legacy TrueType font file `N'ko2Manden-1saDofanen.ttf` or `N'ko2Manden.ttf` (used by Baba Mamadi Diané and Cairo University N'Ko Department circa 2014).
2. **Extract Glyph Names:** Use `fontTools` to inspect `cmap` and `post` tables:
   ```bash
   ttx -t cmap -t post N'ko2Manden.ttf
   ```
3. **Build Deterministic Mapping Table:** Map each glyph index (`0xF120..0xF1E1`) to its corresponding official Unicode N'Ko codepoint (`0x07C0..0x07FF`).
4. **Update Verified Field:** Run a migration updating `verified_nko` and setting `is_verified = 1` for all mapped entries.
