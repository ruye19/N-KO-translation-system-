# N'Ko Dictionary Encoding — Independent Decoding Investigation

Date: 2026-10-30 · Scope: investigation and reporting only. Nothing in the repository was modified.

## 1. Bottom line

The legacy `N'ko2Manden` encoding can be decoded from evidence inside the PDF itself, without Mansa.

- **94 of the 101 legacy codes that occur have strong, multi-source evidence. 7 are candidates.**
- **99.13% of dictionary entries (21,439 / 21,627) decode using only strong-tier codes.** Candidate codes account for 232 glyph occurrences (0.05%).
- The strongest single piece of evidence is the dictionary's own alphabet entries. Each French letter is glossed with its N'Ko letter and its ordinal position. All 14 ordinals that are present are arithmetically correct (g=7 … z=26), and every letter matches by sound.
- **Nothing is marked VERIFIED.** "Strong" means several independent lines of evidence agree. It does not mean a qualified N'Ko reader has confirmed it. A light human spot-check (see §8) is still recommended before any N'Ko is shown as verified.

Correction to the earlier report (`docs/DICTIONARY_ENCODING_INVESTIGATION.md`): it said the encoding was "not recoverable without the original font/chart". That conclusion was reasonable given the glyph-matching-only approach, but it no longer holds. Crib-based and orthographic evidence closes the gap.

## 2. What has been established (measured facts)

| # | Fact | How |
|---|---|---|
| F1 | The PDF carries **three** N'Ko fonts by the same author. `N'ko2Manden-1saDofanen` is the body font. `MonotypeKoufi-Bold` and `SimplifiedArabicBackslantedBoldItalic` are **misnamed**: their `name` tables read "Baba Diane la baara le…" and "Baba wla Mamadi Diane la baara le." | fontTools `name` table |
| F2 | Koufi shares Manden's code→glyph-slot layout exactly, with identical bboxes. It is a revision of the same design, **not** an independent witness. | GID/ToUnicode comparison, outline diff |
| F3 | Backslan (running page headers only, ~480×) uses a **different** encoding. It is not needed for the dictionary body. | codepoint census |
| F4 | Text is stored in **visual left-to-right order**. Logical N'Ko (RTL) is the reverse of each line. | x-coordinates increase along every span |
| F5 | Zero-advance glyphs (`C4–CD`, `D0–D5`, `D7–DB`, `59`) are combining marks. In the visual stream a mark **precedes** its base, so after reversal it follows the base, as Unicode requires. | `hmtx` advance = 0, bbox geometry |
| F6 | The font encodes **positional variants as separate codes**. Glyphs without a left joining stroke sit at the visual left end (= word end) of words 85–97% of the time. | bbox join test × word position, corpus-wide |
| F7 | Exact duplicate outlines: `42≡U+05D0`, `6B≡6C`, `6F≡70`, `A9≡AA`, `AB≡AC`, `BC≡BD`, `C0≡C1`, and the mark set `D2–D9 ≡ C4–CB` (`D4`/`C6` match by bbox). | point-level outline comparison |
| F8 | The six composite marks are **exactly** the union of two simple marks (e.g. `CC = C4 + C9`). | contour-set equality |
| F9 | The existing `data/raw_extraction.jsonl` keeps visual order, with marks *before* their base (85.7% of marks are followed by a vowel, 0.1% preceded by one). **It cannot be decoded by a lookup table as-is.** It must be re-extracted from page geometry. | statistic over all 32,057 records |

## 3. Lines of evidence used

Each mapping was scored on how many of these independent sources agree.

1. **Shape (A)**: glyph-outline IoU against **two** reference fonts, Ebrima and Noto Sans NKo. My own rasteriser keeps the baseline, and the letter scorer ignores the joining band. Final/isolated forms match strongly (typically 0.65–0.86 with clear margins). Medial forms are weaker and were never relied on alone.
2. **Structure (B)**: advance widths, mark position (above/below), outline identity, composite decomposition.
3. **Orthographic statistics (C)**, independent of shape:
   - Tone and nasal marks fall on candidate vowels **98.7–100%** of the time (≈80k marks).
   - The dot-above (U+07ED) also lands on ߜ/ߖ/ߝ. That is the documented N'Ko way of writing /g/, /z/, /v/.
   - The woloso letters follow a nasal **94.3%** (ߠ) and **97.6%** (ߧ) of the time, against 4.7% / 12.7% for plain ߟ / ߦ, exactly as N'Ko spelling rules require.
4. **Cribs (D)**: decoded text compared with things known independently.
   - **Alphabet entries**: 20 single-letter headwords. Template: *[letter] ߕ. ߝߊ߬ߙߊ߲߬ߛߌ߬ߞߊ߲ ߛߓߍߘߋ߲߫ [N]ߣߊ߲* ("letter N of the French alphabet"). Ordinals 7, 8, 9, 13, 14, 15, 19, 20, 21, 22, 23, 24, 25, 26 are all correct. Letter values: x→ߌߞߛ, v→ߝ߭, z→ߖ߭, w→ߥ, y→ߦ, h→ߤ, j→ߖ, f→ߝ, n→ߣ, m→ߡ, l→ߟ, k→ߞ, i→ߌ, u→ߎ, o→ߏ, s→ߛ, a→ߊ.
   - **Front matter, cross-checked against non-N'Ko text in the same PDF**:

     | Decoded N'Ko | Independent source |
     |---|---|
     | ߓߊ߬ߓߊ߫ ߡߊ߬ߡߊߘߌ߫ ߖߊ߭ߣߍ߫ | French title page: "BABA MAMADI DIANE" |
     | ߓߊߕߍ߫ ߒߝߊ߬ߖߌ߬ߞߊ ߖߌߣߍ߫ | font copyright: "Bate-Nafadjika, Guine" |
     | ߂߀߁߄ | French: "Edition 2014" |
     | ߞߊ߯ߤߌ߬ߙߊ߬ / ߡߌߛߌ߬ߙߊ߲߬ | French: "Caire - Egypte" |
     | ߞߊ߲߬ߖߊ߬ߡߊ߯ߘߌ߫ | French: "KANJAMADI" |
     | ߒߞߏ | "N'Ko" |
     | ߛߟߏ߬ߡߊ߯ߣߊ߫ | French preface: "Kánté Sòlòmànà" |
     | ߊߟߊ߫ ߡߊ߬ߤߌ߬ߣߟߊ߬ ߤߌߣߟߊ ߕߐ߮ ߟߊ߫ | the basmala, at the head of the N'Ko title page |

   - **Basic vocabulary**: about 30 headwords picked in advance all decode to the expected Manding word. mère→ߓߊ, nom→ߕߐ߮, femme→ߡߏ߬ߛߏ, homme→ߡߐ߱, deux/trois/un→ߝߌ߬ߟߊ߬/ߛߓߊ߬/ߞߋߟߋ߲߫, tête→ߞߎ߲߭, sel→ߞߐ߱, riz→ߡߊ߬ߟߏ, sang→ߖߋ߬ߟߌ, lait→ߣߐߣߐ, miel→ߟߌ, terre→ߘߎ߱, ciel→ߛߊ߲, soleil→ߕߋ߬ߟߋ, œil→ߢߊ, demain→ߛߌߣߌ߲߫, monde→ߘߎߢߊ߫, Guinée→ߖߌ߬ߣߍ, Sénégal→ߛߌ߬ߣߍ߬ߞߊ߯ߟߌ߫, Afrique→ߊߝߙߌߞߌ߬, Japon-related→ߣߌߔߐ߲߫, Europe→ߋߙߐߔߎ߬, menthe→ߣߊ߬ߣߊ߬ߦߋ, sucre→ߟߌߞߐ߮ ("honey-salt").
   - Caveat: the expected forms in this group come from general knowledge of Manding, not from a source in the repository. They corroborate the mapping but do not prove it. The front-matter and alphabet cribs above *are* independent of that knowledge.

## 4. Mapping table

`code` = U+F1xx − 0xF100 (or the literal codepoint). Medial/final variants are listed together. The full machine-readable table with per-code evidence is in `mapping_tiers.json`.

### 4.1 Strong evidence (A or B, plus C or D)

| Unicode | Legacy codes (joined → final) | Main evidence |
|---|---|---|
| ߊ U+07CA | `42`, `U+05D0` → `AB`, `AC` | shape 0.81 both refs; basmala; alphabet *a* |
| ߋ U+07CB | `7B` → `7C` | Noto 0.70; ߞߋߟߋ߲, ߕߋߟߋ, ߘߋ߲ |
| ߌ U+07CC | `49` → `4A` | shape 0.72 both; alphabet *i* |
| ߍ U+07CD | `A6` → `A7`, `A8` | shape 0.78/0.74, margin 0.4; ߖߊ߭ߣߍ, ߖߌߣߍ |
| ߎ U+07CE | `61` → `62` | shape 0.64/0.80; alphabet *u* |
| ߏ U+07CF | `63` → `64` | shape 0.65/0.67; alphabet *o*; ߒߞߏ |
| ߐ U+07D0 | `AE` → `AF`, `BA` | shape 0.70/0.72; ߕߐ߮, ߣߐߣߐ |
| ߑ U+07D1 | `C0`, `C1` | shape 0.54/0.52; Abdul, Baltika, bristol |
| ߒ U+07D2 | `58` | ߒߞߏ |
| ߓ U+07D3 | `69` | ߓߟߏ, Baba, ߓߊ |
| ߔ U+07D4 | `67` → `68` | final shape 0.74/0.86; ߣߌߔߐ߲ (Nippon), ߋߙߐߔߎ (Europe) |
| ߕ U+07D5 | `79` → `7A` | shape 0.69/0.72; ߕߐ߮, ߕߋߟߋ |
| ߖ U+07D6 | `4B` → `4C` | shape 0.78/0.74; Kanjamadi; alphabet *j*, *g*, *z* |
| ߗ U+07D7 | `6B`, `6C` → `6E` | final shape 0.77/0.86; ߗߍ |
| ߘ U+07D8 | `60` | Kanjamadi, Mamadi, ߘߎߢߊ |
| ߙ U+07D9 | `6F`, `70` → `71`, `72` | final shape 0.84; ߞߊ߯ߤߌߙߊ, ߡߌߛߌߙߊ |
| ߛ U+07DB | `A5` | alphabet *s*; ߛߓߍ |
| ߜ U+07DC | `A1`, `A2` → `A3`, `A4` | ▽ shape (Noto 0.71); sigma = ߜ߭ (g) |
| ߝ U+07DD | `7F` → `E1` | alphabet *f*, *v*; ߝߊ߬ߙߊ߲߬ߛߌ |
| ߞ U+07DE | `6A` | alphabet *k*; Kanjamadi, N'Ko |
| ߟ U+07DF | `A9`, `AA` | basmala; alphabet *l* |
| ߠ U+07E0 | `4D` | woloso rule 94.3% |
| ߡ U+07E1 | `52` → `54` | Δ shape 0.69/0.76; alphabet *m* |
| ߢ U+07E2 | `55` | ߘߎߢߊ, ߢߐ߲ |
| ߣ U+07E3 | `7D` → `U+05DE` | final shape 0.79/0.82; alphabet *n*; basmala |
| ߤ U+07E4 | `4F` → `51` | final shape 0.82/0.80; alphabet *h*; basmala |
| ߥ U+07E5 | `78` (initial, see §6) | alphabet *w*; "wa, wali = taa, taali"; ߥߎߦߊ |
| ߦ U+07E6 | `73`, `74` → `75` | alphabet *y*; ߦߙߌ |
| ߧ U+07E7 | `65` | woloso rule 97.6% |
| ◌߫ U+07EB | `C6`, `D4` | shape 0.78/0.67; 100% on vowels |
| ◌߬ U+07EC | `C4`, `D2` | shape 0.82/0.77; 98.7–100% on vowels |
| ◌߭ U+07ED | `C5`, `D3` | shape 0.90/0.66; v = ߝ߭, z = ߖ߭ |
| ◌߮ U+07EE | `CB`, `D9` | shape 0.69/0.61; ߕߐ߮ |
| ◌߯ U+07EF | `CA`, `D8` | shape 0.55/0.58 (thin margin; resolved by the one-to-one constraint); 100% on vowels |
| ◌߰ U+07F0 | `C7`, `D5` | shape 0.80/0.73 |
| ◌߱ U+07F1 | `C8` | shape 0.55/0.58 (thin margin); ߡߐ߱, ߞߐ߱ (canonical spellings) |
| ◌߲ U+07F2 | `C9`, `D7` | the only below-mark; shape 0.94/0.78 |
| composites | `CC CD D0 D1 DA DB` | exact contour union of two simple marks |
| ߴ U+07F4 | `5A` | shape 0.68/0.64 vs 0.33; elision after high-tone ߣߌ߫ |
| ߵ U+07F5 | `BB` | shape 0.76/0.69 vs 0.39; elision after low-tone ߞߊ߬ |
| ߸ U+07F8 | `BC`, `BD` | shape 0.57/0.59 vs 0.11; clause separator |
| ߀–߉ U+07C0–07C9 | `U+0660–0669` | earlier shape test plus correct alphabet ordinals |

### 4.2 Candidates (single line of evidence or too rare to confirm)

| Code | Candidate | Why only a candidate | Occurrences |
|---|---|---|---|
| `77` | ߥ (medial) | shape top in both refs but weak (0.51/0.42); pairs with `78` | ~109 |
| `48` | ߚ U+07DA | refs disagree; mostly ideophones | 34 |
| `5F` | ߺ U+07FA | shape 0.41/0.42 vs 0.29; used as elongation | 86 |
| `56`, `57` | ߢ or ߧ (final) | shape ambiguous between the two | ≤ 3 |
| `66` | ߧ (final) | shape 0.63/0.71, 1 occurrence | 1 |
| `59` | ◌߳ U+07F3 | shape 0.70/0.80, 1 occurrence, on a vowel | 1 |

### 4.3 Unresolved

- `46`, `4E`: present only in Koufi front-matter headings (≤ 2 occurrences). Not used in the dictionary body.

### 4.4 Punctuation (pass through; editorial choice, not decoding)

`U+060C ،`, `U+061B ؛`, `U+061F ؟` are genuine Arabic punctuation glyphs. The earlier shape test agrees, and N'Ko commonly uses them. `U+2212` is used as a hyphen. `. / : ( ) [ ] " = + !` are literal. In RTL logical order, **parentheses and brackets must be mirrored** (visual `)` = logical `(`).

## 5. What remains uncertain

1. **No human confirmation.** Every tier is evidence-based. None is VERIFIED.
2. The 7 candidate codes in §4.2.
3. The `78` + space rule (§6). In 2,530 of 2,808 occurrences the space after `78` is a spacer. A genuine word-final ߥ before a real space would be indistinguishable, though it is rare in Manding.
4. **Why duplicate codes exist** (`42` vs `U+05D0`, the C- vs D-series marks). The outlines are identical, so the decoded result is the same either way. Whatever the duplicates meant to the author (keyboard layer, spacing, or something else) is unknown and does not affect decoding.
5. **Source errors are not decoding errors.** Example: the *t* entry repeats ߛ from the *s* entry, while its ordinal (20) is correct. A decoder must not "fix" these.
6. **Entry segmentation.** My geometric headword→N'Ko alignment produces 21,689 entries, against 32,057 sense records in the existing extraction. Multi-line and multi-sense entries need careful handling in any implementation.
7. The Backslan running-header encoding is not decoded (not needed).

## 6. Decoding rules a safe implementation needs

1. Re-extract glyphs **with coordinates** from the PDF. Do not use `raw_target` (F9).
2. Per line: sort glyphs by x descending. At equal x, the base comes before its mark.
3. Deduplicate overprinted glyphs (faux-bold front matter: same code at the same position).
4. Map codes using the strong table. Keep candidate-tier codes flagged. Expand composite marks into two marks.
5. Drop the spacer after `78` when a letter follows.
6. Mirror `( ) [ ]`.
7. Normalise to NFC and keep the original legacy codes alongside, for traceability.
8. Treat `U+05D0`/`U+05DE` (Hebrew codepoints from the font's cmap) as N'Ko letters, not Hebrew.

## 7. Can a partially decoded dictionary be produced safely?

**Yes, as a separate, clearly labelled candidate layer.** It must not replace the existing data or be marked verified.

Recommended shape, not implemented:
- New output (e.g. a `decoded_candidate` column or table). `raw_target`, `verified_nko` and `is_verified = 0` stay untouched.
- Per entry: decoded Unicode, legacy codes, weakest evidence tier (`STRONG` / `CANDIDATE`), and decoder version.
- Entries containing candidate-tier codes (0.87%) stay excluded or flagged.

### What can safely be used in the translator

| Today, no change | After a human spot-check | Not yet |
|---|---|---|
| French headwords, POS, page numbers (already in use) | Strong-tier decoded N'Ko, offered to the model as **reference context labelled "machine-decoded, unverified"**, behind a flag that is off by default | Anything presented to users as *verified* N'Ko |
| N'Ko digits | | Candidate-tier entries |

Production behaviour should stay as it is until you decide.

## 8. Recovering the remaining certainty without Mansa

In order of value:

1. **Spot-check by any literate N'Ko reader.** This is now a much smaller task: read about 80 decoded entries (`reviewer_sample.tsv`) and mark right or wrong. That replaces judging 90 abstract glyphs. A clean sample of 80 bounds the per-entry error rate below roughly 4% at 95% confidence.
2. **Corpus validation.** Look up decoded words in an existing Unicode N'Ko corpus, for example the Maninka reference corpus (Vydrin et al.) or N'Ko Wikipedia. A high hit-rate for decoded word forms is quantitative evidence that needs no reader.
3. **The publisher.** The PDF lists `www.kanjamadi.com` / `kanjamadi.org` and `nko@kanjamadi.org`. They may have a Unicode edition, the original font, or its keyboard chart. That would settle the mapping definitively. Not contacted; that's your call.
4. **Targeted re-checks** for the 7 candidate codes: pull every occurrence (≤ 110 each) for a reader or for corpus lookup.

## 9. Files (scratchpad, not in the repo)

All in `C:\Users\ruthy\AppData\Local\Temp\claude\c--Users-ruthy-OneDrive-Desktop-N-KO-AI-translator\eea878c7-ff1a-4ae5-9956-086cbf6ca74b\scratchpad\inv\`:

- `mapping_tiers.json`: every code, its candidate Unicode, tier, and evidence
- `reviewer_sample.tsv`: 80 random decoded entries for spot-checking
- `metrics.json`, `letter_scores.json`, `marks_scores.json`: raw measurements
- `sheet_legacy_letters.png`, `sheet_reference_letters.png`: glyph sheets
- `corpus.json`: geometry-based entry corpus (contains copyrighted dictionary content; do not redistribute)
- scripts: `trace.py`, `metrics.py`, `positions.py`, `marks.py`, `letters.py`, `identity.py`, `decode.py`, `corpus2.py`, `tests.py`, `tiers.py`, `raster.py`

Run them with Python 3.14 (`py -3.14`), which has PyMuPDF, fontTools, Pillow and numpy. The repo `.venv` lacks these.

## 10. Repository state

Read-only. No repository file was created, modified, staged or deleted. The PDF, `dictionary.sqlite`, `raw_extraction.jsonl` and the verification worksheet are untouched. I did not run `scripts/verify_glyph_mappings.py`, because it writes into `data/glyph_evidence/`.
