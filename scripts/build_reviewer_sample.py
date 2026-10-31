"""Draw a stratified human-review sample from data/dictionary_decoded.sqlite.

Each stratum answers a different question, so results must be reported per
stratum. Only stratum A estimates an overall error rate.

  A  random     150 STRONG headword entries, spread evenly over page bands:
                unbiased per-entry error estimate (0 errors in 150 bounds
                the error rate below ~2% at 95% confidence)
  B  codes      at least 3 entries containing each STRONG legacy code, rare
                codes first: does every individual mapping hold?
  C  rules      entries where a decoding rule changed the text (wa-tail spacer
                removed, brackets mirrored, composite marks expanded)
  D  candidate  up to 10 entries per CANDIDATE code, shown with placeholders:
                evidence for promoting or rejecting each candidate mapping
  E  structure  wrapped headwords, sub-entries, column-top continuations and
                long entries: is the N'Ko attached to the right French entry?

Reviewers fill two separate columns: script fidelity (does the N'Ko match the
printed glyphs?) and segmentation (does it belong to this entry?). Nothing
here marks anything as verified.

The sample contains excerpts of a copyrighted dictionary. The default output
path is under data/, which is git-ignored; do not commit or publish it.

Run from the repository root:

    python scripts/build_reviewer_sample.py
    python scripts/build_reviewer_sample.py --crops-dir <dir>   # page-image crops (needs pymupdf)
"""

from __future__ import annotations

import argparse
import collections
import csv
import json
import random
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = REPO_ROOT / "data" / "dictionary_decoded.sqlite"
DEFAULT_OUTPUT = REPO_ROOT / "data" / "reviewer_sample.v2.tsv"
DEFAULT_PDF = REPO_ROOT / "docs" / "dictionnaire Fr_nko.pdf"
DEFAULT_SEED = 20261030

RANDOM_SIZE = 150
PAGE_BANDS = 10
PER_CODE = 3
RULE_QUOTA = {"wa_tail_spacer_removed": 20, "bracket_mirrored": 20, "composite_mark_expanded": 15}
PER_CANDIDATE = 10
STRUCTURE_QUOTA = {"wrapped_headword": 15, "subentry": 10, "continuation": 10, "long_entry": 5}

COLUMNS = (
    "sample_id", "stratum", "reason", "entry_ref", "page_number", "column_index", "entry_kind",
    "headword", "headword_lines", "decoded_nko", "weakest_tier", "candidate_codes", "rules_applied",
    "parent_entry_ref", "continued_from", "nko_baselines",
    "review_script_ok", "review_segmentation_ok", "review_notes",
)


def load_rows(db_path: Path) -> tuple[list[dict], dict]:
    conn = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = [dict(r) for r in conn.execute("SELECT * FROM decoded_entries ORDER BY entry_ref")]
        meta = dict(conn.execute("SELECT key, value FROM decode_metadata").fetchall())
    finally:
        conn.close()
    for r in rows:
        r["_codes"] = {c for line in json.loads(r["legacy_codes"]) for c in line}
        r["_rules"] = sorted({t["rule"] for t in json.loads(r["transformations"])})
    return rows, meta


def build_sample(rows: list[dict], strong_codes: list[str], candidate_codes: list[str], seed: int) -> list[dict]:
    rng = random.Random(seed)
    chosen: dict[str, tuple[str, str]] = {}   # entry_ref -> (stratum, reason)

    def take(pool: list[dict], n: int, stratum: str, reason: str) -> int:
        pool = [r for r in pool if r["entry_ref"] not in chosen]
        picked = rng.sample(pool, min(n, len(pool)))
        for r in sorted(picked, key=lambda r: r["entry_ref"]):
            chosen[r["entry_ref"]] = (stratum, reason)
        return len(picked)

    reviewable = [r for r in rows if r["entry_kind"] != "orphan_lines" and r["line_count"]]
    strong = [r for r in reviewable if r["weakest_tier"] == "STRONG"]

    # A: even spread over page bands.
    heads = [r for r in strong if r["entry_kind"] == "headword"]
    lo, hi = min(r["page_number"] for r in heads), max(r["page_number"] for r in heads)
    width = (hi - lo + 1) / PAGE_BANDS
    bands = collections.defaultdict(list)
    for r in heads:
        bands[min(PAGE_BANDS - 1, int((r["page_number"] - lo) / width))].append(r)
    for b in range(PAGE_BANDS):
        take(bands[b], RANDOM_SIZE // PAGE_BANDS, "A_random", f"page band {b + 1}/{PAGE_BANDS}")

    # B: every strong code at least PER_CODE times across the whole sample, rarest first.
    by_ref = {r["entry_ref"]: r for r in rows}
    occurrences = collections.Counter(c for r in strong for c in r["_codes"])
    for code in sorted(strong_codes, key=lambda c: (occurrences[int(c[2:], 16)], c)):
        cp = int(code[2:], 16)
        have = sum(1 for ref in chosen if cp in by_ref[ref]["_codes"])
        if have < PER_CODE:
            take([r for r in strong if cp in r["_codes"]], PER_CODE - have, "B_codes", f"contains {code}")

    # C: decoding rules that change the text.
    for rule, n in RULE_QUOTA.items():
        take([r for r in strong if rule in r["_rules"]], n, "C_rules", rule)

    # D: candidate codes, shown as placeholders.
    for code in candidate_codes:
        take([r for r in reviewable if code in json.loads(r["candidate_codes"])], PER_CANDIDATE, "D_candidate", code)

    # E: structure.
    take([r for r in reviewable if r["headword_join"].startswith("wrapped")],
         STRUCTURE_QUOTA["wrapped_headword"], "E_structure", "wrapped headword")
    take([r for r in reviewable if r["entry_kind"] == "subentry"],
         STRUCTURE_QUOTA["subentry"], "E_structure", "sub-entry")
    take([r for r in rows if r["continued_from"] and r["line_count"]],
         STRUCTURE_QUOTA["continuation"], "E_structure", "column-top continuation")
    take([r for r in reviewable if r["line_count"] >= 3],
         STRUCTURE_QUOTA["long_entry"], "E_structure", "3+ N'Ko lines")

    order = {"A_random": 0, "B_codes": 1, "C_rules": 2, "D_candidate": 3, "E_structure": 4}
    sample = sorted(chosen.items(), key=lambda kv: (order[kv[1][0]], kv[0]))
    out = []
    for i, (ref, (stratum, reason)) in enumerate(sample, 1):
        r = by_ref[ref]
        out.append({
            "sample_id": f"S{i:03d}",
            "stratum": stratum,
            "reason": reason,
            "entry_ref": ref,
            "page_number": r["page_number"],
            "column_index": r["column_index"],
            "entry_kind": r["entry_kind"],
            "headword": r["headword"],
            "headword_lines": " | ".join(t.strip() for _y, t in json.loads(r["headword_lines"])),
            "decoded_nko": r["decoded_nko"].replace("\n", " | "),
            "weakest_tier": r["weakest_tier"],
            "candidate_codes": " ".join(json.loads(r["candidate_codes"])),
            "rules_applied": " ".join(r["_rules"]),
            "parent_entry_ref": r["parent_entry_ref"] or "",
            "continued_from": r["continued_from"] or "",
            "nko_baselines": " ".join(str(p[0]) for p in json.loads(r["line_positions"])),
            "review_script_ok": "",
            "review_segmentation_ok": "",
            "review_notes": "",
        })
    return out


def code_coverage(sample: list[dict], rows: list[dict], strong_codes: list[str]) -> dict:
    by_ref = {r["entry_ref"]: r for r in rows}
    counts = collections.Counter(c for s in sample for c in by_ref[s["entry_ref"]]["_codes"])
    return {code: counts[int(code[2:], 16)] for code in strong_codes}


def write_crops(sample: list[dict], rows: list[dict], pdf: Path, crops_dir: Path) -> int:
    import fitz

    by_ref = {r["entry_ref"]: r for r in rows}
    crops_dir.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(str(pdf))
    for s in sample:
        r = by_ref[s["entry_ref"]]
        ys = [p[0] for p in json.loads(r["line_positions"])] + [y for y, _t in json.loads(r["headword_lines"])]
        x0, x1 = (95.0, 300.0) if r["column_index"] == 0 else (300.0, 505.0)
        clip = fitz.Rect(x0, min(ys) - 16, x1, max(ys) + 8)
        pix = doc[r["page_number"] - 1].get_pixmap(clip=clip, dpi=200)
        pix.save(str(crops_dir / f"{s['sample_id']}_{s['entry_ref']}.png"))
    doc.close()
    return len(sample)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED)
    ap.add_argument("--crops-dir", type=Path, help="also save a page-image crop per sampled entry")
    ap.add_argument("--pdf", type=Path, default=DEFAULT_PDF)
    args = ap.parse_args()

    if not args.db.exists():
        print(f"{args.db} not found; run scripts/decode_dictionary.py first", file=sys.stderr)
        return 1
    protected = {(REPO_ROOT / p).resolve() for p in ("data/dictionary.sqlite", "data/raw_extraction.jsonl",
                                                     "docs/dictionnaire Fr_nko.pdf", "data/dictionary_decoded.sqlite",
                                                     "docs/dictionary-decoding/reviewer_sample.tsv")}
    if args.output.resolve() in protected:
        print(f"refusing to overwrite {args.output}", file=sys.stderr)
        return 1

    rows, meta = load_rows(args.db)
    conn = sqlite3.connect(f"file:{args.db.as_posix()}?mode=ro", uri=True)
    strong_codes = [c for (c,) in conn.execute("SELECT codepoint FROM code_inventory WHERE handling = 'STRONG' ORDER BY codepoint")]
    candidate_codes = [c for (c,) in conn.execute("SELECT codepoint FROM code_inventory WHERE handling = 'CANDIDATE' ORDER BY codepoint")]
    conn.close()

    sample = build_sample(rows, strong_codes, candidate_codes, args.seed)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, delimiter="\t", lineterminator="\n")
        w.writeheader()
        w.writerows(sample)

    coverage = code_coverage(sample, rows, strong_codes)
    manifest = {
        "seed": args.seed,
        "source_db_content_sha256": meta.get("content_sha256"),
        "decoder_version": meta.get("decoder_version"),
        "mapping_version": meta.get("mapping_version"),
        "sample_size": len(sample),
        "by_stratum": dict(sorted(collections.Counter(s["stratum"] for s in sample).items())),
        "strong_codes_below_target": {c: n for c, n in coverage.items() if n < PER_CODE},
        "status_note": "Review sample only. Entries remain machine_decoded until a separate review record says otherwise.",
    }
    if args.crops_dir:
        manifest["crops"] = write_crops(sample, rows, args.pdf, args.crops_dir)
    manifest_path = args.output.with_suffix(".manifest.json")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
