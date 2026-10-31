"""Tests for the offline legacy N'Ko decoder (scripts/decode_dictionary.py).

Unit tests use short synthetic legacy-code sequences, so they need neither the
PDF nor any copyrighted dictionary text. Tests against the generated database
(data/dictionary_decoded.sqlite) and the PDF are skipped, not silently passed,
when those are absent.

None of these tests asserts that a decoding is linguistically correct: the
decoder's output is machine-decoded and unverified.
"""

import collections
import hashlib
import json
import shutil
import sqlite3
import subprocess
import sys
import unicodedata
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import decode_dictionary as dd  # noqa: E402

DOCS = REPO_ROOT / "docs" / "dictionary-decoding"
V1 = DOCS / "mapping_tiers.json"
V2 = DOCS / "mapping_tiers.v2.json"
DECODED_DB = REPO_ROOT / "data" / "dictionary_decoded.sqlite"
PDF = REPO_ROOT / "docs" / "dictionnaire Fr_nko.pdf"

# Hashes recorded in docs/dictionary-decoding/PROVENANCE.md.
V1_SHA256 = "b089c80a09023111c8ceae3c48ae93a872d21db8dcc8d84f6c241afac157489e"
PROTECTED = {
    REPO_ROOT / "docs" / "dictionnaire Fr_nko.pdf": "871628d99b9601cbdb9d797c54ffa81cad0f0ba1b4920de3aca64e3706be574b",
    REPO_ROOT / "data" / "dictionary.sqlite": "c01e64ffdd2e483afa4a662e6347087e2caa4c08c538dbeafb196b82cfc438ef",
    REPO_ROOT / "data" / "raw_extraction.jsonl": "676f6b3f1eeca0fb90dd3ac1b2fa5069f9c53b0070f470ab170a26f99676f3c0",
}

# Legacy codes as extracted from the PDF (U+F100 + legacy byte).
SPACE, WA_TAIL = 0xF120, 0xF178
KA, A_MEDIAL, A_FINAL, I, JA, MA, DA, U = 0xF16A, 0xF142, 0xF1AC, 0xF149, 0xF14B, 0xF152, 0xF160, 0xF161
LOW, HIGH, LONG_HIGH, NASAL, LOW_NASAL = 0xF1C4, 0xF1C6, 0xF1CA, 0xF1C9, 0xF1CC
CANDIDATE_RRA = 0xF148           # candidate tier: must never be decoded
KOUFI_ONLY = 0xF146              # known unresolved
NEVER_SEEN = 0xF1FF              # not in any table


@pytest.fixture(scope="module")
def mapping():
    return dd.load_mapping(V2)


def nfc(s):
    return unicodedata.normalize("NFC", s)


# ---------------------------------------------------------------------------
# Corrected evidence file
# ---------------------------------------------------------------------------

def test_preserved_v1_mapping_is_unchanged():
    assert hashlib.sha256(V1.read_bytes()).hexdigest() == V1_SHA256


def test_v2_counts_distinguish_font_codes_digits_and_tiers(mapping):
    data = json.loads(V2.read_text(encoding="utf-8"))
    kinds = [c["kind"] for c in data["codes"].values()]
    tiers = [c["tier"] for c in data["codes"].values()]
    assert kinds.count("font_code") == 91
    assert kinds.count("digit_codepoint") == 10
    assert tiers.count("STRONG") == 94
    assert tiers.count("CANDIDATE") == 7
    assert data["counts"] == {**data["counts"], "font_codes": 91, "digit_codepoints": 10, "strong": 94, "candidate": 7}
    assert data["derived_from"]["sha256"] == V1_SHA256


def test_v2_candidate_counts_are_the_audited_body_counts():
    data = json.loads(V2.read_text(encoding="utf-8"))
    got = {k: v["body_occurrences"] for k, v in data["codes"].items() if v["tier"] == "CANDIDATE"}
    assert got == {"U+F148": 51, "U+F156": 1, "U+F157": 2, "U+F159": 1, "U+F15F": 100, "U+F166": 1, "U+F177": 141}


def test_v2_does_not_claim_arabic_semicolon_or_question_mark_as_confirmed():
    data = json.loads(V2.read_text(encoding="utf-8"))
    for cp in ("U+061B", "U+061F"):
        assert cp not in data["codes"], f"{cp} must not be a decoded mapping"
        entry = data["passthrough"][cp]
        assert entry["output"] == chr(int(cp[2:], 16)), "kept as-is, not converted"
        assert "UNVERIFIED" in entry["evidence"] and "NOT confirmed" in entry["evidence"]


def test_v2_never_maps_to_private_use_or_marks_anything_verified(mapping):
    for info in mapping.codes.values():
        assert not any(dd.is_pua(ch) for ch in info["unicode"])
    text = V2.read_text(encoding="utf-8").lower()
    assert '"verified"' not in text and "human_verified" not in text


# ---------------------------------------------------------------------------
# Decoding
# ---------------------------------------------------------------------------

def test_strong_tier_decoding(mapping):
    # ߞߊ߲߬ߖߊ߬ߡߊ߯ߘߌ߫ in legacy codes, logical order, marks after their base.
    codes = [KA, A_MEDIAL, NASAL, LOW, JA, A_MEDIAL, LOW, MA, A_MEDIAL, LONG_HIGH, DA, I, HIGH]
    line = dd.decode_line(codes, mapping)
    assert line.text == nfc("ߞߊ߲߬ߖߊ߬ߡߊ߯ߘߌ߫")
    assert not line.candidate_codes and not line.unresolved_codes
    assert dd.weakest_tier([line]) == "STRONG"


def test_candidate_code_stays_a_visible_placeholder(mapping):
    line = dd.decode_line([KA, A_MEDIAL, CANDIDATE_RRA, I], mapping)
    assert "⟨U+F148⟩" in line.text
    assert "ߚ" not in line.text, "the candidate guess (ߚ) must never be emitted"
    assert line.candidate_codes == {CANDIDATE_RRA}
    assert dd.weakest_tier([line]) == "CANDIDATE"


@pytest.mark.parametrize("code", [KOUFI_ONLY, NEVER_SEEN, 0x0041])
def test_unknown_codes_are_kept_not_dropped(mapping, code):
    codes = [KA, code, A_FINAL]
    line = dd.decode_line(codes, mapping)
    assert f"⟨U+{code:04X}⟩" in line.text
    assert line.unresolved_codes == {code}
    assert len(line.alignment) == len(codes)
    assert dd.weakest_tier([line]) == "UNRESOLVED"


def test_composite_mark_expands_to_two_unicode_marks(mapping):
    line = dd.decode_line([MA, A_MEDIAL, LOW_NASAL], mapping)
    assert line.text == nfc("ߡߊ߲߬")
    assert {t["rule"] for t in line.transformations} == {"composite_mark_expanded"}


def test_wa_tail_spacer_is_removed_only_before_a_letter(mapping):
    joined = dd.decode_line([WA_TAIL, SPACE, U], mapping)
    assert joined.text == "ߥߎ"
    assert joined.transformations == [{"line": 0, "index": 1, "rule": "wa_tail_spacer_removed"}]
    assert dd.decode_line([WA_TAIL, SPACE, 0x002E], mapping).text == "ߥ ."
    # At the end of a line the space is a trailing layout space (v1.2), not the tail's spacer.
    end = dd.decode_line([WA_TAIL, SPACE], mapping)
    assert end.text == "ߥ" and [t["rule"] for t in end.transformations] == ["trailing_layout_space_removed"]
    assert dd.decode_line([KA, SPACE, U], mapping).text == "ߞ ߎ"


def test_brackets_are_mirrored_for_logical_order(mapping):
    line = dd.decode_line([0x0029, KA, A_FINAL, 0x0028], mapping)
    assert line.text == "(ߞߊ)"


def test_arabic_punctuation_passes_through_unchanged(mapping):
    line = dd.decode_line([KA, 0x060C, KA, 0x061B, KA, 0x061F], mapping)
    assert line.text == "ߞ،ߞ؛ߞ؟"


# ---------------------------------------------------------------------------
# Ordering
# ---------------------------------------------------------------------------

def test_reading_order_is_reversed_and_base_precedes_its_mark():
    marks = {LOW}
    # Visual left-to-right stream: [ߊ at x=5] [mark, base ߞ both at x=10]
    visual = [(5.0, A_FINAL), (10.0, LOW), (10.0, KA)]
    assert dd.order_line(visual, marks) == [KA, LOW, A_FINAL]


def test_mark_order_does_not_depend_on_stream_order():
    marks = {LOW}
    a = dd.order_line([(10.0, LOW), (10.0, KA), (4.0, A_FINAL)], marks)
    b = dd.order_line([(4.0, A_FINAL), (10.0, KA), (10.0, LOW)], marks)
    assert a == b == [KA, LOW, A_FINAL]


def test_digits_come_out_most_significant_first(mapping):
    # Visually "13" in N'Ko reads right-to-left: ߃ at the left, ߁ at the right.
    logical = dd.order_line([(5.0, 0x0663), (9.0, 0x0661)], set())
    assert dd.decode_line(logical, mapping).text == "߁߃"


# ---------------------------------------------------------------------------
# Round trip, loss, PUA
# ---------------------------------------------------------------------------

MIXED = [WA_TAIL, SPACE, U, LOW_NASAL, 0x0029, CANDIDATE_RRA, NEVER_SEEN, SPACE, 0x0660, 0x0028, 0xF1C5, KA]


def test_round_trip_rebuilds_original_codes_and_text(mapping):
    line = dd.decode_line(MIXED, mapping)
    assert dd.rebuild_codes(line.alignment) == MIXED
    assert dd.rebuild_text(line.alignment) == line.text


def test_every_input_code_has_exactly_one_alignment_item(mapping):
    line = dd.decode_line(MIXED, mapping)
    assert [cp for cp, _ in line.alignment] == MIXED
    unknown = {CANDIDATE_RRA, NEVER_SEEN}
    assert unknown <= line.candidate_codes | line.unresolved_codes


def test_no_private_use_characters_in_any_decoded_output(mapping):
    every = list(mapping.codes) + list(mapping.passthrough) + [KOUFI_ONLY, NEVER_SEEN, 0xE000, 0xF8FF]
    line = dd.decode_line(every, mapping)
    assert not [hex(ord(c)) for c in line.text if dd.is_pua(c)]


# ---------------------------------------------------------------------------
# Spacing (v1.2)
# ---------------------------------------------------------------------------

def gap(width, after=KA, unit=2.5):
    return {"gap": width, "unit": unit, "after": after}


def rules(line):
    return [t["rule"] for t in line.transformations]


def test_positioned_gap_between_words_becomes_one_space(mapping):
    # "word ߕ. word": the typesetter moved the pen one space advance, no glyph in between.
    line = dd.decode_line([KA, A_MEDIAL, U, 0x002E, MA, A_FINAL], mapping, gaps={2: gap(2.5), 4: gap(2.52, after=0x002E)})
    assert line.text == "ߞߊ ߎ. ߡߊ"
    assert rules(line) == ["positioned_space_inserted", "positioned_space_inserted"]
    assert [t["gap_pt"] for t in line.transformations] == [2.5, 2.52]


def test_label_sized_gap_counts_as_a_space(mapping):
    # One space at the 12 pt label size is 2.0 pt.
    assert dd.decode_line([KA, U], mapping, gaps={1: gap(2.0)}).text == "ߞ ߎ"


def test_double_width_gap_becomes_two_spaces(mapping):
    line = dd.decode_line([KA, U], mapping, gaps={1: gap(5.0)})
    assert line.text == "ߞ  ߎ" and line.transformations[0]["spaces"] == 2


@pytest.mark.parametrize("width,rule", [(1.4, "narrow_gap_not_spaced"), (27.0, "wide_gap_not_spaced")])
def test_gaps_outside_the_space_range_are_recorded_but_not_spaced(mapping, width, rule):
    line = dd.decode_line([KA, U], mapping, gaps={1: gap(width)})
    assert line.text == "ߞߎ" and rules(line) == [rule]


def test_gap_after_wa_before_a_letter_is_the_tail_not_a_space(mapping):
    # Same situation as wa_tail_spacer_removed, without a spacer glyph.
    line = dd.decode_line([WA_TAIL, U], mapping, gaps={1: gap(2.5, after=WA_TAIL)})
    assert line.text == "ߥߎ" and rules(line) == ["wa_tail_gap_not_a_space"]
    # A gap wider than the tail's slot still leaves a real space.
    wide = dd.decode_line([WA_TAIL, U], mapping, gaps={1: gap(5.0, after=WA_TAIL)})
    assert wide.text == "ߥ ߎ" and rules(wide) == ["positioned_space_inserted"]
    # Before punctuation the gap is kept, as the spacer glyph is.
    assert dd.decode_line([WA_TAIL, 0x002E], mapping, gaps={1: gap(2.5, after=WA_TAIL)}).text == "ߥ ."


def test_layout_spaces_at_line_edges_are_removed_and_recorded(mapping):
    line = dd.decode_line([SPACE, SPACE, KA, SPACE, U, SPACE], mapping)
    assert line.text == "ߞ ߎ"
    assert rules(line) == ["leading_layout_space_removed"] * 2 + ["trailing_layout_space_removed"]
    assert dd.rebuild_codes(line.alignment) == [SPACE, SPACE, KA, SPACE, U, SPACE]


def test_inner_spaces_and_all_space_lines_are_kept(mapping):
    assert dd.decode_line([KA, SPACE, SPACE, U], mapping).text == "ߞ  ߎ"   # printed double space
    blank = dd.decode_line([SPACE, SPACE], mapping)
    assert blank.text == "  " and blank.transformations == []


def test_inserted_spaces_round_trip_without_inventing_codes(mapping):
    codes = [SPACE, KA, A_MEDIAL, U, LOW, MA, SPACE]
    line = dd.decode_line(codes, mapping, gaps={3: gap(2.5)})
    assert [None, " "] in line.alignment
    assert dd.rebuild_codes(line.alignment) == codes
    assert dd.rebuild_text(line.alignment) == line.text == nfc("ߞߊ ߎ߬ߡ")
    assert line.text.replace(" ", "") == dd.decode_line(codes, mapping).text.replace(" ", "")


def test_positioned_gaps_measure_visual_gaps_in_logical_order():
    # Visual left-to-right: U | gap | KA LOW(mark) | SPACE | MA.  Logical: MA, SPACE, KA, LOW, U.
    marks = {LOW}
    glyphs = [(100.0, U, 6.0, 15.0), (108.5, KA, 5.0, 15.0), (108.5, LOW, 0.0, 15.0),
              (113.5, SPACE, 2.5, 15.0), (116.0, MA, 6.6, 15.0)]
    assert dd.order_line([(x, cp) for x, cp, _w, _s in glyphs], marks) == [MA, SPACE, KA, LOW, U]
    # Only the U|KA gap is reported (the space glyph needs nothing), before U at logical index 4.
    assert dd.positioned_gaps(glyphs, marks) == {4: {"gap": 2.5, "unit": 2.5, "after": KA}}


def test_group_lines_measures_gaps_only_when_widths_are_known():
    measured = dd.group_lines([(100.0, 50.0, U, 6.0, 15.0), (108.5, 50.0, KA, 5.0, 15.0)], set())
    assert measured[0].gaps == {1: {"gap": 2.5, "unit": 2.5, "after": KA}}
    y, codes, extent = measured[0]                     # still unpacks as before
    assert (y, codes, extent) == (50.0, [KA, U], (100.0, 108.5))
    assert dd.group_lines([(100.0, 50.0, U), (108.5, 50.0, KA)], set())[0].gaps == {}


def test_segmentation_carries_gaps_into_the_decoded_row(mapping):
    spans = [(0, 100.0, 106.0, "abaca")]
    glyphs = [(200.0, 100.0, U, "Manden", 6.0, 15.0), (208.5, 100.0, A_FINAL, "Manden", 3.0, 15.0),
              (211.5, 100.0, KA, "Manden", 5.0, 15.0)]
    (entry,) = dd.segment_page(dd.PageData(41, glyphs, spans), set())
    row = dd.build_row(entry, mapping, "x")
    assert row["decoded_nko"] == "ߞߊ ߎ"
    assert json.loads(row["legacy_codes"]) == [[KA, A_FINAL, U]]
    assert [t["rule"] for t in json.loads(row["transformations"])] == ["positioned_space_inserted"]


def test_wide_gap_rows_are_flagged(mapping):
    row = row_for(mapping, 41, 0, 0, "headword", [[KA, U]], 100.0)
    row["transformations"] = json.dumps([{"line": 0, "index": 1, "rule": "wide_gap_not_spaced", "gap_pt": 30.0}])
    dd.assign_flags([row])
    assert "wide_gap_not_spaced" in json.loads(row["flags"])


# ---------------------------------------------------------------------------
# Alphabet-position check
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("ߡ ߝߊ߬ߙߊ߲߬ߛߌ߬ߞߊ߲ ߛߓߍߛߎ߲ ߛߓߍߘߋ߲ ߁߃߲", 13),
    ("ߣ ) ߛߓߍߘߋ߲߫ ߁߄ߣߊ߲ (", 14),
    ("ߖߕ.ߝߊ߬ߙߊ߲߬ߛߌ߬ߞߊ߲ ߛߓߍߘߋ߲߫ ߇߲", 7),
    ("ߞ ߛߓߍߘߋ߲߫ ߁߇ ߣߊ߲", 17),                 # suffix set after a printed gap
    ("ߞ ߛߓߍߘߋ߲߫ ߁߇  ߣߊ߲", None),              # but not across a wider break
    ("ߝ߭߁، ߝ߭߂) ߊߟߌߡߊ߲", None),  # sub-sense numbering, not an ordinal
])
def test_alphabet_ordinal(text, expected):
    assert dd.alphabet_ordinal(text) == expected


def test_alphabet_check_flags_a_wrong_ordinal():
    row = {"entry_ref": "p999-c0-e000", "entry_kind": "headword", "headword": "m",
           "decoded_nko": "ߡ ߛߓߍߘߋ߲ ߁߄߲"}
    (check,) = dd.alphabet_checks([row])
    assert check["ordinal"] == 14 and check["alphabet_position"] == 13 and not check["ok"]


# ---------------------------------------------------------------------------
# Rows, references, validation, storage
# ---------------------------------------------------------------------------

def make_entry(lines, headword="teckel", page=452, column=0, index=3):
    return dd.RawEntry(page, column, index, "headword", headword, 147.0,
                       [(147.0 + 14 * i, codes, (200.0, 280.0)) for i, codes in enumerate(lines)])


def test_row_preserves_source_page_and_entry_reference(mapping):
    row = dd.build_row(make_entry([[KA, A_FINAL]]), mapping, "pdfsha")
    dd.assign_links([row], {(452, "teckel"): [(28927, 1)]})
    assert row["entry_ref"] == "p452-c0-e003"
    assert (row["page_number"], row["column_index"], row["entry_index"]) == (452, 0, 3)
    assert row["headword"] == "teckel" and row["headword_normalized"] == "teckel"
    assert json.loads(row["dictionary_entry_ids"]) == [28927] and row["link_status"] == "unique"
    assert row["status"] == "machine_decoded"
    assert row["mapping_sha256"] == mapping.sha256 and row["source_pdf_sha256"] == "pdfsha"


def test_orphan_lines_get_their_own_reference(mapping):
    entry = dd.RawEntry(264, 1, -1, "orphan_lines", "", None, [(90.0, [KA, A_FINAL], (300.0, 480.0))])
    row = dd.build_row(entry, mapping, "x")
    assert row["entry_ref"] == "p264-c1-orphan" and row["link_status"] == "not_checked"


def synthetic_page():
    spans = [
        (0, 77.6, 105.0, "425"),          # page number in the header band
        (0, 82.0, 105.0, "afftanchir"),   # first entry on an early page (baseline 82)
        (0, 96.0, 115.0, "technologiste"),  # indented continuation, not a headword
        (0, 110.0, 105.2, "affublement"),
        (1, 82.0, 307.0, "africanisation"),
    ]
    glyphs = [
        (60.0, 75.0, SPACE, "Manden"),     # blank glyph in the header band
        (280.0, 82.0, KA, "Manden"), (275.0, 82.0, A_FINAL, "Manden"),
        (280.0, 110.0, MA, "Manden"), (275.0, 110.0, A_FINAL, "Koufi"),
        (480.0, 82.0, DA, "Manden"),
    ]
    return dd.PageData(30, glyphs, spans)


def test_headwords_use_each_columns_own_margin():
    heads = dd.page_headwords(synthetic_page(), "page_margins")
    assert [t for _c, _y, t in heads] == ["afftanchir", "affublement", "africanisation"]


def test_audit_v1_segmentation_is_kept_for_regression_only():
    # The audit's fixed margins miss x=105/307 pages entirely.
    assert dd.page_headwords(synthetic_page(), "audit_v1") == []


def test_segmentation_attaches_lines_and_keeps_koufi_glyphs(mapping):
    entries = dd.segment_page(synthetic_page(), set(), "page_margins")
    by_ref = {e.ref: e for e in entries}
    assert by_ref["p030-c0-e000"].lines[0][1] == [KA, A_FINAL]
    assert by_ref["p030-c0-e001"].lines[0][1] == [MA, A_FINAL]      # Koufi glyph kept
    assert by_ref["p030-c1-e000"].lines[0][1] == [DA]
    _body, excluded = dd.page_body_glyphs(synthetic_page(), "page_margins")
    assert excluded == {SPACE: 1}


def test_headword_normalisation_matches_the_existing_extractor():
    from extract_dictionary import normalize_headword

    for h in ("mental,e,aux ", "Teint,e ", "  menteur,euse ", "a"):
        assert dd.normalize_headword(h) == normalize_headword(h)


def test_validation_accepts_clean_rows(mapping):
    row = dd.build_row(make_entry([MIXED, [KA, A_FINAL, HIGH]]), mapping, "x")
    dd.validate([row])


@pytest.mark.parametrize("tamper", ["codes", "pua", "status", "hidden_candidate"])
def test_validation_rejects_broken_rows(mapping, tamper):
    row = dd.build_row(make_entry([[KA, CANDIDATE_RRA, A_FINAL]]), mapping, "x")
    if tamper == "codes":
        row["legacy_codes"] = json.dumps([[KA, A_FINAL]])
    elif tamper == "pua":
        row["decoded_nko"] += ""
    elif tamper == "status":
        row["status"] = "verified"
    else:
        row["decoded_nko"] = row["decoded_nko"].replace("⟨U+F148⟩", "ߚ")
    with pytest.raises(ValueError):
        dd.validate([row])


def test_database_refuses_any_status_but_machine_decoded(mapping, tmp_path):
    row = dd.build_row(make_entry([[KA, A_FINAL]]), mapping, "x")
    out = tmp_path / "d.sqlite"
    dd.write_database(out, [row], [], {"tool": dd.TOOL_NAME})
    conn = sqlite3.connect(out)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE decoded_entries SET status = 'verified'")
    conn.close()


def test_output_guard_refuses_source_files_and_foreign_databases(tmp_path):
    for protected in PROTECTED:
        with pytest.raises(SystemExit):
            dd.check_output_path(protected)
    foreign = tmp_path / "other.sqlite"
    sqlite3.connect(foreign).close()
    with pytest.raises(SystemExit):
        dd.check_output_path(foreign)


def test_write_is_deterministic(mapping, tmp_path):
    rows = [dd.build_row(make_entry([MIXED], index=i), mapping, "x") for i in range(3)]
    d1 = dd.write_database(tmp_path / "a.sqlite", rows, [("U+F16A", "STRONG", "letter", "ߞ", 3)], {"tool": dd.TOOL_NAME})
    d2 = dd.write_database(tmp_path / "b.sqlite", list(reversed(rows)), [("U+F16A", "STRONG", "letter", "ߞ", 3)], {"tool": dd.TOOL_NAME})
    assert d1 == d2


# ---------------------------------------------------------------------------
# Segmentation: margins, wrapped headwords, sub-entries
# ---------------------------------------------------------------------------

def test_column_margin_uses_the_most_common_left_edge():
    # p.117: one entry ("de") sits 2 pt left of the headwords at x=310.
    assert dd.column_margin([308.0] + [310.0] * 30 + [317.0] * 3) == 310.0
    assert dd.column_margin([106.0, 106.0, 115.0, 115.0]) == 106.0  # ties -> leftmost
    # More indented lines than headwords must not move the margin to the indent.
    assert dd.column_margin([106.0, 106.0, 113.0, 113.0, 113.0]) == 106.0


@pytest.mark.parametrize("lines,expected", [
    (["abreuvage ou ", "abreuvement"], "abreuvage ou abreuvement"),
    (["anticonstitutionne", "l,elle "], "anticonstitutionnel,elle"),
    (["antigouvernemental,", "e,aux "], "antigouvernemental,e,aux"),
    (["arrière-grands-", "parents"], "arrière-grands-parents"),
    (["déterminer un lieu en ", "latitude"], "déterminer un lieu en latitude"),
])
def test_join_headword_lines_respects_the_raw_line_break(lines, expected):
    assert dd.join_headword_lines(lines) == expected


@pytest.mark.parametrize("last,has_pos,width,nxt,source,expected", [
    ("abreuvage ou ", False, 60, "abreuvement", None, "wrapped_unconfirmed"),
    ("arrière-grands-", False, 70, "parents", None, "wrapped_unconfirmed"),
    ("anticonstitutionne", False, 83, "l,elle ", None, "wrapped_unconfirmed"),
    ("aéroporté", False, 61, "aérotranporté,e", None, None),           # short whole word
    ("télé", True, 20, "television ", None, None),                     # has a POS label
    ("adverbe", False, 40, "- de lieu", None, None),                   # sub-entry marker
    ("technologue ou ", False, 70, "technologiste", {"technologue ou technologiste"}, "wrapped_confirmed"),
])
def test_wrap_decision(last, has_pos, width, nxt, source, expected):
    joined = dd.join_headword_lines([last, nxt])
    assert dd.wrap_decision(last, has_pos, width, nxt, joined, source) == expected


@pytest.mark.parametrize("raw,has_pos,expected", [
    ("antisémite", True, True),            # headword set off its margin
    ("branler ", True, True),
    ("antisémite", False, False),          # no POS label: not enough evidence
    ("- à coudre", True, False),           # sub-entry marker
    ("avoir une jolie -", True, False),    # dash stands for the headword
    ("s’- de,", True, False),
    ("prendre un air –", True, False),
    ("arrière-plan", True, True),          # a hyphen inside a word is not a placeholder
])
def test_is_indented_headword(raw, has_pos, expected):
    assert dd.is_indented_headword(raw, has_pos) is expected


def wrap_page():
    spans = [
        (0, 100.0, 106.0, "abreuvage ou "),   # no POS: wraps onto the next line
        (0, 114.0, 113.0, "abreuvement"),
        (0, 128.0, 106.0, "adverbe"),          # has a POS label
        (0, 142.0, 113.0, "- de lieu"),
        (0, 156.0, 113.0, "- de temps "),
    ]
    glyphs = [(250.0, y, cp, "Manden") for y, cp in ((100.0, KA), (114.0, MA), (128.0, DA), (142.0, I), (156.0, U))]
    return dd.PageData(40, glyphs, spans, pos_baselines={(0, 114.0), (0, 128.0)})


def test_wrapped_headword_keeps_both_lines_and_all_its_nko(mapping):
    entries = {e.ref: e for e in dd.segment_page(wrap_page(), set())}
    head = entries["p040-c0-e000"]
    assert head.headword == "abreuvage ou abreuvement"
    assert head.headword_join == "wrapped_unconfirmed"
    assert [raw for _y, raw in head.headword_lines] == ["abreuvage ou ", "abreuvement"]
    assert [codes for _y, codes, _x in head.lines] == [[KA], [MA]]


def test_subentries_get_their_own_nko_window_and_parent(mapping):
    entries = {e.ref: e for e in dd.segment_page(wrap_page(), set())}
    assert [codes for _y, codes, _x in entries["p040-c0-e001"].lines] == [[DA]]
    sub1, sub2 = entries["p040-c0-e001-s01"], entries["p040-c0-e001-s02"]
    assert (sub1.kind, sub1.parent_ref, sub1.headword) == ("subentry", "p040-c0-e001", "- de lieu")
    assert [codes for _y, codes, _x in sub1.lines] == [[I]]
    assert [codes for _y, codes, _x in sub2.lines] == [[U]]


# ---------------------------------------------------------------------------
# Continuations, links, flags
# ---------------------------------------------------------------------------

def row_for(mapping, ref_page, col, index, kind, nko_codes, baseline, french=False, headword="x"):
    lines = [(baseline + 14 * i, codes, (200.0, 280.0)) for i, codes in enumerate(nko_codes)]
    entry = dd.RawEntry(ref_page, col, index, kind, headword if kind != "orphan_lines" else "",
                        None if kind == "orphan_lines" else baseline, lines,
                        headword_lines=[] if kind == "orphan_lines" else [(baseline, headword)],
                        french_on_baseline=french)
    return dd.build_row(entry, mapping, "x")


def test_column_top_text_links_to_the_previous_entry(mapping):
    prev = row_for(mapping, 24, 0, 30, "headword", [[KA, 0x0029]], 660.0)   # leaves '(' open (mirrored)
    orphan = row_for(mapping, 24, 1, -1, "orphan_lines", [[0x0028, A_FINAL]], 90.0)
    rows = [orphan, prev]
    dd.assign_continuations(rows)
    assert orphan["continued_from"] == "p024-c0-e030"
    assert orphan["continuation_evidence"] == "bracket_balance"
    assert json.loads(prev["continued_by"]) == ["p024-c1-orphan"]
    assert prev["decoded_nko"] == "ߞ(", "nothing is merged into the previous entry"


def test_continuation_crosses_pages_and_reports_weak_evidence(mapping):
    prev = row_for(mapping, 50, 1, 30, "headword", [[KA]], 660.0)
    orphan = row_for(mapping, 51, 0, -1, "orphan_lines", [[MA, A_FINAL]], 90.0)
    dd.assign_continuations([orphan, prev])
    assert (orphan["continued_from"], orphan["continuation_evidence"]) == ("p050-c1-e030", "reading_order")


@pytest.mark.parametrize("codes,french,evidence", [
    ([[SPACE]], False, "blank"),
    ([[KA, A_FINAL]], True, "french_text_on_baseline"),
])
def test_unsafe_continuations_are_not_linked(mapping, codes, french, evidence):
    prev = row_for(mapping, 24, 0, 30, "headword", [[KA]], 660.0)
    orphan = row_for(mapping, 24, 1, -1, "orphan_lines", codes, 90.0, french=french)
    dd.assign_continuations([prev, orphan])
    assert orphan["continued_from"] is None and orphan["continuation_evidence"] == evidence
    assert json.loads(prev["continued_by"]) == []


def test_link_statuses(mapping):
    source = {
        (22, "abattement"): [(18, 1), (19, 2)],          # one headword, two senses
        (22, "abonnement"): [(64, 1), (66, 1)],          # repeated on the page
        (22, "absent"): [(103, 1), (104, 1), (105, 1)],  # three occurrences, two decoded rows
        (22, "abbé"): [(10, 1)],
    }
    rows = [row_for(mapping, 22, 0, i, "headword", [[KA]], 100.0 + 14 * i, headword=h)
            for i, h in enumerate(["abattement", "abonnement", "abonnement", "absent", "absent", "abbé", "abattoir"])]
    dd.assign_links(rows, source)
    got = [(r["headword"], r["link_status"], json.loads(r["dictionary_entry_ids"])) for r in rows]
    assert got == [
        ("abattement", "senses", [18, 19]),
        ("abonnement", "paired_by_order", [64]),
        ("abonnement", "paired_by_order", [66]),
        ("absent", "ambiguous", [103, 104, 105]),
        ("absent", "ambiguous", [103, 104, 105]),
        ("abbé", "unique", [10]),
        ("abattoir", "none", []),
    ]


def test_wrapped_headword_links_through_one_of_its_lines(mapping):
    row = row_for(mapping, 23, 0, 12, "headword", [[KA]], 262.0, headword="abreuvage ou abreuvement")
    row["headword_join"] = "wrapped_unconfirmed"
    row["headword_lines"] = json.dumps([[262.0, "abreuvage ou "], [276.0, "abreuvement"]])
    dd.assign_links([row], {(23, "abreuvement"): [(77, 1)]})
    dd.assign_flags([row])
    assert (row["link_status"], json.loads(row["dictionary_entry_ids"])) == ("unique", [77])
    assert "linked_via_headword_line" in json.loads(row["flags"])


def test_flags_mark_layout_artifacts(mapping):
    caps = row_for(mapping, 31, 0, 16, "headword", [], 600.0, headword="AGRES")
    dash = row_for(mapping, 177, 0, 12, "headword", [[KA]], 300.0, headword="-")
    dd.assign_links([caps, dash], {})
    dd.assign_flags([caps, dash])
    assert json.loads(caps["flags"]) == ["caps_catchword", "no_nko", "headword_not_in_source"]
    assert json.loads(dash["flags"]) == ["non_alphabetic_headword", "headword_not_in_source"]


def test_generated_database_path_is_git_ignored():
    if shutil.which("git") is None:
        pytest.skip("git not available")
    res = subprocess.run(["git", "check-ignore", "-q", "data/dictionary_decoded.sqlite"], cwd=REPO_ROOT)
    assert res.returncode == 0, "data/dictionary_decoded.sqlite must stay out of Git"


# ---------------------------------------------------------------------------
# Generated database: regression against the audited results
# ---------------------------------------------------------------------------

needs_db = pytest.mark.skipif(not DECODED_DB.exists(),
                              reason=f"{DECODED_DB} not present; run: python scripts/decode_dictionary.py")


@pytest.fixture(scope="module")
def db():
    conn = sqlite3.connect(f"file:{DECODED_DB.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


def meta(db, key):
    return db.execute("SELECT value FROM decode_metadata WHERE key = ?", (key,)).fetchone()[0]


@needs_db
def test_audited_coverage_reproduces_under_the_audit_segmentation(db):
    # The audit's 99.13% used a fixed-margin headword heuristic; the build
    # re-segments the same pages that way and records the result.
    # Coverage of the mapping, NOT a measure of linguistic accuracy.
    audit = json.loads(meta(db, "audit_v1_regression"))
    assert audit["headword_entries_with_nko"] == 21627
    assert audit["entries_by_weakest_tier"] == {"STRONG": 21439, "CANDIDATE": 188}
    assert round(100 * audit["strong_entry_coverage"], 2) == 99.13


@needs_db
def test_decoder_coverage_regression(db):
    # Pins the decoder's own segmentation (v1.1). Mapping coverage only.
    rows = db.execute("""SELECT weakest_tier, COUNT(*) FROM decoded_entries
                         WHERE entry_kind = 'headword' AND line_count > 0 GROUP BY weakest_tier""").fetchall()
    assert dict((r[0], r[1]) for r in rows) == {"STRONG": 31506, "CANDIDATE": 247, "UNRESOLVED": 2}
    kinds = dict(db.execute("SELECT entry_kind, COUNT(*) FROM decoded_entries GROUP BY entry_kind").fetchall())
    assert kinds == {"headword": 31887, "subentry": 862, "orphan_lines": 116}


@needs_db
def test_no_glyph_is_lost_by_segmentation(db):
    # Every legacy glyph in the body lands in exactly one row, whatever the segmentation.
    total = db.execute("SELECT SUM(occurrences) FROM code_inventory").fetchone()[0]
    assert total == 547655 + 112437 + 297 + 2
    in_rows = sum(len(line) for (codes,) in db.execute("SELECT legacy_codes FROM decoded_entries")
                  for line in json.loads(codes))
    assert in_rows == total


@needs_db
def test_continuations_are_consistent_and_never_guessed(db):
    rows = {r["entry_ref"]: r for r in db.execute(
        "SELECT entry_ref, entry_kind, parent_entry_ref, continued_from, continuation_evidence, continued_by, decoded_nko "
        "FROM decoded_entries")}
    for ref, r in rows.items():
        if r["continued_from"]:
            assert r["continuation_evidence"] in ("bracket_balance", "reading_order")
            assert ref in json.loads(rows[r["continued_from"]]["continued_by"])
        for child in json.loads(r["continued_by"]):
            assert rows[child]["continued_from"] == ref
        if r["continuation_evidence"] in ("blank", "french_text_on_baseline", "no_previous_entry"):
            assert r["continued_from"] is None
    orphans = [r for r in rows.values() if r["entry_kind"] == "orphan_lines"]
    assert all(r["continued_from"] or r["continuation_evidence"] != "reading_order" for r in orphans)


@needs_db
def test_subentries_point_at_existing_headwords(db):
    refs = {r[0]: r[1] for r in db.execute("SELECT entry_ref, entry_kind FROM decoded_entries")}
    for ref, parent in db.execute("SELECT entry_ref, parent_entry_ref FROM decoded_entries WHERE entry_kind = 'subentry'"):
        assert parent is None or refs[parent] == "headword", ref


@needs_db
def test_wrapped_headwords_keep_every_raw_line(db):
    for hw, lines, join in db.execute(
            "SELECT headword, headword_lines, headword_join FROM decoded_entries WHERE headword_join LIKE 'wrapped%'"):
        raw = [t for _y, t in json.loads(lines)]
        assert len(raw) >= 2
        assert dd.join_headword_lines(raw) == hw


@needs_db
def test_link_status_distribution(db):
    got = dict(db.execute("SELECT link_status, COUNT(*) FROM decoded_entries "
                          "WHERE entry_kind = 'headword' GROUP BY link_status").fetchall())
    assert got == {"unique": 27362, "senses": 1546, "paired_by_order": 1077, "ambiguous": 173, "none": 1729}


@needs_db
def test_only_the_known_unresolved_code_is_unresolved(db):
    rows = db.execute("SELECT headword, unresolved_codes, decoded_nko FROM decoded_entries "
                      "WHERE has_unresolved_codes = 1 ORDER BY entry_ref").fetchall()
    assert [(r[0], json.loads(r[1])) for r in rows] == [("Km", ["U+F146"]), ("km2", ["U+F146"])]
    assert all("⟨U+F146⟩" in r[2] for r in rows)


@needs_db
def test_nothing_but_blank_glyphs_is_excluded_from_the_header_area(db):
    excluded = json.loads(meta(db, "header_area_glyphs_excluded"))
    assert set(excluded) <= {"U+F120", "U+0020"}


@needs_db
def test_every_row_is_machine_decoded_only(db):
    assert {r[0] for r in db.execute("SELECT DISTINCT status FROM decoded_entries")} == {"machine_decoded"}


@needs_db
def test_every_row_round_trips_and_has_no_pua(db):
    for r in db.execute("SELECT entry_ref, legacy_codes, alignment, decoded_nko FROM decoded_entries"):
        align = json.loads(r["alignment"])
        assert [dd.rebuild_codes(l) for l in align] == json.loads(r["legacy_codes"]), r["entry_ref"]
        assert "\n".join(dd.rebuild_text(l) for l in align) == r["decoded_nko"], r["entry_ref"]
        assert not any(dd.is_pua(c) for c in r["decoded_nko"]), r["entry_ref"]


V1_1_BACKUP = REPO_ROOT / "data" / "backups" / "dictionary_decoded.v1.1.0.sqlite"


@needs_db
def test_spacing_decisions_regression(db):
    # Pins the v1.2 spacing pass over the whole book (see SPACING_AUDIT.md).
    got = collections.Counter(t["rule"] for (tr,) in db.execute("SELECT transformations FROM decoded_entries")
                              for t in json.loads(tr))
    assert {k: got[k] for k in ("positioned_space_inserted", "wa_tail_gap_not_a_space", "wide_gap_not_spaced",
                                "narrow_gap_not_spaced", "leading_layout_space_removed",
                                "trailing_layout_space_removed", "wa_tail_spacer_removed")} == {
        "positioned_space_inserted": 31710, "wa_tail_gap_not_a_space": 413, "wide_gap_not_spaced": 51,
        "narrow_gap_not_spaced": 8, "leading_layout_space_removed": 1506,
        "trailing_layout_space_removed": 14424, "wa_tail_spacer_removed": 3458}


@needs_db
def test_no_decoded_line_starts_or_ends_with_a_space_unless_it_is_blank(db):
    for ref, text in db.execute("SELECT entry_ref, decoded_nko FROM decoded_entries"):
        for line in text.split("\n"):
            assert not line.strip(" ") or line == line.strip(" "), ref


@needs_db
@pytest.mark.parametrize("ref,line,rule,count", [
    ("p497-c0-e027", 0, "positioned_space_inserted", 1),   # space before the part-of-speech label
    ("p497-c1-orphan", 0, "leading_layout_space_removed", 3),  # continuation-line indent (S345)
    ("p400-c0-e026", 0, "wa_tail_gap_not_a_space", 1),     # gap is ߥ's tail, word stays joined
    ("p494-c0-e000", 0, "positioned_space_inserted", 2),   # incl. a 5 pt gap after ߥ: tail slot + one space
    ("p462-c1-e034", 0, "wide_gap_not_spaced", 1),         # stray fragment 93 pt away: left alone
])
def test_known_spacing_cases(db, ref, line, rule, count):
    (tr, text) = db.execute("SELECT transformations, decoded_nko FROM decoded_entries WHERE entry_ref = ?",
                            (ref,)).fetchone()
    hits = [t for t in json.loads(tr) if t["line"] == line and t["rule"] == rule]
    assert len(hits) == count
    first = text.split("\n")[line]
    assert first == first.strip(" ")


@needs_db
@pytest.mark.skipif(not V1_1_BACKUP.exists(), reason=f"{V1_1_BACKUP} not present")
def test_spacing_changed_nothing_but_spaces_since_v1_1(db):
    old = sqlite3.connect(f"file:{V1_1_BACKUP.as_posix()}?mode=ro", uri=True)
    cols = "entry_ref, headword, headword_lines, legacy_codes, line_positions, decoded_nko"
    before = {r[0]: r for r in old.execute(f"SELECT {cols} FROM decoded_entries")}
    old.close()
    after = {r[0]: tuple(r) for r in db.execute(f"SELECT {cols} FROM decoded_entries")}
    assert before.keys() == after.keys()
    changed = 0
    for ref, (_r, hw, hwl, codes, pos, text) in after.items():
        _r0, hw0, hwl0, codes0, pos0, text0 = before[ref]
        assert (hw, hwl, codes, pos) == (hw0, hwl0, codes0, pos0), ref        # French and glyphs untouched
        assert text.replace(" ", "") == text0.replace(" ", ""), ref          # only U+0020 differs
        assert text.count("\n") == text0.count("\n"), ref
        changed += text != text0
    assert changed == 23784


@needs_db
def test_candidate_rows_show_placeholders_and_never_candidate_letters(db):
    rows = db.execute("SELECT candidate_codes, decoded_nko FROM decoded_entries WHERE has_candidate_codes = 1").fetchall()
    assert rows
    for r in rows:
        for code in json.loads(r["candidate_codes"]):
            assert f"⟨{code}⟩" in r["decoded_nko"]
    assert db.execute("SELECT COUNT(*) FROM decoded_entries WHERE decoded_nko LIKE '%ߚ%'").fetchone()[0] == 0


@needs_db
def test_candidate_inventory_matches_corrected_body_counts(db):
    data = json.loads(V2.read_text(encoding="utf-8"))
    expected = {k: v["body_occurrences"] for k, v in data["codes"].items() if v["tier"] == "CANDIDATE"}
    got = dict(db.execute("SELECT codepoint, occurrences FROM code_inventory WHERE handling = 'CANDIDATE'").fetchall())
    assert got == expected


@needs_db
def test_source_references_are_complete_and_unique(db):
    n, distinct = db.execute("SELECT COUNT(*), COUNT(DISTINCT entry_ref) FROM decoded_entries").fetchone()
    assert n == distinct
    lo, hi = db.execute("SELECT MIN(page_number), MAX(page_number) FROM decoded_entries").fetchone()
    assert 22 <= lo and hi <= 498
    bad = db.execute("""SELECT COUNT(*) FROM decoded_entries WHERE entry_kind = 'headword'
                        AND (headword = '' OR headword_baseline_y IS NULL)""").fetchone()[0]
    assert bad == 0


@needs_db
def test_alphabet_ordinals_all_correct(db):
    checks = json.loads(meta(db, "validation"))["alphabet_ordinals"]
    assert all(c["ok"] for c in checks)
    # The audit found these 14; the corrected segmentation also reaches e, p, q, r.
    assert sorted(c["ordinal"] for c in checks) == [5, 7, 8, 9, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26]


@needs_db
def test_provenance_metadata_matches_inputs(db):
    assert meta(db, "status_of_all_rows") == "machine_decoded"
    assert meta(db, "mapping_sha256") == hashlib.sha256(V2.read_bytes()).hexdigest()
    assert meta(db, "decoder_version") == dd.DECODER_VERSION
    assert meta(db, "content_sha256") == dd.content_digest(db)
    if PDF.exists():
        assert meta(db, "source_pdf_sha256") == dd.sha256_file(PDF)


@pytest.mark.parametrize("path,expected", PROTECTED.items(), ids=lambda p: getattr(p, "name", ""))
def test_protected_source_files_are_unchanged(path, expected):
    if not path.exists():
        pytest.skip(f"{path} not present")
    assert dd.sha256_file(path) == expected


# ---------------------------------------------------------------------------
# Reproducibility from the PDF (slow: ~25 s per run)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not PDF.exists(), reason="source PDF not present")
def test_regeneration_from_pdf_is_reproducible(tmp_path):
    pytest.importorskip("fitz")
    pytest.importorskip("fontTools")
    pages = "264,452"
    a = dd.run(PDF, V2, tmp_path / "a.sqlite", pages)
    b = dd.run(PDF, V2, tmp_path / "b.sqlite", pages)
    assert a["content_sha256"] == b["content_sha256"]
    if DECODED_DB.exists():
        # The same pages inside the full build must be identical, except for the
        # continuation links, which depend on the neighbouring pages.
        cross_page = {"continued_from", "continued_by", "continuation_evidence"}
        cols = ", ".join(c for c in dd.ENTRY_COLUMNS if c not in cross_page)
        sql = f"SELECT {cols} FROM decoded_entries WHERE page_number IN (264, 452) ORDER BY entry_ref"
        small = sqlite3.connect(tmp_path / "a.sqlite")
        full = sqlite3.connect(f"file:{DECODED_DB.as_posix()}?mode=ro", uri=True)
        assert small.execute(sql).fetchall() == full.execute(sql).fetchall()
        small.close()
        full.close()
