"""Tests for the offline visual review kit (scripts/build_review_kit.py and
scripts/review_viewer/review_core.js).

They need the generated sample TSV and decoded database plus pymupdf, and are
skipped, not silently passed, without them. The export/import tests also need
Node. All output goes to pytest's tmp_path.
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

TSV = REPO_ROOT / "data" / "reviewer_sample.v2.tsv"
PDF = REPO_ROOT / "docs" / "dictionnaire Fr_nko.pdf"
SCRIPT = REPO_ROOT / "scripts" / "build_review_kit.py"
CORE_JS = REPO_ROOT / "scripts" / "review_viewer" / "review_core.js"
CURRENT_DB = REPO_ROOT / "data" / "dictionary_decoded.sqlite"

fitz = pytest.importorskip("fitz")

import build_review_kit as brk  # noqa: E402


def content_hash(db: Path) -> str | None:
    conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    try:
        row = conn.execute("SELECT value FROM decode_metadata WHERE key = 'content_sha256'").fetchone()
        return row[0] if row else None
    finally:
        conn.close()


def sample_database() -> Path | None:
    """The decoded database the sample was drawn from: current or a backup."""
    wanted = brk.sample_db_hash(TSV) if TSV.exists() else None
    candidates = [CURRENT_DB, *sorted((REPO_ROOT / "data" / "backups").glob("dictionary_decoded*.sqlite"))]
    return next((p for p in candidates if p.exists() and content_hash(p) == wanted), None)


DB = sample_database()
pytestmark = pytest.mark.skipif(not (TSV.exists() and DB and PDF.exists()),
                                reason="sample TSV, the decoded DB it was drawn from, or the PDF is missing")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture(scope="module")
def sample_rows():
    return brk.read_sample(TSV)


@pytest.fixture(scope="module")
def entries():
    return brk.load_entries(DB)[0]


@pytest.fixture(scope="module")
def records(sample_rows, entries):
    doc = fitz.open(str(PDF))
    try:
        return brk.build_records(sample_rows, entries, brk.PageSpans(doc))
    finally:
        doc.close()


def test_every_record_keeps_its_19_original_cells(sample_rows, records):
    assert len(records) == len(sample_rows) == 345
    for row, rec in zip(sample_rows, records):
        assert rec["original"] == row and len(row) == 19
        assert rec["sample_id"] == row[0]


def test_decoded_lines_are_not_trimmed(records, entries):
    idx = brk.brs.COLUMNS.index("decoded_nko")
    edged = 0
    for rec in records:
        lines = rec["entry"]["decoded_lines"]
        assert "\n".join(lines) == entries[rec["entry"]["entry_ref"]]["decoded_nko"]
        assert " | ".join(lines) == rec["original"][idx]
        edged += any(s != s.strip() for s in lines)
    assert edged > 0, "expected some lines with leading/trailing whitespace to survive"


def test_line_boxes_follow_line_positions(records):
    for rec in records:
        positions = rec["entry"]["line_positions"]
        assert len(rec["lines"]) == len(positions) == len(rec["entry"]["decoded_lines"])
        for line, (y, x0, x1) in zip(rec["lines"], positions):
            cx0, cy0, cx1, cy1 = line["clip"]
            assert cy0 < y < cy1 and cy1 - cy0 <= brk.LINE_ABOVE + brk.LINE_BELOW + 2 * brk.LINE_PAD + 0.01
            assert cx0 <= x0 and cx1 >= x1 and cx1 - cx0 < 200, rec["sample_id"]   # one line, not a column
            assert not cx0 < brk.dd.COLUMN_SPLIT_X < cx1
        nko_boxes = [b for b in rec["context"]["boxes"] if b["kind"] == "nko"]
        assert [b["line"] for b in nko_boxes] == list(range(len(positions)))
        for b in rec["context"]["boxes"]:
            assert 0 <= b["l"] and 0 <= b["t"] and b["l"] + b["w"] <= 1.0001 and b["t"] + b["h"] <= 1.0001


def test_continuation_rows_are_exactly_the_linked_ones(sample_rows, records):
    idx = brk.brs.COLUMNS.index("continued_from")
    linked = {r[0] for r in sample_rows if r[idx]}
    assert {rec["sample_id"] for rec in records if rec["continuation"]} == linked
    for rec in records:
        if rec["continuation"]:
            assert rec["continuation"]["parent"]["entry_ref"] == rec["original"][idx]
            assert rec["continuation"]["evidence"]


def test_s345_is_flagged_but_not_reassigned(records):
    flagged = {rec["sample_id"]: rec["auto_flags"] for rec in records if rec["auto_flags"]}
    assert list(flagged) == ["S345"]
    (flag,) = flagged["S345"]
    assert flag["code"] == "continuation_bracket_contradiction"
    assert "not known" in flag["message"] and "not been reassigned" in flag["message"]
    s345 = next(r for r in records if r["sample_id"] == "S345")
    assert s345["entry"]["entry_ref"] == "p497-c1-orphan"
    assert s345["entry"]["continued_from"] == "p497-c0-e027"
    assert s345["continuation"]["parent"]["headword"] == "zétète"


def test_bracket_rule():
    child = {"continued_from": "x", "decoded_nko": "  ߊ )", "continuation_evidence": "reading_order"}
    assert brk.auto_flags(child, {"entry_ref": "x", "headword": "h", "decoded_nko": "ߊ"})
    assert not brk.auto_flags(child, {"entry_ref": "x", "headword": "h", "decoded_nko": "( ߊ"})
    assert not brk.auto_flags({**child, "decoded_nko": "ߊ"}, {"entry_ref": "x", "headword": "h", "decoded_nko": "ߊ"})


def test_cli_subset_builds_kit_and_leaves_inputs_untouched(tmp_path):
    before = {p: sha(p) for p in (TSV, DB, PDF)}
    out = tmp_path / "kit"
    res = subprocess.run([sys.executable, "-W", "ignore", str(SCRIPT), "--db", str(DB), "--only", "S345,S008", "--out", str(out)],
                         capture_output=True, text=True, encoding="utf-8")
    assert res.returncode == 0, res.stderr
    assert {p: sha(p) for p in before} == before
    for name in (*brk.VIEWER_FILES, "review_data.js", "kit_manifest.json"):
        assert (out / name).exists(), name
    manifest = json.loads((out / "kit_manifest.json").read_text(encoding="utf-8"))
    assert manifest["records"] == 2 and manifest["source"]["subset"] is True
    assert manifest["auto_flagged"] == ["S345"]
    pngs = sorted(p.name for p in (out / "crops").iterdir())
    assert "S345_parent.png" in pngs and "S008_line2.png" in pngs and len(pngs) == manifest["images"]
    # Same inputs, same kit.
    first = sha(out / "review_data.js")
    assert subprocess.run([sys.executable, "-W", "ignore", str(SCRIPT), "--db", str(DB), "--only", "S345,S008", "--out", str(out)],
                          capture_output=True).returncode == 0
    assert sha(out / "review_data.js") == first


@pytest.mark.parametrize("dest", ["scripts/review_kit_probe", "docs/review_kit_probe", "data", "data/backups/kit_probe"])
def test_cli_refuses_tracked_or_source_locations(dest):
    target = REPO_ROOT / dest
    existed = target.exists()
    res = subprocess.run([sys.executable, "-W", "ignore", str(SCRIPT), "--db", str(DB), "--only", "S001", "--out", str(target)],
                         capture_output=True, text=True)
    assert res.returncode != 0
    assert target.exists() == existed


def test_cli_refuses_foreign_directory(tmp_path):
    (tmp_path / "notes.txt").write_text("keep me", encoding="utf-8")
    res = subprocess.run([sys.executable, "-W", "ignore", str(SCRIPT), "--db", str(DB), "--only", "S001", "--out", str(tmp_path)],
                         capture_output=True, text=True)
    assert res.returncode != 0
    assert sorted(p.name for p in tmp_path.iterdir()) == ["notes.txt"]


def test_cli_refuses_a_database_the_sample_was_not_drawn_from(tmp_path):
    if not CURRENT_DB.exists() or CURRENT_DB.resolve() == DB.resolve():
        pytest.skip("the current database is the sample's own")
    res = subprocess.run([sys.executable, "-W", "ignore", str(SCRIPT), "--db", str(CURRENT_DB), "--only", "S001",
                          "--out", str(tmp_path / "kit")], capture_output=True, text=True, encoding="utf-8")
    assert res.returncode == 1 and "--db" in res.stderr
    assert not (tmp_path / "kit").exists()


# --- review_core.js (export / import), run under Node ----------------------

NODE = shutil.which("node")


def run_core(tmp_path, records, body: str):
    data = {"columns": list(brk.brs.COLUMNS), "extra_columns": list(brk.EXTRA_COLUMNS),
            "answers": list(brk.ANSWERS), "source": {}, "records": records}
    (tmp_path / "data.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    script = tmp_path / "run.js"
    script.write_text(
        "const fs = require('fs');\n"
        f"const core = require({json.dumps(str(CORE_JS))});\n"
        f"const data = JSON.parse(fs.readFileSync({json.dumps(str(tmp_path / 'data.json'))}, 'utf8'));\n"
        f"const out = (() => {{ {body} }})();\n"
        f"fs.writeFileSync({json.dumps(str(tmp_path / 'out.json'))}, JSON.stringify(out));\n",
        encoding="utf-8")
    res = subprocess.run([NODE, str(script)], capture_output=True, text=True)
    assert res.returncode == 0, res.stderr
    return json.loads((tmp_path / "out.json").read_text(encoding="utf-8"))


@pytest.mark.skipif(NODE is None, reason="node not installed")
def test_unreviewed_export_keeps_every_original_line_byte_for_byte(tmp_path, records):
    exported = run_core(tmp_path, records, "return core.exportTsv(data, {});")
    original = TSV.read_text(encoding="utf-8").split("\n")
    lines = exported.split("\n")
    assert len(lines) == len(original) and lines[-1] == original[-1] == ""
    for orig, new in zip(original[:-1], lines[:-1]):
        assert new.startswith(orig + "\t")
    rows = list(csv.reader(exported.splitlines(), delimiter="\t"))
    assert rows[0] == list(brk.brs.COLUMNS) + list(brk.EXTRA_COLUMNS)
    by_id = {r[0]: r for r in rows[1:]}
    assert by_id["S345"][19:] == ["", "continuation_bracket_contradiction", "", ""]
    assert by_id["S001"][19] == "n/a"


@pytest.mark.skipif(NODE is None, reason="node not installed")
def test_reviews_round_trip_and_tampering_is_rejected(tmp_path, records):
    notes = '  line 2:\t"tone" mark\nmissing  '
    reviews = {
        "S345": {"script": "yes", "segmentation": "uncertain", "continuation": "no", "notes": notes,
                 "reviewer": "AB", "updated_at": "2026-10-30T00:00:00Z"},
        "S001": {"script": "no", "segmentation": "yes", "notes": "", "reviewer": "AB", "updated_at": "t"},
    }
    out = run_core(tmp_path, records, f"""
        const reviews = {json.dumps(reviews, ensure_ascii=False)};
        const text = core.exportTsv(data, reviews);
        const back = core.importTsv(data, text);
        const rows = core.parseTsv(text);
        const di = data.columns.indexOf('decoded_nko');
        const tampered = rows.map((r, i) => i === 1 ? r.map((c, j) => j === di ? c.trim() + 'x' : c) : r)
            .map(r => r.map(core.tsvField).join('\\t')).join('\\n') + '\\n';
        const ci = rows[0].indexOf('review_continuation_ok');
        const badCont = rows.map((r, i) => r[0] === 'S001' ? r.map((c, j) => j === ci ? 'yes' : c) : r)
            .map(r => r.map(core.tsvField).join('\\t')).join('\\n') + '\\n';
        return {{ text, back, tampered: core.importTsv(data, tampered),
                  badCont: core.importTsv(data, badCont),
                  status: core.recordStatus(data.records.find(r => r.sample_id === 'S345'), reviews.S345),
                  status1: core.recordStatus(data.records.find(r => r.sample_id === 'S001'), reviews.S001),
                  summary: core.summarize(data, reviews) }};
    """)
    rows = {r[0]: r for r in csv.reader(out["text"].splitlines(keepends=True), delimiter="\t")}
    s345 = rows["S345"]
    assert s345[16:19] == ["yes", "uncertain", notes] and s345[19:21] == ["no", "continuation_bracket_contradiction"]
    assert out["back"]["errors"] == []
    for sid, r in reviews.items():
        got = out["back"]["reviews"][sid]
        for k in ("script", "segmentation", "notes", "reviewer", "updated_at"):
            assert got[k] == r[k]
        assert got["continuation"] == r.get("continuation", "")
    assert len(out["back"]["reviews"]) == 2
    assert out["tampered"]["errors"] and "S001" not in out["tampered"]["reviews"]
    assert out["badCont"]["errors"] and "S001" not in out["badCont"]["reviews"]
    assert out["status"] == out["status1"] == "complete"
    assert out["summary"]["E_structure"]["continuation"]["no"] == 1
    assert out["summary"]["A_random"]["script"]["no"] == 1
