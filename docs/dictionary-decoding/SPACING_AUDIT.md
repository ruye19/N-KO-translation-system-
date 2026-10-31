# N'Ko spacing audit and decoder v1.2

Date: 2026-10-31. Scope: whitespace only. Character mappings (`mapping_tiers.v2.json`) are unchanged and treated as provisionally correct. Nothing here is human-verified, and every row remains `machine_decoded`.

This document contains no dictionary text. Examples are given by `entry_ref` and by structure. Before-and-after strings for those entries can be read locally from `data/dictionary_decoded.sqlite` and its backup.

## 1. How spacing worked in v1.1

- Spaces came only from space glyphs. These are U+F120, the legacy space (no outline, advance 341/2048 em, which is 2.5 pt at 15 pt), and rarely U+0020.
- Glyphs were placed in logical order using their origin x only. The widths were discarded, so the decoder could not see a gap that had no glyph in it.
- The one existing space rule was `wa_tail_spacer_removed`. ߥ (U+F178) is drawn with a tail, and the U+F120 that follows it is a spacer when a letter comes next.
- Every U+F120 at either end of a line was kept as a space.
- `backend/app/services/nko_mapping.py` has no space handling, and the decoder does not use it.

## 2. Method

The whole book was measured: 38,217 N'Ko lines. This is exactly the decoder's own line set, with the same faux-bold de-duplication.

- **Pen gaps.** For each pair of neighbouring glyphs, the gap from the end of one glyph's advance to the next glyph's origin.
- **Ink gaps.** The distance between the glyphs' actual outlines, using the `glyf` bounding boxes of the embedded `N'ko2Manden` font program. A pixel test on advance boxes proved unreliable, because outlines in this font overhang their advances. That test showed ink in 37% of slots that are known spaces.
- **Other fonts.** Whether any glyph from another font sits inside a gap. 32,128 of 32,191 gaps contain none.
- **Visual check.** Rendered line crops with gaps and spaces marked, sampled from every category.
- **Line structure.** Where space runs sit relative to the line and the column margin, and to the line's position within its entry.

The scripts were throw-away and run from the session scratchpad, read-only on the PDF.

## 3. Findings

### 3.1 Missing spaces: pen gaps with no glyph (corrected)

| Measurement | Value |
|---|---|
| Gaps of 0.3 pt or more with no space glyph on either side | 32,191 |
| …of which 2.4–2.6 pt, exactly one U+F120 advance | 31,823 |
| …of which 2.0–2.2 pt, one space at the 12 pt label size | 164 |
| Clear ink between the outlines, against U+F120 spaces | Same distribution: mostly 2.5–4.5 pt |

Where these gaps occur:
- About 27,000 surround the 12 pt red part-of-speech label (". ߕ", ". ߡ", ". ߞ").
- The rest are around the headword-placeholder dash "−", brackets, "/", "،", digits, and between N'Ko letters.

Why they are spaces:
- **Width:** the gap is exactly one space advance.
- **Nothing in the gap:** no glyph in any font.
- **Clear outlines:** the clearance between outlines matches that of real spaces.
- **Joining script:** N'Ko letters join, so a 2.5 pt break cannot occur inside a word.
- **Visual check:** rendered crops show a visible word space.

What v1.1 produced, using placeholders: `WORDߕ.WORD` and `WORDߡ.`, with the label fused to both neighbours, and `−WORD`.

### 3.2 Gaps that are not spaces (kept joined)

- **The ߥ tail (413 gaps).** The gap sits right after ߥ and before a letter. ߥ's outline starts 315/2048 em (about 2.3 pt) left of its origin, so its tail fills the slot. In every one of these 413 cases the outlines overlap, and on the rendered page the word is continuous. This is the same situation as `wa_tail_spacer_removed`, without the spacer glyph. One gap after ߥ (on p.494) is 5.05 pt wide: once the tail's slot is subtracted, one real space remains.
- **Too narrow (8 gaps, under 1.95 pt).** Left unchanged.
- **Too wide (51 gaps, over 5.5 pt and up to 93 pt).** Rendering shows a stray N'Ko fragment placed far from the line it belongs to, often inside the French column. A space there would be a guess about where the fragment belongs. Left unchanged, and the rows are flagged `wide_gap_not_spaced`.

### 3.3 Leading spaces: indentation (removed, recorded)

Leading spaces are U+F120 at the logical start of a line, which is the visual right edge.

- 1,506 such glyphs on 938 lines.
- 837 of 888 such lines are continuation lines, meaning the second or a later line of an entry.
- 805 of 938 end exactly at the column's N'Ko margin when their spaces are counted.

They set a hanging indent and never separate two words on the line.

### 3.4 Trailing spaces: layout residue (removed, recorded)

Trailing spaces are U+F120 at the logical end of a line, which is the visual left edge. There are 14,424 such glyphs.

- Nothing follows them on the line, so they cannot separate two words on it.
- They are not a reliable sign of where a line wrapped. They end 46% of first lines, but also 21% of single-line entries.

### 3.5 Spaces between wrapped lines (unchanged)

Lines of one entry stay joined by `\n`. Trailing spaces cannot tell whether a line ended at a word boundary (see 3.4), so the decoder neither adds nor removes anything across a line break.

### 3.6 Spaces inside words (unchanged)

- **121 spaces the print hides.** In these cases a U+F120 exists, but the next glyph is placed on top of it, so the print shows no space. The rendered sample of these sat at the edge of the part-of-speech label, not inside N'Ko words. 108 of the 121 are on pp.22–24 and p.253. Kept: the text did contain a space.
- **3,458 ߥ spacers** are already handled by the existing `wa_tail_spacer_removed` rule.
- **Ordinary spaces inside a word.** No geometric test can tell an extra word-internal space from a real word space. Finding them would need a lexicon or a human reader.

### 3.7 Missing spaces where the print itself has none (unchanged)

- About 250 label boundaries, where the 12 pt label touches a 15 pt word in the print.
- Word boundaries with no gap of any kind.

Adding spaces here would be inference, not measurement.

## 4. Decoder v1.2 changes (`scripts/decode_dictionary.py`)

### Extraction and measurement

- Extraction keeps each glyph's advance width and font size.
- `positioned_gaps()` measures the gaps on each line. The results travel with the line as `NkoLine.gaps`, which still unpacks as `(y, codes, extent)`.

### Decisions in `decode_line()`

Each decision is recorded in `transformations` with the measured `gap_pt`.

| Rule | When it applies | What it does |
|---|---|---|
| `positioned_space_inserted` | 1.95–5.5 pt gap | Inserts one space, or two if the gap is at least 1.5 space advances wide (75 such gaps). |
| `wa_tail_gap_not_a_space` | ߥ, then a letter | Subtracts the tail's slot first. |
| `narrow_gap_not_spaced`, `wide_gap_not_spaced` | Gap outside 1.95–5.5 pt | Records the gap; no change. |
| `leading_layout_space_removed`, `trailing_layout_space_removed` | Space glyphs at a line edge | Output becomes "". A line made only of spaces is kept as it is. |

### What stays reversible

- An inserted space is an alignment item `[null, " "]`, with no legacy code.
- A removed space keeps its code, with the output "".
- `legacy_codes`, glyph counts and the code inventory are unchanged.
- `rebuild_codes()` still returns the exact glyph sequence.

### Other changes

- The alphabet-ordinal check accepts "-nan" after a single space. The print sets it both ways: with a gap on q and e, solid on z and y.
- `assign_flags` adds `wide_gap_not_spaced`.
- The build summary now counts each spacing rule.

## 5. Result (full book, against the v1.1 backup)

| Item | Value |
|---|---|
| Entries | 32,865, with the same references |
| Entries whose `decoded_nko` changed | 23,784 |
| Spaces inserted | 31,791 (31,710 gaps) |
| Spaces removed | 15,930 (1,506 leading, 14,424 trailing) |
| Net characters | +15,861, all U+0020 |
| Non-space characters changed | 0 entries |
| Line structure, French headwords, legacy codes, inventory | Unchanged |
| Columns that differ | `decoded_nko`, `alignment`, `transformations`, `decoder_version`, and `flags` (51 rows) |
| Lines starting or ending with a space | 10,539 → 0, apart from lines made only of spaces |
| Tiers, entry counts, tone marks on vowels (99.97%), alphabet ordinals (18 of 18) | Unchanged |
| Content hash | `2785aa87…`, identical on two full builds |

The v1.1 database is preserved at `data/backups/dictionary_decoded.v1.1.0.sqlite` (SHA-256 `da69aead…`). The reviewer sample `data/reviewer_sample.v2.tsv` was drawn from v1.1. 261 of its 345 rows now read differently in spacing only. Build its review kit with `--db data/backups/dictionary_decoded.v1.1.0.sqlite`.

## 6. Unresolved

1. **51 wide gaps (stray fragments).** Which entry or word each fragment belongs to is unknown.
2. **About 250 label boundaries and 121 overlapped spaces.** The print sets the label touching a word. The spacing is left as the glyphs give it.
3. **Word boundaries across line breaks.** No reliable evidence either way.
4. **Spaces inside words, and missing spaces with no gap.** These cannot be seen in the geometry, and need a lexicon or a reader.
5. **75 double-width gaps** become two spaces, as printed, alongside 70 printed double U+F120. Collapsing them would be normalisation, not correction.
6. **Ordinal "-nan" after a gap (q, e).** Kept as printed. Whether the orthography wants it attached is a linguistic question.
