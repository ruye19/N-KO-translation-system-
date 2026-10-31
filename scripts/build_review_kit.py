"""Build an offline visual review kit for data/reviewer_sample.v2.tsv.

For every sampled entry the kit shows the printed N'Ko next to the decoded
Unicode, so a reviewer can answer three separate questions:

  script fidelity     does the decoded Unicode match the printed N'Ko?
  segmentation        are the French and N'Ko lines grouped into the right entry?
  continuation        is a column-top orphan linked to the right previous entry?
                      (only asked where the decoder made such a link)

Crops come from the exact line boxes in decoded_entries.line_positions
([baseline y, x0, x1]) intersected with the PDF's own legacy-font spans, not
from whole-column strips.

Everything is read-only with respect to the inputs: the sample TSV, the decoded
database and the PDF are never modified, and the decoder is not re-run. The kit
contains excerpts of a copyrighted dictionary, so it is written under data/
(git-ignored) and the script refuses a destination inside the repository that
Git would track. Keep it local; do not upload or publish it.

Run from the repository root (needs pymupdf):

    py -3.14 scripts/build_review_kit.py
    # then open data/review_kit/index.html in a browser

The sample must be shown against the database it was drawn from (its manifest
records the content hash). reviewer_sample.v2.tsv came from decoder v1.1; after
the v1.2 rebuild, pass --db data/backups/dictionary_decoded.v1.1.0.sqlite.
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

import build_reviewer_sample as brs  # noqa: E402
import decode_dictionary as dd  # noqa: E402

DEFAULT_TSV = REPO_ROOT / "data" / "reviewer_sample.v2.tsv"
DEFAULT_DB = REPO_ROOT / "data" / "dictionary_decoded.sqlite"
DEFAULT_PDF = dd.DEFAULT_PDF
DEFAULT_OUT = REPO_ROOT / "data" / "review_kit"
VIEWER_DIR = Path(__file__).resolve().parent / "review_viewer"
VIEWER_FILES = ("index.html", "review.css", "review_core.js", "review_app.js")

KIT_TOOL = "build_review_kit"
KIT_VERSION = "1.0.0"

# Columns appended to the 19 original columns on export. The original three
# review_* columns are filled in place; nothing else in them changes.
EXTRA_COLUMNS = ("review_continuation_ok", "auto_flags", "reviewer", "reviewed_at")
ANSWERS = ("yes", "no", "uncertain")

COLUMN_X = {0: (100.0, 296.0), 1: (302.0, 496.0)}   # pt: crop width for each column
CONTEXT_PAD = 16.0      # pt above/below the entry: about one neighbouring line
LINE_PAD = 2.0          # pt around a single N'Ko line
BASELINE_TOL = 1.0      # pt: span origin vs stored baseline
# Span boxes come from font metrics (24 pt tall on a 14 pt line pitch) and would
# take in the neighbouring lines, so the vertical extent is a band around the
# baseline instead: ink reaches ~10.5 pt above it (tone marks) and ~3 pt below.
LINE_ABOVE, LINE_BELOW = 12.0, 4.0
CONTEXT_DPI = 200
LINE_DPI = 300


# --- inputs ---------------------------------------------------------------

def read_sample(tsv: Path) -> list[list[str]]:
    with tsv.open(encoding="utf-8", newline="") as f:
        rows = list(csv.reader(f, delimiter="\t"))
    if tuple(rows[0]) != brs.COLUMNS:
        raise SystemExit(f"{tsv}: header is not the 19 reviewer-sample columns")
    bad = [i for i, r in enumerate(rows[1:], 2) if len(r) != len(brs.COLUMNS)]
    if bad:
        raise SystemExit(f"{tsv}: malformed rows at lines {bad}")
    return rows[1:]


def sample_db_hash(tsv: Path) -> str | None:
    """Decoded-database content hash recorded in the sample's manifest, if any."""
    try:
        return json.loads(tsv.with_suffix(".manifest.json").read_text(encoding="utf-8")).get("source_db_content_sha256")
    except (OSError, ValueError):
        return None


def load_entries(db: Path) -> dict[str, dict]:
    conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = {r["entry_ref"]: dict(r) for r in conn.execute("SELECT * FROM decoded_entries")}
        meta = dict(conn.execute("SELECT key, value FROM decode_metadata").fetchall())
    finally:
        conn.close()
    return rows, meta


class PageSpans:
    """Span boxes per PDF page, read once: legacy N'Ko spans and other text spans."""

    def __init__(self, doc):
        self.doc = doc
        self._cache: dict[int, tuple[list, list]] = {}

    def get(self, number: int) -> tuple[list, list]:
        if number not in self._cache:
            nko, text = [], []
            for block in self.doc[number - 1].get_text("rawdict")["blocks"]:
                for line in block.get("lines", []):
                    for span in line["spans"]:
                        chars = span["chars"]
                        if not chars:
                            continue
                        item = (chars[0]["origin"][1], tuple(span["bbox"]))
                        if any(f in span["font"] for f in dd.LEGACY_FONTS):
                            nko.append(item)
                        elif "".join(c["c"] for c in chars).strip():
                            text.append(item)
            self._cache[number] = (nko, text)
        return self._cache[number]


def _union(boxes):
    return (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))


def nko_line_box(spans: PageSpans, page: int, y: float, x0: float, x1: float) -> tuple:
    """Box of the printed N'Ko line stored as (y, x0, x1): the legacy-font spans on
    that baseline that overlap [x0, x1], cut vertically to the baseline band.
    x0/x1 are glyph origins, so the spans' own edges are kept: clipping to x1
    would cut the rightmost glyph."""
    nko, _text = spans.get(page)
    hits = [b for oy, b in nko if abs(oy - y) <= BASELINE_TOL and b[2] > x0 - 1 and b[0] < x1 + 1]
    if not hits:
        raise ValueError(f"p{page}: no N'Ko span on baseline {y} between x {x0}-{x1}")
    u = _union(hits)
    return (u[0], y - LINE_ABOVE, u[2], y + LINE_BELOW)


def french_line_box(spans: PageSpans, page: int, column: int, y: float) -> tuple | None:
    _nko, text = spans.get(page)
    cx0, cx1 = COLUMN_X[column]
    hits = [b for oy, b in text if abs(oy - y) <= BASELINE_TOL and cx0 <= b[0] < cx1]
    if not hits:
        return None
    u = _union(hits)
    return (u[0], max(u[1], y - LINE_ABOVE), u[2], min(u[3], y + LINE_BELOW))


# --- record assembly ------------------------------------------------------

def bracket_balance(text: str) -> int:
    return text.count("(") + text.count("[") - text.count(")") - text.count("]")


def auto_flags(entry: dict, parent: dict | None) -> list[dict]:
    """Automatic warnings shown to the reviewer. They never change the data."""
    flags = []
    if entry["continued_from"] and parent is not None:
        own, theirs = bracket_balance(entry["decoded_nko"]), bracket_balance(parent["decoded_nko"])
        if own < 0 and theirs <= 0:
            flags.append({
                "code": "continuation_bracket_contradiction",
                "severity": "warning",
                "message": (
                    f"Suspected incorrect continuation. This row closes {-own} bracket(s) that the linked "
                    f"entry {parent['entry_ref']} ({parent['headword'] or 'no headword'}) never opens, so the "
                    f"brackets contradict the link (decoder evidence: {entry['continuation_evidence']}). "
                    "The correct parent is not known and the row has not been reassigned."
                ),
            })
    return flags


def entry_view(e: dict) -> dict:
    return {
        "entry_ref": e["entry_ref"],
        "page": e["page_number"],
        "column": e["column_index"],
        "kind": e["entry_kind"],
        "headword": e["headword"],
        "headword_lines": [{"y": y, "text": t} for y, t in json.loads(e["headword_lines"])],
        "decoded_lines": e["decoded_nko"].split("\n"),
        "line_positions": json.loads(e["line_positions"]),
        "link_status": e["link_status"],
        "flags": json.loads(e["flags"]),
        "parent_entry_ref": e["parent_entry_ref"],
        "continued_from": e["continued_from"],
        "continuation_evidence": e["continuation_evidence"],
        "continued_by": json.loads(e["continued_by"]) if e["continued_by"] else [],
    }


def context_crop(spans: PageSpans, e: dict) -> dict:
    """Crop rectangle (pt) for an entry plus highlight boxes as fractions of it."""
    page, col = e["page_number"], e["column_index"]
    boxes = []
    for i, (y, x0, x1) in enumerate(json.loads(e["line_positions"])):
        boxes.append(("nko", i, nko_line_box(spans, page, y, x0, x1)))
    for i, (y, _t) in enumerate(json.loads(e["headword_lines"])):
        b = french_line_box(spans, page, col, y)
        if b:
            boxes.append(("fr", i, b))
    if not boxes:
        raise ValueError(f"{e['entry_ref']}: nothing to crop")
    u = _union([b for _k, _i, b in boxes])
    cx0, cx1 = COLUMN_X[col]
    page_rect = spans.doc[page - 1].rect
    clip = (min(cx0, u[0] - 2), max(page_rect.y0, u[1] - CONTEXT_PAD),
            max(cx1, u[2] + 2), min(page_rect.y1, u[3] + CONTEXT_PAD))
    w, h = clip[2] - clip[0], clip[3] - clip[1]
    return {
        "page": page,
        "clip": [round(v, 2) for v in clip],
        "boxes": [{"kind": k, "line": i,
                   "l": round((b[0] - clip[0]) / w, 5), "t": round((b[1] - clip[1]) / h, 5),
                   "w": round((b[2] - b[0]) / w, 5), "h": round((b[3] - b[1]) / h, 5)}
                  for k, i, b in boxes],
    }


def build_records(sample_rows: list[list[str]], entries: dict, spans: PageSpans) -> list[dict]:
    idx = {c: i for i, c in enumerate(brs.COLUMNS)}
    records = []
    for row in sample_rows:
        ref = row[idx["entry_ref"]]
        e = entries.get(ref)
        if e is None:
            raise SystemExit(f"{row[idx['sample_id']]}: {ref} is not in the decoded database")
        if e["decoded_nko"].replace("\n", " | ") != row[idx["decoded_nko"]]:
            raise SystemExit(f"{row[idx['sample_id']]}: TSV and database disagree on decoded_nko")
        parent = entries.get(e["continued_from"]) if e["continued_from"] else None
        sid = row[idx["sample_id"]]
        rec = {
            "sample_id": sid,
            "original": row,
            "entry": entry_view(e),
            "context": {**context_crop(spans, e), "img": f"crops/{sid}_context.png"},
            "lines": [],
            "continuation": None,
            "structural_parent": None,
            "auto_flags": auto_flags(e, parent),
        }
        for i, (y, x0, x1) in enumerate(json.loads(e["line_positions"])):
            b = nko_line_box(spans, e["page_number"], y, x0, x1)
            rec["lines"].append({"img": f"crops/{sid}_line{i + 1}.png", "y": y, "x0": x0, "x1": x1,
                                 "clip": [round(b[0] - LINE_PAD, 2), round(b[1] - LINE_PAD, 2),
                                          round(b[2] + LINE_PAD, 2), round(b[3] + LINE_PAD, 2)]})
        if e["continued_from"]:
            if parent is None:
                raise SystemExit(f"{sid}: continued_from {e['continued_from']} is not in the database")
            rec["continuation"] = {
                "parent": entry_view(parent),
                "evidence": e["continuation_evidence"],
                "context": {**context_crop(spans, parent), "img": f"crops/{sid}_parent.png"},
            }
        if e["parent_entry_ref"] and e["parent_entry_ref"] in entries:
            p = entries[e["parent_entry_ref"]]
            rec["structural_parent"] = {"entry_ref": p["entry_ref"], "headword": p["headword"],
                                        "decoded_lines": p["decoded_nko"].split("\n")}
        records.append(rec)
    return records


# --- output ---------------------------------------------------------------

def check_out_dir(out: Path) -> None:
    out = out.resolve()
    protected = [p.resolve() for p in (DEFAULT_PDF, DEFAULT_DB, DEFAULT_TSV, dd.SOURCE_DB, dd.RAW_JSONL,
                                       REPO_ROOT / "data" / "backups" / "dictionary_decoded.v1.1.0.sqlite")]
    if (out in protected or any(p.parent == out for p in protected)
            or any(out.is_relative_to((REPO_ROOT / d).resolve()) for d in ("docs", "data/backups"))):
        raise SystemExit(f"refusing to write the review kit to {out}: it would sit beside or over source files")
    if out.is_relative_to(REPO_ROOT.resolve()):
        probe = out / "crops" / "probe.png"
        res = subprocess.run(["git", "check-ignore", "-q", str(probe)], cwd=REPO_ROOT, capture_output=True)
        if res.returncode != 0:
            raise SystemExit(f"{out} is inside the repository and not git-ignored; the kit holds copyrighted "
                             "excerpts, so choose a git-ignored or external directory")
    if out.exists() and any(out.iterdir()):
        manifest = out / "kit_manifest.json"
        try:
            ok = json.loads(manifest.read_text(encoding="utf-8")).get("tool") == KIT_TOOL
        except (OSError, ValueError):
            ok = False
        if not ok:
            raise SystemExit(f"{out} is not empty and was not produced by {KIT_TOOL}; refusing to write into it")


def render(doc, page: int, clip: list[float], dpi: int, path: Path) -> tuple[int, int]:
    import fitz

    pix = doc[page - 1].get_pixmap(clip=fitz.Rect(*clip), dpi=dpi)
    pix.save(str(path))
    return pix.width, pix.height


def write_kit(records: list[dict], doc, out: Path, source: dict) -> dict:
    crops = out / "crops"
    crops.mkdir(parents=True, exist_ok=True)
    files = []
    for rec in records:
        ctx = rec["context"]
        ctx["px"] = render(doc, ctx["page"], ctx["clip"], CONTEXT_DPI, out / ctx["img"])
        files.append(ctx["img"])
        for line in rec["lines"]:
            line["px"] = render(doc, rec["entry"]["page"], line["clip"], LINE_DPI, out / line["img"])
            files.append(line["img"])
        if rec["continuation"]:
            pc = rec["continuation"]["context"]
            pc["px"] = render(doc, pc["page"], pc["clip"], CONTEXT_DPI, out / pc["img"])
            files.append(pc["img"])
    for name in VIEWER_FILES:
        shutil.copyfile(VIEWER_DIR / name, out / name)
    data = {
        "kit_version": KIT_VERSION,
        "columns": list(brs.COLUMNS),
        "extra_columns": list(EXTRA_COLUMNS),
        "answers": list(ANSWERS),
        "source": source,
        "records": records,
    }
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    (out / "review_data.js").write_text(f"window.REVIEW_DATA = {payload};\n", encoding="utf-8", newline="\n")
    manifest = {
        "tool": KIT_TOOL,
        "kit_version": KIT_VERSION,
        "source": source,
        "records": len(records),
        "auto_flagged": [r["sample_id"] for r in records if r["auto_flags"]],
        "continuation_rows": [r["sample_id"] for r in records if r["continuation"]],
        "images": len(files),
        "note": "Local review material containing copyrighted dictionary excerpts. Do not commit, upload or publish.",
    }
    (out / "kit_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n",
                                           encoding="utf-8", newline="\n")
    return manifest


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tsv", type=Path, default=DEFAULT_TSV)
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--pdf", type=Path, default=DEFAULT_PDF)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--only", help="comma-separated sample_ids (for quick checks)")
    args = ap.parse_args()

    for p in (args.tsv, args.db, args.pdf):
        if not p.exists():
            print(f"{p} not found", file=sys.stderr)
            return 1
    check_out_dir(args.out)
    import fitz

    rows = read_sample(args.tsv)
    if args.only:
        wanted = set(args.only.split(","))
        rows = [r for r in rows if r[0] in wanted]
        if len(rows) != len(wanted):
            print(f"unknown sample_id in --only {args.only}", file=sys.stderr)
            return 1
    entries, meta = load_entries(args.db)
    wanted_db = sample_db_hash(args.tsv)
    if wanted_db and meta.get("content_sha256") != wanted_db:
        print(f"{args.tsv.name} was drawn from decoded-database content {wanted_db[:12]}…, but {args.db} holds "
              f"{str(meta.get('content_sha256'))[:12]}… (decoder {meta.get('decoder_version')}). Pass --db with the "
              f"database the sample came from, e.g. data/backups/dictionary_decoded.v1.1.0.sqlite", file=sys.stderr)
        return 1
    doc = fitz.open(str(args.pdf))
    try:
        records = build_records(rows, entries, PageSpans(doc))
        source = {
            "sample_tsv": args.tsv.name,
            "sample_tsv_sha256": dd.sha256_file(args.tsv),
            "decoded_db_content_sha256": meta.get("content_sha256"),
            "decoder_version": meta.get("decoder_version"),
            "pdf_sha256": dd.sha256_file(args.pdf),
            "subset": bool(args.only),
        }
        args.out.mkdir(parents=True, exist_ok=True)
        manifest = write_kit(records, doc, args.out, source)
    finally:
        doc.close()
    print(json.dumps(manifest, ensure_ascii=False, indent=1))
    print(f"open {args.out / 'index.html'} in a browser", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
