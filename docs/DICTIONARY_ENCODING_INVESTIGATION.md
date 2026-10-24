# Dictionary Encoding Investigation

**Status: BLOCKED — no verified PUA → Unicode N'Ko mapping exists yet.**
**Consequence: dictionary retrieval is disabled in the application.**

Source file: `dictionnaire Fr_nko.pdf` (unchanged; treated as read-only).

This note records what was measured directly from the PDF. Anything not
demonstrated is marked **UNKNOWN** rather than guessed.

---

## 1. What the PDF actually is

| Property | Finding | How it was established |
|---|---|---|
| Pages | 498 | PDF page tree |
| PDF version | 1.6, objects inside compressed object streams | file header + `/ObjStm` parsing |
| Text | Selectable (not a scan) | text operators present; no full-page images |
| French text | Extracts correctly as Unicode | direct extraction |
| N'Ko text | Extracts as **Private Use Area** characters | `ToUnicode` CMaps (below) |

OCR is **not** required to read the French side. The problem is not image
quality — it is character encoding.

## 2. The font carrying the N'Ko

All N'Ko body text is set in an embedded subset of:

```
N'ko2Manden-1saDofanen
```

- Copyright string in the font's `name` table:
  `Baba Diane la baara le Bate-Nafadjika, Guine.`
- Three Type0 subsets appear in the PDF (`APNCJG+`, `CIMNIA+`, `EDODLD+`),
  all sharing one 24,852-byte font program.
- `Subtype /CIDFontType2`, `/Encoding /Identity-H`, `/CIDToGIDMap /Identity`
  → **glyph ID equals CID**.
- 172 glyphs, `unitsPerEm` 2048.
- `OS/2`: `usFirstCharIndex = 0xF100`, `usLastCharIndex = 0xF1E1`.

**Critical: the embedded subset has no `cmap` table and no `post` table.**
There are no glyph names and no character-to-glyph mapping inside the font.
The embedded font therefore carries *no* encoding information that could be
used to recover Unicode deterministically.

## 3. What the ToUnicode CMaps say

Extracted CMaps (`docs/evidence/tounicode-manden-subset.json`):

| Subset | CID mappings | of which PUA |
|---|---|---|
| `CIMNIA+N'ko2Manden-1saDofanen` | 101 | 77 |
| `EDODLD+N'ko2Manden-1saDofanen` | 117 | 90 |

The non-PUA mappings are ordinary characters the font also carries:

- ASCII punctuation: `U+0021 ! `, `U+0022 "`, `U+0028 (`, `U+0029 )`, `U+002E .`, `U+002F /`, `U+003A :`
- **Arabic-Indic digits** `U+0660`–`U+0669` (used for N'Ko digits)
- Arabic punctuation: `U+060C` (comma), `U+061B` (semicolon), `U+066A` (percent)

The N'Ko letters themselves all map into the Private Use Area, spanning
`U+F120`–`U+F1E1` — 194 code points wide, sparsely occupied, with 17–23 gaps.

**This is not a shifted copy of the Unicode N'Ko block.** The Unicode N'Ko
block is 64 code points (`U+07C0`–`U+07FF`); the PUA usage is ~90 distinct
values across a 194-wide span. The pattern `0xF100 + n`, with `n` ranging over
`0x20`–`0xE1`, is the signature of a **legacy 8-bit font codepage lifted into
the PUA**: the byte the author's N'Ko keyboard produced, offset by `0xF100`.

Recovering Unicode therefore requires knowing that legacy keyboard/codepage
layout. That layout is not in the PDF.

## 4. One genuine Unicode source inside the same PDF

The PDF also embeds subsets of **Ebrima**, a Microsoft font with real N'Ko
coverage. Those subsets carry correct Unicode:

| Subset | GIDs used | ToUnicode | Cross-check against `C:\Windows\Fonts\ebrima.ttf` |
|---|---|---|---|
| `CIMNJC+Ebrima` | 1104, 1109, 1121, 1122, 1124 | `U+07ED`, `U+07F2`, `U+07C0`, `U+07C1`, `U+07C3` | glyph names `uni07ED`, `uni07F2`, `uni07C0`, `uni07C1`, `uni07C3` — **exact match** |
| `EECHAL+Ebrima` | 1125, 1126 | `U+07C4`, `U+07C5` | `uni07C4`, `uni07C5` — **exact match** |

This is a useful verification anchor, but it covers only **seven characters**
and they are incidental, not the dictionary body text. It does not unlock the
`N'ko2Manden` encoding.

## 5. Glyph-matching experiment (and why it was not enough)

Since the font carries no encoding, the remaining option was to identify
glyphs **by shape** against known Unicode N'Ko fonts.

Reference fonts found locally (nothing was downloaded):

- `C:\Windows\Fonts\ebrima.ttf` — 63 characters in `U+07C0`–`U+07FF`
- `…\Tor Browser\Browser\fonts\NotoSansNKo-Regular.ttf` — 62 characters

Method:

1. Extracted the embedded font program; injected a synthetic `cmap` so each
   glyph could be addressed (GID = CID, per `/CIDToGIDMap /Identity`).
2. Rendered all 90 PUA glyphs (89 non-blank) via FreeType.
3. Normalised scale between fonts empirically (the Manden design renders ~1.61×
   smaller than Ebrima at equal ppem) and aligned on a common baseline origin.
4. Scored each PUA glyph against every reference character using
   intersection-over-union with a ±12px translation search, **independently
   against both reference fonts**.

Result:

| Tier | Count (of 90) |
|---|---|
| Both reference fonts agree, IoU ≥ 0.70, clear margin over runner-up | **5** |
| Both agree, but low score or no margin | 54 |
| The two reference fonts **disagree** on the best match | 30 |
| Blank glyph | 1 |

Even the top tier is only *suggestive*:

| CID | PUA | Candidate | Ebrima IoU | Noto IoU |
|---|---|---|---|---|
| 90 | `U+F16E` | `U+07D7` | 0.73 | 0.84 |
| 84 | `U+F168` | `U+07D4` | 0.70 | 0.80 |
| 61 | `U+F151` | `U+07E4` | 0.73 | 0.72 |
| 117 | `U+F1AB` | `U+07CA` | 0.73 | 0.72 |
| 118 | `U+F1AC` | `U+07CA` | 0.73 | 0.72 |

Note that CIDs 117 and 118 both resolve to the same candidate — which is
exactly the expected failure: **N'Ko is cursive**, so a legacy font stores
multiple positional variants (initial/medial/final/isolated) of one letter,
plus standalone combining tone marks. Those cannot be matched one-to-one
against isolated Unicode forms. Visual inspection of
`docs/evidence/pdf-font-glyphs.png` against `docs/evidence/unicode-nko-ebrima.png`
confirms many PUA slots are diacritics and positional variants.

**Classification of the 90 mappings: VERIFIED 0 · POSSIBLE 5 · UNKNOWN 85.**

Automated glyph matching alone cannot produce a trustworthy mapping table.

## 6. Search for the original font / encoding chart

| Location | Result |
|---|---|
| `C:\Windows\Fonts` | Only `ebrima.ttf` / `ebrimabd.ttf`. No N'ko2 Manden. |
| User profile & project folder | No `*nko*` / `*manden*` font file. |
| PDF embedded font metadata | Family `N'ko2Manden`, author credit only. No encoding table. |
| Documentation with the PDF | None supplied. |

The original full `N'ko2 Manden` font was **not found locally**, and no
encoding or keyboard chart accompanies the dictionary.

## 7. Which path is actually possible

- **A. Deterministic conversion from the original font/encoding — NOT POSSIBLE
  TODAY, but this is the real unlock.** It becomes possible the moment the
  original `N'ko2 Manden` font file or its keyboard/encoding chart is obtained.
  With the full font, the legacy byte → glyph → Unicode correspondence can be
  derived and verified exactly, instead of estimated. **Recommended next
  action: request the font or its layout chart from the publisher or the N'Ko
  community (the font is credited to Baba Diane, Nafadji, Guinea).**
- **B. Glyph matching — PARTIALLY POSSIBLE, insufficient on its own.** It can
  propose candidates (5 reached a reasonable bar out of 90), but it cannot
  confirm them, and it breaks down on positional variants and combining marks.
  It is usable only as input to human review by an N'Ko reader.
- **C. Targeted OCR — POSSIBLE BUT UNPROVEN.** Not attempted here (full OCR was
  explicitly out of scope). N'Ko OCR support in common engines is weak, and it
  would still require human verification. Worth a small trial only if A fails.
- **D. None yet** — accurate as a description of today's *verified* state: zero
  confirmed mappings.

**Chosen path: A, with B as supporting evidence and human confirmation.**

## 8. Effect on the application

The translator does not depend on any of this:

- `DICTIONARY_ENABLED` defaults to `false`.
- `app/services/dictionary.py` ships `NullDictionaryService`, which returns no
  entries and never invents one. The `DictionaryService` interface is in place
  so a verified implementation can be added without touching the API or UI.
- `dictionary_used` in every API response is therefore `false` today, and says
  so honestly.
- The backend additionally strips any Private Use Area characters from model
  output and flags it as a warning, so legacy-font characters can never reach a
  user as if they were N'Ko (`app/services/nko_text.py`).

## 9. Evidence files

| File | Contents |
|---|---|
| `evidence/pdf-font-glyphs.png` | All 90 PUA glyphs rendered from the PDF's embedded font, labelled `CID/PUA` |
| `evidence/unicode-nko-ebrima.png` | `U+07C0`–`U+07FF` rendered from Ebrima, labelled |
| `evidence/tounicode-manden-subset.json` | Raw CID → ToUnicode map extracted from the PDF |

## 10. Copyright

The dictionary is a third-party published work (Baba Mamadi Diané, 1st ed.
2014). Extracted data must not be redistributed, published, or used for model
training without confirming rights. The working-data folders are git-ignored.
