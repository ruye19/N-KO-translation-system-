# Spacing review kit (v1.1 → v1.2)

An offline page for visually checking the decoder v1.2 spacing changes (see `SPACING_AUDIT.md`). It covers the 261 entries of the v2 reviewer sample whose decoded text changed. The review does not change the decoder, the databases, or any entry's `machine_decoded` status.

## Build and open

```
py -3.14 scripts/build_spacing_review.py      # about 50 s, needs pymupdf
```

Then open `data/spacing_review/kit/index.html` in a browser. No server or network is needed.

## Inputs and outputs

All inputs are opened read-only:
- `data/reviewer_sample.v2.tsv`
- `data/backups/dictionary_decoded.v1.1.0.sqlite`
- `data/dictionary_decoded.sqlite` (v1.2)
- the PDF

The builder writes only to `data/spacing_review/`, which is git-ignored:

| File | Contents |
|---|---|
| `spacing_sample.v1.tsv` | One row per changed entry, described below |
| `manifest.json` | Hashes of every input, plus record and change counts |
| `kit/` | The viewer, the data, and 652 page crops |

Each row of `spacing_sample.v1.tsv` holds:
- **IDs:** a stable ID, SP001–SP261 in the original sample's order, and the original sample ID.
- **Location:** `entry_ref`, PDF page and column, and the French headword.
- **Both texts:** the exact v1.1 and v1.2 text. A multi-line entry is a quoted field with real newlines.
- **Change counts:** spaces inserted and removed.
- **`changes_json`:** every change, with its line, position, rule and measured gap.

### Safety

- The builder refuses any destination inside `docs/`, `data/backups/` or `data/review_kit/`, or beside a source file.
- It refuses a folder it did not create.
- It refuses a destination inside the repository that Git would track.
- The kit contains copyrighted excerpts, so keep it local.

## What it checks before writing

Each displayed change is confirmed three ways:

1. **Text difference.** Comparing v1.1 with v1.2 shows that only U+0020 differs, and both versions are rebuilt exactly from the displayed segments.
2. **Recorded transformations.** The text difference must agree with v1.2's own `transformations`, position by position.
3. **The PDF.** The page is re-read. The glyphs on each line must equal the stored legacy codes, and every measured gap must equal the recorded `gap_pt`, to within 0.02 pt.

Any mismatch stops the build. Glyphs, headwords and mappings are identical between the two versions.

## Reviewing

For each record the page shows the following.

- **The printed entry.** N'Ko lines are numbered and the French headword is dashed.
- **Each printed line, with numbered markers:**
  - green: an inserted space, shown over the measured gap;
  - red: a removed space, shown over the space glyph;
  - grey: a gap that was measured but left joined.
- **The text, three ways:**
  - v1.1 and v1.2, exactly as stored, with spaces shown as `·` (this can be switched off);
  - a "Changes" line with numbered badges at each change.
- **An evidence table:** the rule and the measured gap in points.

Answer four questions, each with yes, no or uncertain:

1. Does the v1.2 word separation match the printed PDF?
2. Were any spaces inserted inside a word?
3. Were any meaningful spaces removed?
4. Is the result uncertain or difficult to judge?

A record counts as a problem when question 1 is "no", when question 2, 3 or 4 is "yes", or when any answer is "uncertain". Problem records show a red dot, and the status filter can list just those.

Other features:
- **Notes** are free text.
- **Keys:**
  - 1–3: question 1;
  - 4–6: question 2;
  - 7–9: question 3;
  - z/x/c: question 4 (yes/no/uncertain);
  - j/k: next / previous;
  - u: next unfinished.
- **Summary** tallies the answers, overall and per original stratum.

## Saving and exporting

- **In the browser.** Answers are saved in the browser's local storage, keyed to the spacing sample's SHA-256. That storage can be lost, so **Export TSV** is the durable record.
- **The export file.** **Export TSV** downloads `spacing_sample.v1.review.tsv` to the browser's download folder. Move it into `data/spacing_review/` and keep it local.
- **What it contains.** The export repeats the 13 sample columns unchanged, then adds:
  - `q1_separation_matches_pdf`
  - `q2_space_inserted_inside_word`
  - `q3_meaningful_space_removed`
  - `q4_uncertain_or_difficult`
  - `review_notes`, `reviewer`, `reviewed_at`
- **Importing.** **Import TSV** reloads an export. It rejects rows whose sample columns were changed, and answers other than yes, no or uncertain.
