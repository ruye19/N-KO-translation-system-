# Provenance: N'Ko dictionary decoding evidence

Preserved 2026-10-30. The three evidence files below were copied byte-for-byte from the investigation session's scratchpad (`…\scratchpad\inv\`). The SHA-256 of each copy equals its original.

| File | SHA-256 | What it is |
|---|---|---|
| `DICTIONARY_DECODING_REPORT.md` | `2845b6eb7e25a4f58f92feb1af5d0e32aa6ab3e0aaf294290df31721b4e7eca3` | investigation report (unedited; see `REPRODUCIBILITY_AUDIT.md` for corrections) |
| `mapping_tiers.json` | `b089c80a09023111c8ceae3c48ae93a872d21db8dcc8d84f6c241afac157489e` | legacy code → candidate Unicode, tier, evidence summary |
| `reviewer_sample.tsv` | `99f5b9bf89a4060f3739e8bbab569eedffc73c8b4e92a8656154f8ecdbaffd8c` | 80 randomly sampled decoded entries for human spot-checking |

## Source artefacts these were derived from (unchanged)

| File | SHA-256 |
|---|---|
| `docs/dictionnaire Fr_nko.pdf` | `871628d99b9601cbdb9d797c54ffa81cad0f0ba1b4920de3aca64e3706be574b` |
| `data/dictionary.sqlite` | `c01e64ffdd2e483afa4a662e6347087e2caa4c08c538dbeafb196b82cfc438ef` |
| `data/raw_extraction.jsonl` | `676f6b3f1eeca0fb90dd3ac1b2fa5069f9c53b0070f470ab170a26f99676f3c0` |

If the PDF hash ever differs, every finding here must be re-run before it is relied on.

## Evidence the report relies on

1. Glyph shape against two reference fonts: Ebrima (`C:\Windows\Fonts\ebrima.ttf`) and Noto Sans NKo (found locally under a Tor Browser install, so machine-specific).
2. Embedded-font structure: zero-advance marks, identical outlines, composite marks.
3. Orthographic statistics: tone marks on vowels; woloso letters after nasals.
4. Cribs: the dictionary's single-letter alphabet entries (ordinal arithmetic), front matter against French text and the font copyright string in the same PDF, and basic vocabulary.

## Limitations stated by the report (and still true)

- Nothing is human-verified. "STRONG" means multiple independent lines of evidence agree; it is not a verification status.
- 7 codes are CANDIDATE only; 2 codes (`46`, `4E`) are unresolved and appear only in front matter.
- The vocabulary and basmala cribs depend on the investigator's knowledge of Manding, not on a source in this repository.
- `data/raw_extraction.jsonl` is in visual order with marks before their base; it cannot be decoded by table lookup.
- Coverage figures depend on a geometric headword segmentation heuristic.

## Deliberately NOT preserved here

- `corpus.json` (the full geometric re-extraction of the dictionary): copyrighted text.
- Extracted font programs: third-party fonts embedded in the PDF.
- The investigation's analysis scripts: they lived in the session scratchpad. An independent re-check, written from scratch, is in `scripts/audit_dictionary_decoding.py`.

## Copyright caution

`reviewer_sample.tsv` contains 80 decoded excerpts of a third-party published work (Baba Mamadi Diané, 2014), and the report quotes short passages. `docs/` is **not** git-ignored. Keep these files out of commits and published pages unless the rights position is confirmed.
