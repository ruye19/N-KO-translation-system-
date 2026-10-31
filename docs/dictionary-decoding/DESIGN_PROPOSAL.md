# Design proposal: decoded N'Ko layer and optional dictionary reference

Status: **proposal only. Nothing here is implemented or enabled.** It depends on the findings and corrections in `REPRODUCIBILITY_AUDIT.md`.

---

## Part A: decoding pipeline (offline, reversible)

### A.1 Principles

1. **Input is the PDF, not `raw_extraction.jsonl`.** Raw records are in visual order with marks before their base, and they carry no coordinates, so ordering cannot be repaired after the fact.
2. **Additive only.** Output goes to new files and new tables. `dictionary_entries`, `raw_target`, `verified_nko` and `is_verified` are never written.
3. **Lossless.** Every decoded string keeps the legacy code sequence it came from, so the decoding can be redone or reversed.
4. **Nothing is dropped.** Every input code ends up as decoded text, passthrough, or an explicit placeholder, plus an `unresolved_codes` list.
5. **Tiers stay separate.** STRONG and CANDIDATE mappings are applied in separate passes. Normal output uses STRONG only.
6. **Never "verified".** Machine output is `machine_decoded`. The `verified` state is reserved for human review recorded elsewhere.

### A.2 Stages

```
PDF ──► 1 extract ──► 2 order ──► 3 segment ──► 4 decode ──► 5 validate ──► 6 store
        glyphs+xy     logical      entries      tiered       invariants     new table
```

**1. Extract.** PyMuPDF `rawdict`, pages 22–498. For each legacy glyph keep (page, column, x, y, legacy code). Remove faux-bold shadow copies: the same code within 1.5 pt in both x and y. The front matter repeats each glyph about 0.9 pt away, not at the same position. Keep only legacy-font glyphs, selected by font name (Manden; Koufi in the front matter). `raw_target` is also contaminated by French text, running-header glyphs and other fonts. Collect French headword spans (ArialNarrow at the column's left margin) with their baselines, using the **same** coordinate system. Mixing `texttrace` and `dict` coordinates shifted every entry by one during the investigation.

**2. Order.** Group by baseline (±2.5 pt). Sort each line by x descending. At an equal pen position, the base sorts before its zero-advance mark. The mark set is read from the embedded font (`hmtx` advance = 0), not hard-coded.

**3. Segment.** Assign each N'Ko line to the nearest headword baseline in the same column at or above it. Keep the source: `page`, `column`, `headword_baseline_y`, `line_index`. Link to the existing `dictionary_entries` row by (page, normalised headword) where unambiguous. Otherwise leave the link empty and flag it; never guess.

**4. Decode.** Each step records what it changed:
   - a. Composite marks expand to two Unicode marks.
   - b. The spacer after legacy `78` (ߥ) is removed only when the next code is a letter, and each removal is recorded.
   - c. `( ) [ ]` are mirrored for logical order.
   - d. STRONG pass: map STRONG codes; passthrough codes stay as they are.
   - e. CANDIDATE codes are **not** mapped in normal output. They become a visible placeholder (`⟨XX⟩`, U+27E8/U+27E9) and the entry gets `has_candidate_codes = 1`.
   - f. Unknown codes (`46`, `4E`, anything new) become `⟨XX⟩` and go to `unresolved_codes`.
   - g. A separate `decoded_with_candidates` column applies CANDIDATE codes too, for reviewers only. The translator never reads it.
   - h. NFC-normalise. Emit **no** Private Use Area characters.

**5. Validate.** These are build-time assertions; the build fails if any breaks.
   - Every legacy code in the input is classified (mapped, passthrough, placeholder).
   - Re-encoding the decoded string with the inverse table reproduces the legacy sequence (round trip).
   - No output PUA code points.
   - Tone marks follow a vowel or ߒ in ≥ 98% of cases, and woloso letters follow a nasal in ≥ 90%. A drop signals an ordering regression.
   - The alphabet-entry ordinals still compute correctly.

**6. Store.** New table in a **new** database file (e.g. `data/dictionary_decoded.sqlite`), so the existing DB is untouched:

```sql
CREATE TABLE decoded_entries (
  id                       INTEGER PRIMARY KEY,
  page_number              INTEGER NOT NULL,
  column_index             INTEGER NOT NULL,
  headword                 TEXT NOT NULL,
  headword_normalized      TEXT NOT NULL,
  dictionary_entry_id      INTEGER,            -- link to dictionary_entries.id when unambiguous, else NULL
  legacy_codes             TEXT NOT NULL,      -- JSON array, logical order, pre-decoding
  decoded_nko              TEXT NOT NULL,      -- STRONG tier only; candidates as placeholders
  decoded_with_candidates  TEXT,               -- reviewer-only
  weakest_tier             TEXT NOT NULL CHECK (weakest_tier IN ('STRONG','CANDIDATE','UNRESOLVED')),
  has_candidate_codes      INTEGER NOT NULL,
  unresolved_codes         TEXT NOT NULL,      -- JSON array
  transformations          TEXT NOT NULL,      -- JSON: spacer removals, mirrors, composite expansions
  status                   TEXT NOT NULL DEFAULT 'machine_decoded'
                           CHECK (status IN ('machine_decoded','human_reviewed_ok','human_reviewed_wrong')),
  decoder_version          TEXT NOT NULL,
  mapping_sha256           TEXT NOT NULL,      -- hash of the mapping table used
  source_pdf_sha256        TEXT NOT NULL
);
CREATE INDEX idx_decoded_headword ON decoded_entries(headword_normalized);
```

The decoder never writes `human_reviewed_*`. Only a separate review-import tool can set those statuses, and it must record the reviewer and date.

### A.3 Mapping as data, not code

Move the mapping into a versioned data file, e.g. `docs/dictionary-decoding/mapping_tiers.json` (corrected per the audit). The decoder records its SHA-256 in every row. Changing a tier then means changing a reviewed data file, never editing decoder logic.

---

## Part B: optional translator integration (designed, NOT activated)

### B.1 Switches, all off by default

| Setting | Default | Meaning |
|---|---|---|
| `DICTIONARY_ENABLED` | `false` | existing switch, unchanged |
| `DICTIONARY_DECODED_REFERENCE_ENABLED` | `false` | new; also requires `DICTIONARY_ENABLED=true` |
| `DICTIONARY_DECODED_DB_PATH` | unset | path to `dictionary_decoded.sqlite`; missing file means the feature stays off |

With either flag off, behaviour is byte-for-byte what it is today. Existing tests must keep passing unchanged.

### B.2 What may reach the model

- Only rows with `weakest_tier = 'STRONG'`, `has_candidate_codes = 0`, empty `unresolved_codes`, and `status` other than `human_reviewed_wrong`.
- Only the `decoded_nko` column. Never `decoded_with_candidates`, never `legacy_codes`.
- Strings are checked again at query time: N'Ko block plus allowed punctuation only, and no `⟨` placeholder.

### B.3 Prompt framing

Each line is explicitly labelled and never presented as authoritative:

```
- {headword} ({pos}) ≈ {decoded_nko} [machine-decoded, unverified N'Ko reference, p.{page}]
```

The preamble in `build_user_prompt` gains a sentence such as: "Lines marked *machine-decoded, unverified* were decoded automatically from a legacy font. They are usually but not always correct; use them as hints, not as the answer." The existing wording for "undecoded" entries stays as it is.

### B.4 Response metadata

- `dictionary_nko_verified` stays tied to **human-verified** N'Ko only. It must **not** become true because of machine-decoded references.
- Add `dictionary_machine_decoded_supplied: bool` (default `false`) so callers can tell the two apart.
- `human_verified` stays `false`.

### B.5 Guarantees and tests (for the implementation phase)

- Flags off: prompts and responses are identical to today's (snapshot test).
- Candidate or unresolved rows are never emitted (test with a fixture DB containing all three tiers).
- A `human_reviewed_wrong` row is never emitted.
- `dictionary_nko_verified` stays `false` when only machine-decoded rows are used.
- The existing PUA output guard is unchanged.

---

## Files a later implementation would touch

| File | Change |
|---|---|
| `scripts/decode_dictionary.py` | **new**: Part A pipeline |
| `docs/dictionary-decoding/mapping_tiers.json` | corrected, versioned mapping (see audit) |
| `data/dictionary_decoded.sqlite` | **new** generated output (git-ignored via `data/*`) |
| `backend/app/config.py` | add two settings, default off |
| `backend/app/services/dictionary.py` | new `DecodedReferenceService` (or an optional join) and a new line format in `format_context` |
| `backend/app/services/prompt.py` | one extra preamble sentence, emitted only when such lines are present |
| `backend/app/services/translation.py` | set `dictionary_machine_decoded_supplied` |
| `backend/app/schemas.py` | new response field, default `false` |
| `backend/tests/test_decoded_reference.py` | **new**: §B.5 tests |
| `backend/tests/test_decode_pipeline.py` | **new**: ordering, round trip, tier separation on small synthetic inputs (no copyrighted text) |
| `.env.example`, `README.md`, `docs/DICTIONARY.md` | document the new switches |

Not touched: the PDF, `data/dictionary.sqlite`, `data/raw_extraction.jsonl`, `backend/app/services/nko_mapping.py` (its digit table and verification semantics stay as they are), and any current translator path.

---

## Implementation notes (Phase 1, 2026-10-30)

Part A is implemented in `scripts/decode_dictionary.py`. Deviations from this proposal:

- **No `decoded_with_candidates` column.** Candidate codes appear only as placeholders, so the database holds no guessed mappings at all.
- **`status` is constrained to `'machine_decoded'`** by a CHECK constraint. Future human review must live in a separate table, not in this column.
- **Reversibility uses a per-glyph alignment** (`[original codepoint, output]`) rather than an inverse table. The mapping is many-to-one (e.g. U+F142 and U+05D0 both give ߊ), so an inverse table cannot rebuild the original.
- **Segmentation uses per-page column margins,** not the audit's fixed margins (see `REPRODUCIBILITY_AUDIT.md` §5).
- **Glyphs in the misnamed Koufi font are included,** since a few body pages use it.
- **Placeholders show the full codepoint,** e.g. `⟨U+F148⟩`.

Part B (translator integration) is **not** implemented.

### Decoder v1.1 (review fixes, 2026-10-30)

- **Margins:** each column's margin is the most common left edge within 5 pt of its leftmost edge. A stray span 2 pt left of the margin (p.117) no longer rejects a whole column of headwords.
- **Indented lines** are classified, in this order:
  1. *Wrapped headword.* The line above has no POS label and ends in "-", ",", a joining word ("ou", "de", "en"…), or a long mid-word break. The lines are joined using the raw trailing space and recorded as `wrapped_unconfirmed`, or `wrapped_confirmed` if the joined form exists in `dictionary.sqlite`.
  2. *Misaligned headword.* The line has its own POS label and no dash standing in for the headword. It is flagged `indented_headword`; see pp.146–147, where two blocks with different margins share a column.
  3. *Sub-entry.* Anything else becomes a `subentry` row with its own N'Ko window and a `parent_entry_ref`.
- **Column-top text:** `continued_from` / `continued_by` link it to the previous entry in reading order, with evidence `bracket_balance` or `reading_order`. Nothing is merged. Blank rows, and rows with non-italic French on the same baseline, are not linked.
- **Links:** `unique`, `senses` (one headword, senses 1..n), `paired_by_order` (repeated headword on both sides), `ambiguous`, `none`. Wrapped headwords fall back to linking via one of their lines (flag `linked_via_headword_line`).
- **Flags:** `caps_catchword`, `non_alphabetic_headword`, `no_nko`, `headword_not_in_source`, `indented_headword`, `linked_via_headword_line`.
- **`--pages` builds:** identical to the full build except for the cross-page continuation fields.
- **Reviewer sample:** `scripts/build_reviewer_sample.py` draws strata A–E with a fixed seed into the git-ignored `data/` directory.
