"""Tests for the v1.1 -> v1.2 spacing review (scripts/build_spacing_review.py and
scripts/spacing_viewer/spacing_core.js).

Unit tests use synthetic strings. The rest need the v2 reviewer sample, the
v1.1 backup, the v1.2 database and the PDF (with pymupdf), and are skipped, not
silently passed, without them. Output only goes to pytest's tmp_path.
"""

import csv
import hashlib
import json
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import build_spacing_review as bsr  # noqa: E402

SCRIPT = REPO_ROOT / "scripts" / "build_spacing_review.py"
CORE_JS = REPO_ROOT / "scripts" / "spacing_viewer" / "spacing_core.js"
SHARED_JS = REPO_ROOT / "scripts" / "review_viewer" / "review_core.js"
INPUTS = (bsr.DEFAULT_SAMPLE, bsr.DEFAULT_OLD_DB, bsr.DEFAULT_NEW_DB, bsr.DEFAULT_PDF)
have_inputs = pytest.mark.skipif(not all(p.exists() for p in INPUTS),
                                 reason="v2 sample, v1.1 backup, v1.2 database or PDF missing")
NODE = shutil.which("node")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# --- text comparison (synthetic) ------------------------------------------------

def test_diff_marks_inserted_removed_and_unchanged_spaces():
    old, new = "  ߞߊߡ. ߓߊ ", "ߞߊ ߡ. ߓߊ"
    segs = bsr.diff_line(old, new)
    assert [(s["t"], s.get("n"), s.get("offset")) for s in segs if s["t"] != "text"] == [
        ("del", 2, 0), ("ins", 1, 2), ("space", 1, 4), ("del", 1, 6)]
    assert bsr.rebuild(segs, "old") == old and bsr.rebuild(segs, "new") == new


def test_diff_refuses_anything_but_space_changes():
    with pytest.raises(ValueError):
        bsr.diff_line("ߞߊ", "ߞߎ")
    with pytest.raises(ValueError):
        bsr.diff_line("ߞ ߊ", "ߞ ߊ")      # a no-break space is not U+0020


def test_transformation_offsets_follow_the_alignment():
    alignment = [[0xF120, ""], [0xF16A, "ߞ"], [None, " "], [0xF1AC, "ߊ"], [0xF120, ""]]
    ts = [{"line": 0, "index": 0, "rule": "leading_layout_space_removed"},
          {"line": 0, "index": 2, "rule": "positioned_space_inserted", "gap_pt": 2.5, "spaces": 1},
          {"line": 0, "index": 3, "rule": "trailing_layout_space_removed"},
          {"line": 0, "index": 1, "rule": "bracket_mirrored"},
          {"line": 1, "index": 0, "rule": "positioned_space_inserted", "gap_pt": 2.5, "spaces": 1}]
    got = [(t["rule"], t["offset"]) for t in bsr.transformation_offsets(alignment, ts, 0)]
    # A transformation's index is the code it precedes; the inserted space comes after one character.
    assert got == [("leading_layout_space_removed", 0), ("positioned_space_inserted", 1),
                   ("trailing_layout_space_removed", 2)]


# --- full sample ---------------------------------------------------------------

@pytest.fixture(scope="module")
def built():
    fitz = pytest.importorskip("fitz")
    header, rows = bsr.read_tsv(bsr.DEFAULT_SAMPLE)
    sample = [dict(zip(header, r)) for r in rows]
    old, _ = bsr.load_db(bsr.DEFAULT_OLD_DB)
    new, _ = bsr.load_db(bsr.DEFAULT_NEW_DB)
    changed = bsr.select_changed(sample, old, new)
    mapping = bsr.dd.load_mapping(bsr.dd.DEFAULT_MAPPING)
    marks = {cp for cp, i in mapping.codes.items() if i["role"] in ("mark", "composite_mark")}
    doc = fitz.open(str(bsr.DEFAULT_PDF))
    try:
        geo, spans = bsr.Geometry(doc, marks), bsr.brk.PageSpans(doc)
        records = [bsr.build_record(n, s, old[s["entry_ref"]], new[s["entry_ref"]], geo, spans)
                   for n, s in enumerate(changed, 1)]
    finally:
        doc.close()
    return sample, old, new, records


@have_inputs
def test_every_changed_sample_entry_is_included_once(built):
    sample, old, new, records = built
    expected = [s["entry_ref"] for s in sample if old[s["entry_ref"]]["decoded_nko"] != new[s["entry_ref"]]["decoded_nko"]]
    assert len(expected) == 261
    assert [r["row"]["entry_ref"] for r in records] == expected
    assert [r["spacing_id"] for r in records] == [f"SP{i:03d}" for i in range(1, 262)]
    assert len({r["row"]["sample_id"] for r in records}) == 261


@have_inputs
def test_both_versions_are_carried_exactly(built):
    _sample, old, new, records = built
    for r in records:
        ref = r["row"]["entry_ref"]
        assert r["row"]["v11_decoded_nko"] == old[ref]["decoded_nko"]
        assert r["row"]["v12_decoded_nko"] == new[ref]["decoded_nko"]
        assert [ln["old"] for ln in r["lines"]] == old[ref]["decoded_nko"].split("\n")
        assert [ln["new"] for ln in r["lines"]] == new[ref]["decoded_nko"].split("\n")
        assert r["row"]["headword"] == old[ref]["headword"] == new[ref]["headword"]
        assert old[ref]["legacy_codes"] == new[ref]["legacy_codes"]        # no mapping or glyph change


@have_inputs
def test_changes_markers_and_counts(built):
    records = built[3]
    kinds = {}
    for r in records:
        for c in r["changes"]:
            kinds[c["kind"]] = kinds.get(c["kind"], 0) + 1
        assert sum(len(ln["markers"]) for ln in r["lines"]) == len(r["changes"])
        for ln in r["lines"]:
            for m in ln["markers"]:
                assert 0 <= m["l"] <= 1 and m["w"] > 0
        assert json.loads(r["row"]["changes_json"]) == [
            {k: c[k] for k in ("id", "line", "offset", "kind", "rule", "count", "gap_pt")} for c in r["changes"]]
    assert kinds == {"inserted": 397, "removed": 287, "kept": 6}
    assert sum(int(r["row"]["spaces_inserted"]) for r in records) == 398
    assert sum(int(r["row"]["spaces_removed"]) for r in records) == 287


@have_inputs
def test_crops_follow_the_entry_lines(built):
    _sample, _old, new, records = built
    for r in records:
        e = new[r["row"]["entry_ref"]]
        assert r["context"]["page"] == e["page_number"]
        for ln, (y, x0, x1) in zip(r["lines"], json.loads(e["line_positions"])):
            cx0, cy0, cx1, cy1 = ln["clip"]
            assert cy0 < y < cy1 and cx0 <= x0 and cx1 >= x1 and not cx0 < bsr.dd.COLUMN_SPLIT_X < cx1


# --- command line --------------------------------------------------------------

def run(*args):
    return subprocess.run([sys.executable, "-W", "ignore", str(SCRIPT), *args], capture_output=True, text=True,
                          encoding="utf-8")


@have_inputs
def test_cli_subset_keeps_full_run_ids_and_leaves_inputs_untouched(tmp_path):
    pytest.importorskip("fitz")
    before = {p: sha(p) for p in INPUTS}
    out = tmp_path / "spacing"
    res = run("--only", "S001,S345", "--out", str(out))
    assert res.returncode == 0, res.stderr
    assert {p: sha(p) for p in INPUTS} == before
    with (out / bsr.SAMPLE_NAME).open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f, delimiter="\t"))
    assert [(r["spacing_id"], r["sample_id"]) for r in rows] == [("SP001", "S001"), ("SP261", "S345")]
    for name in (*bsr.VIEWER_FILES, *bsr.SHARED_FILES, "spacing_data.js"):
        assert (out / "kit" / name).exists(), name
    assert (out / "kit" / "crops" / "SP261_context.png").exists()
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["records"] == 2 and manifest["changed_in_full_sample"] == 261 and manifest["source"]["subset"]
    first = sha(out / "kit" / "spacing_data.js")
    assert run("--only", "S001,S345", "--out", str(out)).returncode == 0
    assert sha(out / "kit" / "spacing_data.js") == first


@have_inputs
@pytest.mark.parametrize("dest", ["data/review_kit", "data/backups/x", "docs/spacing", "scripts/spacing_probe", "data"])
def test_cli_refuses_existing_or_tracked_locations(dest):
    target = REPO_ROOT / dest
    existed = target.exists()
    assert run("--only", "S001", "--out", str(target)).returncode != 0
    assert target.exists() == existed


@have_inputs
def test_cli_refuses_foreign_directory(tmp_path):
    (tmp_path / "keep.txt").write_text("x", encoding="utf-8")
    assert run("--only", "S001", "--out", str(tmp_path)).returncode != 0
    assert sorted(p.name for p in tmp_path.iterdir()) == ["keep.txt"]


# --- spacing_core.js under Node ------------------------------------------------

def run_core(tmp_path, data, body):
    (tmp_path / "data.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    shutil.copyfile(SHARED_JS, tmp_path / "review_core.js")
    shutil.copyfile(CORE_JS, tmp_path / "spacing_core.js")
    (tmp_path / "run.js").write_text(
        "const fs = require('fs');\n"
        "const core = require('./spacing_core.js');\n"
        "const data = JSON.parse(fs.readFileSync(__dirname + '/data.json', 'utf8'));\n"
        f"const out = (() => {{ {body} }})();\n"
        "fs.writeFileSync(__dirname + '/out.json', JSON.stringify(out));\n", encoding="utf-8")
    res = subprocess.run([NODE, str(tmp_path / "run.js")], capture_output=True, text=True)
    assert res.returncode == 0, res.stderr
    return json.loads((tmp_path / "out.json").read_text(encoding="utf-8"))


def kit_data(records):
    return {"columns": list(bsr.COLUMNS), "answer_columns": list(bsr.ANSWER_COLUMNS), "answers": list(bsr.ANSWERS),
            "source": {}, "records": [{"spacing_id": r["spacing_id"], "row": r["row"]} for r in records]}


@have_inputs
@pytest.mark.skipif(NODE is None, reason="node not installed")
def test_unreviewed_export_starts_every_sample_line_byte_for_byte(tmp_path, built):
    records = built[3]
    bsr.write_sample(records, tmp_path / "sample.tsv")
    exported = run_core(tmp_path, kit_data(records), "return core.exportTsv(data, {});")
    original = list(csv.reader((tmp_path / "sample.tsv").open(encoding="utf-8", newline=""), delimiter="\t"))
    got = list(csv.reader(exported.splitlines(keepends=True), delimiter="\t"))
    assert got[0] == list(bsr.COLUMNS) + list(bsr.ANSWER_COLUMNS)
    assert [row[:len(bsr.COLUMNS)] for row in got] == original
    assert all(row[len(bsr.COLUMNS):] == [""] * len(bsr.ANSWER_COLUMNS) for row in got[1:])
    raw = (tmp_path / "sample.tsv").read_text(encoding="utf-8")
    # Same quoting: removing the answer columns gives the written sample back exactly.
    stripped = run_core(tmp_path, kit_data(records),
                        "const t = core.exportTsv(data, {}); const RC = require('./review_core.js');"
                        "return RC.parseTsv(t).map(r => r.slice(0, data.columns.length).map(RC.tsvField).join('\\t')).join('\\n') + '\\n';")
    assert stripped == raw


@have_inputs
@pytest.mark.skipif(NODE is None, reason="node not installed")
def test_answers_round_trip_and_bad_rows_are_rejected(tmp_path, built):
    records = built[3][:3]
    notes = '  #2 splits a word\t"x"\nline 2  '
    reviews = {"SP001": {"q1": "no", "q2": "yes", "q3": "no", "q4": "uncertain", "notes": notes, "reviewer": "AB",
                         "updated_at": "2026-10-31T00:00:00Z"},
               "SP002": {"q1": "yes", "notes": "", "reviewer": "", "updated_at": "t"}}
    out = run_core(tmp_path, kit_data(records), f"""
        const reviews = {json.dumps(reviews, ensure_ascii=False)};
        const RC = require('./review_core.js');
        const text = core.exportTsv(data, reviews);
        const rows = RC.parseTsv(text);
        const vi = data.columns.indexOf('v12_decoded_nko'), qi = rows[0].indexOf('q2_space_inserted_inside_word');
        const redo = f => rows.map((r, i) => i === 1 ? r.map(f) : r).map(r => r.map(RC.tsvField).join('\\t')).join('\\n') + '\\n';
        return {{ back: core.importTsv(data, text),
                  tampered: core.importTsv(data, redo((c, j) => j === vi ? c + ' ' : c)),
                  badAnswer: core.importTsv(data, redo((c, j) => j === qi ? 'maybe' : c)),
                  status: [core.status(reviews.SP001), core.status(reviews.SP002), core.status(undefined)],
                  problems: core.problems(reviews.SP001), summary: core.summarize(data, reviews).all }};
    """)
    back = out["back"]
    assert back["errors"] == [] and sorted(back["reviews"]) == ["SP001", "SP002"]
    for sid, r in reviews.items():
        for k in ("q1", "q2", "q3", "q4", "notes", "reviewer", "updated_at"):
            assert back["reviews"][sid][k] == r.get(k, "")
    assert out["tampered"]["errors"] and "SP001" not in out["tampered"]["reviews"]
    assert out["badAnswer"]["errors"] and "SP001" not in out["badAnswer"]["reviews"]
    assert out["status"] == ["complete", "partial", "unreviewed"]
    assert out["problems"] == ["q1", "q2", "q4"]
    assert out["summary"]["total"] == 3 and out["summary"]["q1"] == {"no": 1, "yes": 1, "unanswered": 1}
