# Visual review kit for the decoder v1.1 sample

An offline page for checking the 345 entries in `data/reviewer_sample.v2.tsv`. Each entry is shown against the printed dictionary. Nothing in the kit changes the sample, the decoded database, the PDF or the decoder.

## Copyright

The kit contains page crops and text from a copyrighted dictionary.

- It is written to `data/review_kit/`, which is git-ignored.
- The build script refuses a destination that Git would track, or one beside the source files.
- Keep the kit, the exported review file, and any screenshots local. Do not commit, upload or publish them.

## Build and open

```
py -3.14 scripts/build_review_kit.py      # needs pymupdf; about 30 s
```

The v2 sample was drawn from decoder v1.1. Since the v1.2 spacing rebuild (see `SPACING_AUDIT.md`), add `--db data/backups/dictionary_decoded.v1.1.0.sqlite`. The script refuses a database whose content hash differs from the one in the sample's manifest.

Then open `data/review_kit/index.html` in a browser. The kit needs no server or network. The page uses the Ebrima font, which ships with Windows, to show N'Ko. If Noto Sans NKo is installed, the page uses it first.

| Path | Contents |
|---|---|
| `scripts/build_review_kit.py` | Reads the TSV, the database and the PDF (read-only). Writes crops, `review_data.js` and `kit_manifest.json`. |
| `scripts/review_viewer/` | Viewer template, copied into the kit. `review_core.js` holds export and import, and is tested under Node. |
| `backend/tests/test_build_review_kit.py` | Tests for the kit. |

## What the reviewer sees

For each record the page shows the following.

- **The printed entry**, cropped from the PDF with one line of context above and below.
  - The highlight boxes come from `decoded_entries.line_positions` (`y`, `x0`, `x1`), not from whole-column strips.
  - N'Ko lines are drawn as numbered solid boxes. French headword lines are dashed.
- **Each N'Ko line on its own:**
  - the printed crop;
  - the decoded Unicode below it, exactly as stored.
- **Whitespace and placeholders:**
  - Leading and trailing whitespace is never trimmed.
  - Spaces can be shown as `·`, and each line states its leading and trailing counts.
  - Candidate and unknown codes appear as `⟨U+F1xx⟩` placeholders.
  - Code points can be shown on demand.
- **Links:**
  - For a column-top continuation, the linked previous entry, with its own crop and decoded text, and the decoder's evidence (`bracket_balance` or `reading_order`).
  - For a sub-entry, its parent headword.
- **Automatic warnings.** These are display only and never change data.
  - At present the only rule is `continuation_bracket_contradiction`. It fires when a row closes a bracket that its linked entry never opens.
  - In this sample it fires only for S345 (`p497-c1-orphan` → `p497-c0-e027` "zétète"). That link rests on reading order alone.
  - The correct parent of S345 is unknown, and the row has not been reassigned.

## Three separate questions

| Question | Asks | Answers |
|---|---|---|
| Script fidelity | Does the decoded Unicode match the printed N'Ko: letters, tone marks, nasalisation, punctuation and spacing? | yes / no / uncertain |
| Segmentation | Do the highlighted French and N'Ko lines belong together as one entry, with nothing missing or borrowed from a neighbour? | yes / no / uncertain |
| Continuation | Is this column-top orphan attached to the right previous entry? Asked only on the 10 rows the decoder linked. Answer "no" if it belongs elsewhere, without guessing where. | yes / no / uncertain, else `n/a` |

A record is complete once every question that applies is answered. Notes are free text.

**Keys:**
- 1–3: script fidelity.
- 4–6: segmentation.
- 7–9: continuation.
- j/k: next / previous.
- u: next unfinished record.
- Pressing a selected answer again clears it.

## Saving and exporting

- **In the browser.** Answers are saved in that browser's local storage, keyed to the sample's SHA-256. That storage can be lost, so use **Export TSV** as the durable record.
- **The exported file.** **Export TSV** writes `reviewer_sample.v2.review.tsv`. Store it under `data/`.
  - **First 19 columns:** the original 19 columns in their original order. The cells are unchanged, apart from the three `review_*` columns, which hold the answers.
  - **Appended columns:** `review_continuation_ok` (`n/a` where no link exists), `auto_flags`, `reviewer` and `reviewed_at`.
  - **Byte-for-byte check:** with no answers, each exported line begins with the original line byte for byte. A test checks this.
- **Importing.** **Import TSV** reloads an exported file. It rejects any row whose sample cells differ from the kit's source, and any answer outside yes / no / uncertain.
- **Summary.** **Summary** tallies the answers per stratum. Only stratum A estimates an overall error rate, so report the other strata separately.

Review answers do not change any entry's status. Every decoded row stays `machine_decoded` until a separate, deliberate step records human verification.
