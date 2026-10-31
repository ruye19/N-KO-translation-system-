"""Build the spacing review: a sample sheet and an offline visual kit comparing
decoder v1.1 and v1.2 on the reviewer-sample entries whose text changed.

v1.2 changed whitespace only (docs/dictionary-decoding/SPACING_AUDIT.md). For
each changed entry the kit shows the printed line, the v1.1 and v1.2 decoded
text, every inserted and removed space at its place in the text AND on the
printed crop, the gap measured in the PDF and the rule that made the change.

Every displayed change is cross-checked three ways before anything is written:
the text difference between the two databases, the transformations v1.2
recorded, and the gap re-measured from the PDF for the crop markers. Any
disagreement stops the build.

All inputs are read-only: the PDF, the v1.1 backup, the v1.2 database and the
v2 reviewer sample. Output goes to data/spacing_review/ (git-ignored). It holds
copyrighted dictionary excerpts: keep it local, do not commit or publish it.

Run from the repository root (needs pymupdf):

    py -3.14 scripts/build_spacing_review.py
    # then open data/spacing_review/kit/index.html in a browser
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

import build_review_kit as brk  # noqa: E402
import decode_dictionary as dd  # noqa: E402

DEFAULT_SAMPLE = REPO_ROOT / "data" / "reviewer_sample.v2.tsv"
DEFAULT_OLD_DB = REPO_ROOT / "data" / "backups" / "dictionary_decoded.v1.1.0.sqlite"
DEFAULT_NEW_DB = REPO_ROOT / "data" / "dictionary_decoded.sqlite"
DEFAULT_PDF = dd.DEFAULT_PDF
DEFAULT_OUT = REPO_ROOT / "data" / "spacing_review"
VIEWER_DIR = Path(__file__).resolve().parent / "spacing_viewer"
VIEWER_FILES = ("index.html", "spacing.css", "spacing_core.js", "spacing_app.js")
SHARED_FILES = {"review_core.js": brk.VIEWER_DIR / "review_core.js"}   # TSV quoting, shared with the first kit

TOOL = "build_spacing_review"
VERSION = "1.0.0"
SAMPLE_NAME = "spacing_sample.v1.tsv"

COLUMNS = (
    "spacing_id", "sample_id", "stratum", "entry_ref", "page_number", "column_index", "entry_kind",
    "headword", "v11_decoded_nko", "v12_decoded_nko", "spaces_inserted", "spaces_removed", "changes_json",
)
ANSWER_COLUMNS = ("q1_separation_matches_pdf", "q2_space_inserted_inside_word", "q3_meaningful_space_removed",
                  "q4_uncertain_or_difficult", "review_notes", "reviewer", "reviewed_at")
ANSWERS = ("yes", "no", "uncertain")

# Rules v1.2 applies to spacing, and what each one means for the reviewer.
CHANGE_RULES = {
    "positioned_space_inserted": "inserted",
    "leading_layout_space_removed": "removed",
    "trailing_layout_space_removed": "removed",
}
NOTE_RULES = ("wa_tail_gap_not_a_space", "narrow_gap_not_spaced", "wide_gap_not_spaced")
SPACE = " "


# --- text comparison ---------------------------------------------------------

def space_runs(line: str) -> tuple[list[str], list[int]]:
    """Non-space characters, and the number of U+0020 before each (plus one trailing run)."""
    chars, runs, n = [], [], 0
    for ch in line:
        if ch == SPACE:
            n += 1
        else:
            chars.append(ch)
            runs.append(n)
            n = 0
    runs.append(n)
    return chars, runs


def diff_line(old: str, new: str) -> list[dict]:
    """Segments of the new line: text, unchanged spaces, inserted and removed spaces.

    Offsets count non-space characters before a space run, so they are the same
    in both versions. Raises if anything other than U+0020 differs."""
    oc, orun = space_runs(old)
    nc, nrun = space_runs(new)
    if oc != nc:
        raise ValueError("non-space characters differ")
    segs = []
    for k in range(len(nc) + 1):
        same = min(orun[k], nrun[k])
        if same:
            segs.append({"t": "space", "n": same, "offset": k})
        if nrun[k] > orun[k]:
            segs.append({"t": "ins", "n": nrun[k] - orun[k], "offset": k})
        if orun[k] > nrun[k]:
            segs.append({"t": "del", "n": orun[k] - nrun[k], "offset": k})
        if k < len(nc):
            if segs and segs[-1]["t"] == "text":
                segs[-1]["s"] += nc[k]
            else:
                segs.append({"t": "text", "s": nc[k]})
    return segs


def rebuild(segs: list[dict], version: str) -> str:
    """The v1.1 ('old') or v1.2 ('new') line from its segments: proves the display is exact."""
    out = []
    for s in segs:
        if s["t"] == "text":
            out.append(s["s"])
        elif s["t"] == "space" or (s["t"] == "ins" and version == "new") or (s["t"] == "del" and version == "old"):
            out.append(SPACE * s["n"])
    return "".join(out)


def transformation_offsets(alignment_line: list[list], transformations: list[dict], line_index: int) -> list[dict]:
    """v1.2 spacing decisions on one line, each with the non-space offset where it applies."""
    before, offset, code_index = {}, 0, 0
    for cp, piece in alignment_line:
        if cp is not None:
            before[code_index] = offset
            code_index += 1
        offset += sum(1 for ch in piece if ch != SPACE)
    out = []
    for t in transformations:
        if t["line"] != line_index or (t["rule"] not in CHANGE_RULES and t["rule"] not in NOTE_RULES):
            continue
        out.append({**t, "offset": before.get(t["index"], offset)})
    return out


# --- PDF geometry ------------------------------------------------------------

class Geometry:
    """Per-line glyph positions, rebuilt exactly as the decoder builds lines."""

    def __init__(self, doc, marks: set[int]):
        self.doc, self.marks, self._pages = doc, marks, {}

    def line(self, page: int, column: int, y: float) -> list[tuple]:
        if page not in self._pages:
            data = dd.extract_page(self.doc[page - 1], page)
            body, _excluded = dd.page_body_glyphs(data, "page_margins")
            rows = {}
            for col in (0, 1):
                grouped: dict[float, list] = {}
                for x, gy, cp, w, size in (g for g in body if (g[0] < dd.COLUMN_SPLIT_X) == (col == 0)):
                    key = next((k for k in grouped if abs(k - gy) < dd.LINE_TOLERANCE), gy)
                    grouped.setdefault(key, []).append((x, cp, w, size))
                rows.update({(col, round(k, 2)): v for k, v in grouped.items()})
            self._pages[page] = rows
        return self._pages[page][(column, round(y, 2))]

    def logical(self, glyphs: list[tuple]) -> list[tuple]:
        """(x, cp, w, size) in the decoder's logical order."""
        return sorted(glyphs, key=lambda g: (-round(g[0], 1), 1 if g[1] in self.marks else 0))

    def gap_ranges(self, glyphs: list[tuple]) -> dict[int, tuple[float, float, float]]:
        """Logical index -> (x_from, x_to, width) of the gap before it; same walk as dd.positioned_gaps."""
        order = sorted(range(len(glyphs)), key=lambda i: (-round(glyphs[i][0], 1), 1 if glyphs[i][1] in self.marks else 0))
        logical = {i: k for k, i in enumerate(order)}
        visual = sorted(range(len(glyphs)), key=lambda i: (round(glyphs[i][0], 1), 1 if glyphs[i][1] in self.marks else 0))
        out, right, prev = {}, None, None
        for i in visual:
            x, cp, w, _s = glyphs[i]
            if cp in self.marks:
                continue
            if right is not None and x - right > dd.GAP_NOTE_MIN and dd.SPACE_CODES.isdisjoint({cp, glyphs[prev][1]}):
                out[logical[prev]] = (right, x, round(x - right, 2))
            right = x + w if right is None else max(right, x + w)
            prev = i
        return out


# --- records -----------------------------------------------------------------

def read_tsv(path: Path) -> tuple[list[str], list[list[str]]]:
    with path.open(encoding="utf-8", newline="") as f:
        rows = list(csv.reader(f, delimiter="\t"))
    return rows[0], rows[1:]


def load_db(path: Path) -> tuple[dict, dict]:
    conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = {r["entry_ref"]: dict(r) for r in conn.execute("SELECT * FROM decoded_entries")}
        meta = dict(conn.execute("SELECT key, value FROM decode_metadata").fetchall())
    finally:
        conn.close()
    return rows, meta


def select_changed(sample: list[dict], old: dict, new: dict) -> list[dict]:
    return [s for s in sample if old[s["entry_ref"]]["decoded_nko"] != new[s["entry_ref"]]["decoded_nko"]]


def build_record(n: int, s: dict, o: dict, e: dict, geo: Geometry, spans: "brk.PageSpans") -> dict:
    """One spacing-review record; raises on any inconsistency."""
    ref = s["entry_ref"]
    if o["legacy_codes"] != e["legacy_codes"] or o["headword"] != e["headword"]:
        raise ValueError(f"{ref}: glyphs or headword differ between versions")
    old_lines, new_lines = o["decoded_nko"].split("\n"), e["decoded_nko"].split("\n")
    if len(old_lines) != len(new_lines):
        raise ValueError(f"{ref}: line count differs")
    alignment, transformations = json.loads(e["alignment"]), json.loads(e["transformations"])
    codes_by_line, positions = json.loads(e["legacy_codes"]), json.loads(e["line_positions"])
    lines, changes = [], []
    for li, (old, new) in enumerate(zip(old_lines, new_lines)):
        segs = diff_line(old, new)
        if rebuild(segs, "old") != old or rebuild(segs, "new") != new:
            raise ValueError(f"{ref} line {li}: segments do not rebuild both versions")
        decisions = transformation_offsets(alignment[li], transformations, li)
        # Reconcile the text difference with what v1.2 recorded, offset by offset.
        ins = {sg["offset"]: sg["n"] for sg in segs if sg["t"] == "ins"}
        dels = {sg["offset"]: sg["n"] for sg in segs if sg["t"] == "del"}
        rec_ins, rec_del = {}, {}
        for d in decisions:
            if CHANGE_RULES.get(d["rule"]) == "inserted":
                rec_ins[d["offset"]] = rec_ins.get(d["offset"], 0) + d["spaces"]
            elif CHANGE_RULES.get(d["rule"]) == "removed":
                rec_del[d["offset"]] = rec_del.get(d["offset"], 0) + 1
        if ins != rec_ins or dels != rec_del:
            raise ValueError(f"{ref} line {li}: text difference {ins}/{dels} != recorded {rec_ins}/{rec_del}")

        y, x0, x1 = positions[li]
        glyphs = geo.line(e["page_number"], e["column_index"], y)
        logical = geo.logical(glyphs)
        if [g[1] for g in logical] != codes_by_line[li]:
            raise ValueError(f"{ref} line {li}: PDF glyphs do not match the stored legacy codes")
        gaps = geo.gap_ranges(glyphs)
        box = brk.nko_line_box(spans, e["page_number"], y, x0, x1)
        clip = [round(box[0] - brk.LINE_PAD, 2), round(box[1] - brk.LINE_PAD, 2),
                round(box[2] + brk.LINE_PAD, 2), round(box[3] + brk.LINE_PAD, 2)]
        width = clip[2] - clip[0]
        markers = []
        for d in decisions:
            kind = CHANGE_RULES.get(d["rule"], "kept")
            if d["rule"] in ("positioned_space_inserted",) + NOTE_RULES:
                lo, hi, measured = gaps[d["index"]]
                if abs(measured - d["gap_pt"]) > 0.02:
                    raise ValueError(f"{ref} line {li}: re-measured gap {measured} != recorded {d['gap_pt']}")
            else:   # a removed space glyph: its own advance
                x, cp, w, _s = logical[d["index"]]
                if cp not in dd.SPACE_CODES:
                    raise ValueError(f"{ref} line {li}: removed code {cp:#x} is not a space glyph")
                lo, hi = x, x + w
            change = {
                "id": len(changes) + 1, "line": li, "offset": d["offset"], "kind": kind, "rule": d["rule"],
                "count": d.get("spaces", 1 if kind == "removed" else 0), "gap_pt": d.get("gap_pt"),
                "x": [round(lo, 2), round(hi, 2)],
            }
            changes.append(change)
            markers.append({"id": change["id"], "kind": kind,
                            "l": round(max(0.0, (lo - clip[0]) / width), 5),
                            "w": round(max(0.004, (hi - lo) / width), 5)})
        lines.append({"old": old, "new": new, "segments": segs, "y": y, "clip": clip,
                      "img": f"crops/SP{n:03d}_line{li + 1}.png", "markers": markers})
    sid = f"SP{n:03d}"
    inserted = sum(c["count"] for c in changes if c["kind"] == "inserted")
    removed = sum(c["count"] for c in changes if c["kind"] == "removed")
    return {
        "spacing_id": sid,
        "row": {
            "spacing_id": sid, "sample_id": s["sample_id"], "stratum": s["stratum"], "entry_ref": ref,
            "page_number": str(e["page_number"]), "column_index": str(e["column_index"]),
            "entry_kind": e["entry_kind"], "headword": e["headword"],
            "v11_decoded_nko": o["decoded_nko"], "v12_decoded_nko": e["decoded_nko"],
            "spaces_inserted": str(inserted), "spaces_removed": str(removed),
            "changes_json": json.dumps([{k: c[k] for k in ("id", "line", "offset", "kind", "rule", "count", "gap_pt")}
                                        for c in changes], ensure_ascii=False, separators=(",", ":")),
        },
        "lines": lines,
        "changes": changes,
        "context": {**brk.context_crop(spans, e), "img": f"crops/{sid}_context.png"},
        "flags": json.loads(e["flags"]),
    }


# --- output ------------------------------------------------------------------

def check_out_dir(out: Path) -> None:
    out = out.resolve()
    protected = [p.resolve() for p in (DEFAULT_PDF, DEFAULT_OLD_DB, DEFAULT_NEW_DB, DEFAULT_SAMPLE,
                                       DEFAULT_SAMPLE.with_suffix(".manifest.json"), dd.SOURCE_DB, dd.RAW_JSONL)]
    off_limits = [(REPO_ROOT / d).resolve() for d in ("data/review_kit", "data/backups", "docs")]
    if out in protected or any(p.parent == out for p in protected) or any(out.is_relative_to(d) for d in off_limits):
        raise SystemExit(f"refusing to write the spacing review to {out}: it would sit beside or over existing files")
    if out.is_relative_to(REPO_ROOT.resolve()):
        res = subprocess.run(["git", "check-ignore", "-q", str(out / "kit" / "probe.png")], cwd=REPO_ROOT,
                             capture_output=True)
        if res.returncode != 0:
            raise SystemExit(f"{out} is inside the repository and not git-ignored; it holds copyrighted excerpts")
    if out.exists() and any(out.iterdir()):
        try:
            ok = json.loads((out / "manifest.json").read_text(encoding="utf-8")).get("tool") == TOOL
        except (OSError, ValueError):
            ok = False
        if not ok:
            raise SystemExit(f"{out} is not empty and was not produced by {TOOL}; refusing to write into it")


def write_sample(records: list[dict], path: Path) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, delimiter="\t", lineterminator="\n")
        w.writeheader()
        w.writerows(r["row"] for r in records)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sample", type=Path, default=DEFAULT_SAMPLE)
    ap.add_argument("--old-db", type=Path, default=DEFAULT_OLD_DB)
    ap.add_argument("--new-db", type=Path, default=DEFAULT_NEW_DB)
    ap.add_argument("--pdf", type=Path, default=DEFAULT_PDF)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--only", help="comma-separated original sample_ids (quick checks; ids stay those of the full run)")
    args = ap.parse_args()

    for p in (args.sample, args.old_db, args.new_db, args.pdf):
        if not p.exists():
            print(f"{p} not found", file=sys.stderr)
            return 1
    check_out_dir(args.out)
    before = {str(p): dd.sha256_file(p) for p in (args.sample, args.old_db, args.new_db, args.pdf)}
    import fitz

    header, rows = read_tsv(args.sample)
    if tuple(header) != brk.brs.COLUMNS:
        print(f"{args.sample}: not a v2 reviewer sample", file=sys.stderr)
        return 1
    sample = [dict(zip(header, r)) for r in rows]
    old, old_meta = load_db(args.old_db)
    new, new_meta = load_db(args.new_db)
    wanted = brk.sample_db_hash(args.sample)
    if wanted and old_meta.get("content_sha256") != wanted:
        print(f"{args.old_db} is not the database {args.sample.name} was drawn from", file=sys.stderr)
        return 1
    for s in sample:
        if old[s["entry_ref"]]["decoded_nko"].replace("\n", " | ") != s["decoded_nko"]:
            print(f"{s['sample_id']}: sample text differs from {args.old_db.name}", file=sys.stderr)
            return 1

    changed = select_changed(sample, old, new)
    numbered = list(enumerate(changed, 1))          # ids depend on the full selection, never on --only
    if args.only:
        wanted_ids = set(args.only.split(","))
        numbered = [(n, s) for n, s in numbered if s["sample_id"] in wanted_ids]
        if len(numbered) != len(wanted_ids):
            print(f"--only names sample_ids that did not change: {args.only}", file=sys.stderr)
            return 1

    mapping = dd.load_mapping(dd.DEFAULT_MAPPING)
    marks = {cp for cp, i in mapping.codes.items() if i["role"] in ("mark", "composite_mark")}
    doc = fitz.open(str(args.pdf))
    out = args.out
    kit = out / "kit"
    try:
        geo, spans = Geometry(doc, marks), brk.PageSpans(doc)
        records = [build_record(n, s, old[s["entry_ref"]], new[s["entry_ref"]], geo, spans) for n, s in numbered]
        (kit / "crops").mkdir(parents=True, exist_ok=True)
        images = 0
        for r in records:
            ctx = r["context"]
            ctx["px"] = brk.render(doc, ctx["page"], ctx["clip"], brk.CONTEXT_DPI, kit / ctx["img"])
            images += 1
            for ln in r["lines"]:
                ln["px"] = brk.render(doc, ctx["page"], ln["clip"], brk.LINE_DPI, kit / ln["img"])
                images += 1
    finally:
        doc.close()

    write_sample(records, out / SAMPLE_NAME)
    for name in VIEWER_FILES:
        shutil.copyfile(VIEWER_DIR / name, kit / name)
    for name, src in SHARED_FILES.items():
        shutil.copyfile(src, kit / name)
    source = {
        "sample": args.sample.name, "sample_sha256": before[str(args.sample)],
        "v11_db_content_sha256": old_meta.get("content_sha256"), "v11_decoder_version": old_meta.get("decoder_version"),
        "v12_db_content_sha256": new_meta.get("content_sha256"), "v12_decoder_version": new_meta.get("decoder_version"),
        "pdf_sha256": before[str(args.pdf)], "spacing_sample_sha256": dd.sha256_file(out / SAMPLE_NAME),
        "subset": bool(args.only),
    }
    data = {"version": VERSION, "columns": list(COLUMNS), "answer_columns": list(ANSWER_COLUMNS),
            "answers": list(ANSWERS), "source": source, "records": records}
    (kit / "spacing_data.js").write_text(
        "window.SPACING_DATA = " + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + ";\n",
        encoding="utf-8", newline="\n")
    manifest = {
        "tool": TOOL, "version": VERSION, "source": source,
        "records": len(records), "changed_in_full_sample": len(changed), "images": images,
        "spaces_inserted": sum(int(r["row"]["spaces_inserted"]) for r in records),
        "spaces_removed": sum(int(r["row"]["spaces_removed"]) for r in records),
        "note": "Local review material containing copyrighted dictionary excerpts. Do not commit, upload or publish. "
                "Answers do not verify anything; every row stays machine_decoded.",
    }
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n",
                                       encoding="utf-8", newline="\n")
    after = {str(p): dd.sha256_file(p) for p in (args.sample, args.old_db, args.new_db, args.pdf)}
    if after != before:
        raise SystemExit("an input file changed during the build")
    print(json.dumps(manifest, ensure_ascii=False, indent=1))
    print(f"open {kit / 'index.html'} in a browser", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
