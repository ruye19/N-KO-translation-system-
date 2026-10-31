# Reproducibility audit of the decoding report

Date: 2026-10-30. Tool: `scripts/audit_dictionary_decoding.py`, written from scratch for this audit. It does not reuse the investigation's analysis code. It reads only the source PDF (SHA-256 `871628d9…6be574b`), the saved `mapping_tiers.json`, and `data/raw_extraction.jsonl` (read-only). It writes nothing into the repository.

```
py -3.14 scripts/audit_dictionary_decoding.py --json-out <somewhere outside the repo>/audit.json
```

Letter sound values come from **Unicode character names** (`unicodedata`), not from the report.

## 1. Results

| Claim in report | Re-check | Result |
|---|---|---|
| 101 codes, 94 STRONG / 7 CANDIDATE | table read; every non-passthrough code in the body font inventoried | **Reproduced.** All 101 occur in the dictionary body; no code is missing from the table and none is extra. See wording correction C1. |
| Zero-advance glyphs are marks | read from the embedded font's `hmtx` | **Reproduced.** 22 mark codes, matching the table's mark set. |
| Duplicate outlines (42=05D0, 6B=6C, 6F=70, A9=AA, AB=AC, BC=BD, C0=C1, C4=D2, C5=D3, C7=D5, C9=D7, CA=D8, CB=D9) | contour-set equality | **Reproduced** (13/13). `C6`≠`D4` at point level, as the report said. |
| Composite marks = union of two marks | contour-set equality | **Reproduced** (6/6). |
| A mark shares its base's pen position | x-origin comparison | **Reproduced**: 121,170 / 121,181 marks. |
| Marks fall on vowels (98.7–100%) | geometric order, base before mark | **Reproduced: 99.97%** of 120,189 marks. With naive reversal: **0.92%**. |
| Woloso after nasal 94.3% / 97.6% (vs 4.7% / 12.7%) | recomputed | **Reproduced**: ߠ 94.1% vs ߟ 6.0%; ߧ 97.8% vs ߦ 12.1%. |
| Alphabet ordinals all correct | digits after each single-letter headword vs. alphabet position | **Reproduced: 14/14** genuine ordinals (g, h, i, m, n, o, s, t, u, v, w, x, y, z). The 15th match is "v1, v2" sub-sense numbering, not an ordinal. a–f carry no ordinal on their first line. |
| Alphabet letter values match by sound | Unicode-name value vs French letter | **Reproduced** for a, f, g, h, i, j, k, l, m, n, o, s, u, v, w, x, y, z. **`t` shows ߛ** (the source anomaly the report described; its ordinal 20 is correct). |
| Front matter matches French text in the PDF | decoded skeletons searched for | **Reproduced.** Exact: KANJAMADI, N'KO, BABA, MAMADI, 2014. Under stated normalisations: DIANE→*jane* (di+V = j), Bate (e/ɛ), Nafadjika→*nfajika* (dj = j, elision), Guine→*jine*. |
| 99.13% of entries strong-only | recomputed on the geometric corpus | **Reproduced: 21,439 / 21,627 (99.13%)**; glyphs: 82.99% strong, 16.96% passthrough, 0.05% candidate. |

## 2. Corrections to the report

| # | Report says | Correct statement |
|---|---|---|
| C1 | "94 of the 101 legacy codes that occur" | The 101 are **91** legacy font codes (including `U+05D0` and `U+05DE`) **plus 10** Arabic-Indic digit codepoints. Codes `46` and `4E` occur only in the Koufi front matter and are outside the table. |
| C2 | §4.2 candidate occurrence counts (48: 34, 5F: 86, 77: ~109) | Those count the geometric entry corpus. The full dictionary body has **48: 51, 5F: 100, 77: 141, 57: 2, 56: 1, 66: 1, 59: 1**. |
| C3 | §4.4: U+061B / U+061F are "genuine Arabic punctuation; earlier shape test agrees" | **Overstated.** `backend/app/services/nko_mapping.py` records that only U+060C matched cleanly, and that U+061B's ToUnicode value is not trustworthy. Treat 061B/061F as unverified passthrough. |
| C4 | §6 rule 3: overprint = "same code at the same position" | It is a **shadow copy about 0.9 pt away**. Dedup needs the same code within about 1.5 pt. |
| C5 | Coverage implied for "the dictionary" | 99.13% applies to the **geometric re-extraction only**. Applied to existing `raw_extraction.jsonl` records: 92.48% strong, 1.42% candidate, **6.10% contain foreign characters** (French letters/digits, running-header glyphs, Arabic presentation forms, Ebrima digits) that leaked into `raw_target`. One more reason not to decode from it. |

## 3. Tone marks and character ordering (confirmed)

1. Text is stored in **visual left-to-right** order. Sort each line by x **descending**.
2. A zero-advance mark sits at the **same pen position** as its base. At equal x the base sorts **first** and the mark after (99.97% vowel attachment, vs 0.92% if this rule is skipped).
3. N'Ko digits come out most-significant-first after reversal (߁߃ = 13; ordinals confirm).
4. Composite marks expand to two Unicode marks: e.g. `CC` → U+07EC U+07F2.
5. `( ) [ ]` must be mirrored. The spacer after `78` is removed when a letter follows (2,530 of 2,808 occurrences in the investigation's count).

## 4. Not independently reproduced from saved evidence

| Item | Why | What would close it |
|---|---|---|
| Glyph-shape IoU scores | Not re-implemented in this audit. Noto Sans NKo is only at a machine-specific path (Tor Browser) | Re-implement against pinned reference fonts |
| Basmala, Caire→*Kaahìrà*, Égypte→*Misìràn* | Needs knowledge of Manding/Arabic names | Human N'Ko reader |
| ~30 vocabulary cribs (mère→ߓߊ, sel→ߞߐ߱ …) | Expected forms come from the investigator's Manding knowledge | Human reader, or lookup in a Unicode N'Ko corpus |
| Apostrophe assignment (`5A`→ߴ high, `BB`→ߵ low) | The tone-of-elided-vowel argument is linguistic; only shape is mechanical | Human reader |
| `reviewer_sample.tsv` selection | Drawn with seed 7 from `corpus.json`, which is deliberately not preserved | Regenerate from the future pipeline; the sample stays valid as a review set |
| Linguistic correctness of any decoded entry | Never claimed | Human spot-check (report §8) |

The mechanical claims (structure, ordering, orthographic statistics, alphabet arithmetic, front-matter matches, coverage) reproduce from the PDF plus the saved table. The linguistic claims do not, and they must stay labelled as such.

## 5. Addendum: implementation phase (2026-10-30)

Building `scripts/decode_dictionary.py` exposed a flaw that the investigation and this audit shared, because both used the same segmentation heuristic.

- **Headword margins vary by page** (x = 105–108 / 307–310). The fixed set {106, 107, 308, 309, 310} missed whole columns on pages laid out at 105/307 or 108/310.
- **The body starts at baseline 82** on early pages, so the header cutoff at 85 dropped those pages' first entries.
- As a result, the 99.13% (21,439 / 21,627) was measured on only **21,689 headwords**. A further **196,305 N'Ko glyphs (30%)** were never attached to any headword.

The decoder now detects each column's margin per page and puts the header line at 78 (only 37 blank glyphs sit above it). Results:

| | audit heuristic | decoder (`page_margins`) |
|---|---|---|
| headword entries | 21,689 | **31,627** |
| entries with N'Ko | 21,627 | **31,529** |
| strong-only entries | 21,439 (99.13%) | **31,278 (99.20%)** |
| candidate entries | 188 | 249 |
| unresolved entries | 0 | **2** ('Km', 'km2', p.252: U+F146) |
| N'Ko glyphs not attached to a headword | 196,305 | 4,017 (kept as `orphan_lines` rows) |
| alphabet ordinals found / correct | 14 / 14 | 18 / 18 |

The audited 99.13% still reproduces exactly when the same pages are re-segmented with the audit heuristic. Every build records this in `decode_metadata.audit_v1_regression`.

Also corrected: U+F146 is **not** front-matter-only. Both occurrences are in the dictionary body (p.252, Koufi font); U+F14E is the front-matter one (p.17). See `mapping_tiers.v2.json`.
