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
- **Verified Unicode N'Ko Entries:** **0.** No entry in the database carries usable N'Ko. See §7.
- **Test Suite Status:** see §7 for the audited figure. (The original claim of "78 passing" counted one test that was silently *skipped*, not passed.)

> **Status after independent audit (2026-10-24):** the extraction counts in this
> section were verified and are accurate. Several claims elsewhere in this
> report were not, and have been corrected in place; §7 records what changed.

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
- **Reference Context:** When dictionary retrieval is enabled, the prompt receives the
  French headword, its grammatical tag and its page number. These three facts are
  reliable. The N'Ko itself is withheld and the entry is explicitly labelled
  `N'Ko script undecoded - do not treat as N'Ko`.

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
- `MappingStatus` enum (`VERIFIED`, `PASSTHROUGH`, `UNVERIFIED_PUA`, `UNKNOWN`).
- **Recovers** Arabic-Indic digits (`U+0660`..`U+0669`), which the legacy font uses to
  carry N'Ko digit glyphs, to official Unicode N'Ko digits (`U+07C0`..`U+07C9`).
  This is the only recovered mapping, and it is backed by glyph-shape evidence
  (reproduce with `python scripts/verify_glyph_mappings.py`).
- **Passes through** punctuation unchanged. It does **not** rewrite `U+060C` to
  `U+07F8`: shape comparison shows the PDF glyph is an Arabic comma (IoU 0.582)
  and not the N'Ko comma (0.261), so rewriting it would substitute a different
  character. See §7.
- Provides `is_pua(codepoint)`, `is_unicode_nko(codepoint)`, and `convert_nko_token(text)`.

### 3.3 Searchable Dictionary Service (`backend/app/services/dictionary.py`)
- `DictionaryService` interface and `DictionaryEntry` dataclass.
- `SQLiteDictionaryService`:
  - Tokenizes input text, strips accents/punctuation, filters common French stop words.
  - Searches `dictionary_entries` by `headword_normalized`.
  - Disallows reverse N'Ko->French lookup unless `is_verified == 1`.
  - Formats retrieved entries with clear provenance and an explicit warning
    (`- bonjour [n.m., dictionary ref p.67, N'Ko script undecoded - do not treat as N'Ko]`).
  - Collapses multiple senses of one headword into a single reference line, since
    withholding the N'Ko would otherwise render them identically.
- Auto-discovery mechanism (`find_dictionary_db`) locating `data/dictionary.sqlite` in standard workspace locations.

### 3.4 Translation Orchestration (`backend/app/services/translation.py`)
- Integrates dictionary retrieval into the `translate()` workflow.
- Injects formatted dictionary context into translation prompts when available.
- Sets `dictionary_used: true` when reference context was added to the prompt. This means
  **a French headword matched**, not that a usable N'Ko translation was supplied.
- Also reports `dictionary_entries_found` (count) and `dictionary_nko_verified`
  (always `false` today), so the two cannot be confused.

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
    raw_target TEXT,
    verified_nko TEXT,
    is_verified INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL,
    page_number INTEGER NOT NULL
);

CREATE INDEX idx_headword ON dictionary_entries(headword_normalized);
CREATE INDEX idx_is_verified ON dictionary_entries(is_verified);
CREATE INDEX idx_page ON dictionary_entries(page_number);
```

---

## 5. Verification & Test Coverage

### 5.1 Test Execution Results
Running `.venv\Scripts\python.exe -m pytest backend/tests/ -v`:
- **Audited result (2026-10-24):** **108 passed, 0 skipped, 0 failed.**
- The earlier "78 passed" figure was **77 passed + 1 silently skipped**. The skipped
  test was the only one exercising the real database; it used a path relative to the
  working directory, so it never ran under `pytest` from `backend/`. Fixed.
- Test files:
  - `backend/tests/test_dictionary.py`: 12 tests covering `NullDictionaryService`, missing databases, unverified/verified lookups, stop words, reverse lookups, formatting, and DB auto-discovery.
- `backend/tests/test_dictionary_database.py`: 20 integrity tests run against the real
  `data/dictionary.sqlite` (schema, counts, page coverage, the zero-verified invariant,
  raw-text preservation, and the guarantee that no PUA reaches the prompt).
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

---

## 7. Independent Audit (2026-10-24)

This section records an independent review of the work described above. Claims
were checked against the database, the code and the PDF rather than taken from
the original completion report.

### 7.1 Verified as accurate

| Claim | Measured | Verdict |
|---|---|---|
| 32,057 entries | 32,057 | correct |
| 29,526 distinct headwords | 29,526 (normalised); 29,633 raw | correct |
| 477 pages, 22–498 | 477 distinct, min 22, max 498 | correct |
| 0 verified N'Ko entries | `is_verified=1` → 0; non-empty `verified_nko` → 0 | correct |
| Raw text preserved | 32,057 JSONL rows; 21 empty `raw_target` (0.07%) | correct |
| Extraction reproducible | Re-ran pages 22–41: 1,353 entries, rows identical | correct |
| No PUA reaches the model | Confirmed on real lookups | correct |

### 7.2 Corrected

1. **Unjustified "verified" punctuation mapping.** `U+060C → U+07F8` was listed
   as a VERIFIED mapping. Glyph evidence refutes it: the PDF glyph scores 0.582
   against the Arabic comma and 0.261 against the N'Ko comma. `U+061B` and
   `U+061F` were likewise asserted without evidence. All three are now
   passthrough, and a new `MappingStatus.PASSTHROUGH` separates *keeping a
   character* from *recovering N'Ko*.

2. **Punctuation could fabricate a "verified" entry.** Because `U+07F8` lies in
   the N'Ko block, `convert_nko_token("،")` returned
   `is_verified=True` with converted text `߸` — a verified N'Ko "translation"
   conjured from a comma. `"، abc"` likewise passed as verified N'Ko
   containing Latin text. Verification now additionally requires at least one
   character that is genuinely N'Ko (native block or recovered digit).

3. **Silent deletion of invalid output.** `translation.py` stripped Private Use
   Area characters from model output and returned the remainder as a success.
   Deleting characters changes meaning while still looking correct. The response
   is now rejected with `invalid_output_encoding` (HTTP 502).

4. **A test that never ran.** `test_real_database_lookups_if_present` resolved
   `data/dictionary.sqlite` relative to the working directory and was skipped
   under `pytest` from `backend/`. It now resolves from the repository root, and
   20 further integrity tests were added.

5. **Misleading `dictionary_used`.** It was `true` whenever any entry matched,
   which reads as "the dictionary supplied a translation". It still means
   "reference context was added" (API compatible), but the response now also
   carries `dictionary_entries_found` and `dictionary_nko_verified`.

6. **Identical duplicate context lines.** Five senses of *eau* produced five
   identical prompt lines once the N'Ko was withheld. Senses now collapse into
   one line with a count.

7. **Extraction not reproducible as shipped.** `pypdf` is required by
   `scripts/extract_dictionary.py` but appeared in no requirements file. Added
   as `scripts/requirements-extraction.txt`.

8. **Stale figures and schema.** The documented schema did not match the real
   one (nullability, index names), and "78 tests passing" was 77 passed plus one
   skipped.

### 7.3 Confirmed as genuine recovery

The digit mapping is **correct and evidence-backed**. Rendering the legacy
glyphs and comparing them by shape against Ebrima shows all ten favour the N'Ko
digit decisively and unanimously:

| legacy | vs U+07Cx (N'Ko) | vs U+066x (Arabic-Indic) |
|---|---|---|
| U+0660 | 0.602 | 0.198 |
| U+0661 | 0.591 | 0.126 |
| U+0662 | 0.526 | 0.195 |
| U+0663 | 0.653 | 0.183 |
| U+0664 | 0.636 | 0.211 |
| U+0665 | 0.775 | 0.124 |
| U+0666 | 0.606 | 0.129 |
| U+0667 | 0.774 | 0.279 |
| U+0668 | 0.695 | 0.227 |
| U+0669 | 0.784 | 0.230 |

Reproduce with `python scripts/verify_glyph_mappings.py`.

### 7.4 Still blocked

The N'Ko **letters** — the actual vocabulary — remain undecoded. All 32,057
entries hold only Private Use Area glyphs for their N'Ko side. Recovering them
needs one of:

- the original `N'ko2 Manden` font file or its keyboard/encoding chart
  (**the direct unblock**; makes conversion deterministic and checkable), or
- a parallel French–N'Ko word list in real Unicode to align against, or
- review by a literate N'Ko speaker working from the printed pages.

Glyph-shape matching alone is **not** sufficient: an earlier attempt over all 90
PUA codepoints produced 0 verified and only 5 plausible mappings, because the
legacy font stores positional variants and combining marks that do not
correspond one-to-one with isolated Unicode forms.
