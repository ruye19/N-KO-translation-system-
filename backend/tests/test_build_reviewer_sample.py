"""Tests for the stratified reviewer sample (scripts/build_reviewer_sample.py).

They read the generated data/dictionary_decoded.sqlite and are skipped, not
silently passed, when it is absent. Output only goes to pytest's tmp_path.
"""

import collections
import csv
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import build_reviewer_sample as brs  # noqa: E402

DB = REPO_ROOT / "data" / "dictionary_decoded.sqlite"

pytestmark = pytest.mark.skipif(not DB.exists(), reason=f"{DB} not present; run scripts/decode_dictionary.py")


@pytest.fixture(scope="module")
def corpus():
    rows, meta = brs.load_rows(DB)
    conn = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True)
    strong = [c for (c,) in conn.execute("SELECT codepoint FROM code_inventory WHERE handling = 'STRONG' ORDER BY codepoint")]
    candidate = [c for (c,) in conn.execute("SELECT codepoint FROM code_inventory WHERE handling = 'CANDIDATE' ORDER BY codepoint")]
    conn.close()
    return rows, meta, strong, candidate


@pytest.fixture(scope="module")
def sample(corpus):
    rows, _meta, strong, candidate = corpus
    return brs.build_sample(rows, strong, candidate, brs.DEFAULT_SEED)


def test_same_seed_same_sample(corpus, sample):
    rows, _meta, strong, candidate = corpus
    assert brs.build_sample(rows, strong, candidate, brs.DEFAULT_SEED) == sample
    other = brs.build_sample(rows, strong, candidate, brs.DEFAULT_SEED + 1)
    assert [s["entry_ref"] for s in other] != [s["entry_ref"] for s in sample]


def test_every_entry_appears_once(sample):
    refs = [s["entry_ref"] for s in sample]
    assert len(refs) == len(set(refs))


def test_random_stratum_is_strong_headwords_spread_over_page_bands(corpus, sample):
    rows = {r["entry_ref"]: r for r in corpus[0]}
    a = [s for s in sample if s["stratum"] == "A_random"]
    assert len(a) == brs.RANDOM_SIZE
    assert all(rows[s["entry_ref"]]["weakest_tier"] == "STRONG" and s["entry_kind"] == "headword" for s in a)
    bands = collections.Counter(s["reason"] for s in a)
    assert len(bands) == brs.PAGE_BANDS and set(bands.values()) == {brs.RANDOM_SIZE // brs.PAGE_BANDS}


def test_every_strong_code_is_covered_as_far_as_the_corpus_allows(corpus, sample):
    rows, _meta, strong, _candidate = corpus
    eligible = [r for r in rows if r["entry_kind"] != "orphan_lines" and r["line_count"] and r["weakest_tier"] == "STRONG"]
    available = collections.Counter(c for r in eligible for c in r["_codes"])
    coverage = brs.code_coverage(sample, rows, strong)
    for code, n in coverage.items():
        assert n >= min(brs.PER_CODE, available[int(code[2:], 16)]), code


def test_candidate_stratum_shows_placeholders_not_guesses(sample):
    d = [s for s in sample if s["stratum"] == "D_candidate"]
    assert d
    for s in d:
        assert s["reason"] in s["candidate_codes"].split()
        assert f"⟨{s['reason']}⟩" in s["decoded_nko"]


def test_review_columns_start_empty(sample):
    assert all(s["review_script_ok"] == s["review_segmentation_ok"] == s["review_notes"] == "" for s in sample)


def test_cli_writes_tsv_and_manifest_and_refuses_protected_paths(tmp_path):
    out = tmp_path / "sample.tsv"
    res = subprocess.run([sys.executable, str(REPO_ROOT / "scripts" / "build_reviewer_sample.py"), "--output", str(out)],
                         capture_output=True, text=True, encoding="utf-8")
    assert res.returncode == 0, res.stderr
    with out.open(encoding="utf-8") as f:
        assert tuple(next(csv.reader(f, delimiter="\t"))) == brs.COLUMNS
    manifest = json.loads(out.with_suffix(".manifest.json").read_text(encoding="utf-8"))
    assert manifest["seed"] == brs.DEFAULT_SEED and manifest["sample_size"] > brs.RANDOM_SIZE
    for protected in ("data/dictionary.sqlite", "docs/dictionary-decoding/reviewer_sample.tsv"):
        res = subprocess.run([sys.executable, str(REPO_ROOT / "scripts" / "build_reviewer_sample.py"),
                              "--output", str(REPO_ROOT / protected)], capture_output=True, text=True)
        assert res.returncode == 1
