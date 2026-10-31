"""Independently re-check the claims in docs/dictionary-decoding/.

This script does NOT reuse the investigation's own analysis code. It reads only
the source PDF and the saved mapping table (mapping_tiers.json), derives the
combining-mark set from the embedded font itself, rebuilds logical N'Ko order
from page geometry, and then tests:

  1. inventory      - every legacy code seen in the PDF vs. the mapping table
  2. font structure - zero-advance marks, duplicate outlines, composite marks
  3. ordering       - marks share their base's pen position; reversal needed
  4. orthography    - tone marks on vowels; woloso letters after nasals
  5. alphabet       - single-letter headwords: ordinal arithmetic + letter value
  6. front matter   - decoded names vs. French text printed in the same PDF
  7. coverage       - share of entries / records using only STRONG-tier codes

Letter sound values come from Unicode character names (unicodedata), not from
the investigation. Nothing is written into the repository; pass --json-out to
save results elsewhere.

Run from the repository root:

    py -3.14 scripts/audit_dictionary_decoding.py --json-out <scratch>/audit.json

Requirements: pymupdf, fonttools (see scripts/requirements-extraction.txt).
"""

from __future__ import annotations

import argparse
import collections
import json
import re
import sys
import tempfile
import unicodedata
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PDF = REPO_ROOT / "docs" / "dictionnaire Fr_nko.pdf"
DEFAULT_TIERS = REPO_ROOT / "docs" / "dictionary-decoding" / "mapping_tiers.json"
DEFAULT_RAW = REPO_ROOT / "data" / "raw_extraction.jsonl"
LEGACY_FONT = "Manden"
BODY_FIRST_PAGE = 22
SPACE = 0x20
# Non-letter glyphs the report says pass through unchanged (report section 4.4).
PASSTHROUGH = {0x20, 0x21, 0x22, 0x28, 0x29, 0x2B, 0x2C, 0x2E, 0x2F, 0x3A, 0x3D,
               0x5B, 0x5D, 0x60C, 0x61B, 0x61F, 0x66A, 0x2212}
BRACKET_MIRROR = {0x28: 0x29, 0x29: 0x28, 0x5B: 0x5D, 0x5D: 0x5B}


def legacy_code(u: int) -> int:
    """U+F1xx -> its byte (0x20..0xFF); real codepoints are kept as-is."""
    return u - 0xF100 if 0xF100 <= u < 0xF200 else u


# --------------------------------------------------------------------------
# Unicode-derived phonetics (independent of the investigation)
# --------------------------------------------------------------------------

def nko_latin(ch: str) -> str:
    """Rough Latin value of an N'Ko letter, derived from its Unicode name."""
    name = unicodedata.name(ch, "")
    if not name.startswith("NKO LETTER "):
        return ""
    v = name[len("NKO LETTER "):].lower()
    vowels = {"a": "a", "ee": "e", "i": "i", "e": "e", "u": "u", "oo": "o", "o": "o"}
    if v in vowels:  # EE=/e/, E=/ɛ/, OO=/o/, O=/ɔ/ per the Unicode chart; folded here
        return vowels[v]
    if v == "dagbasinna":
        return ""
    v = v.replace(" woloso", "")
    return v[:-1] if v.endswith("a") else v  # "ba" -> "b", "gba" -> "gb", "nya" -> "ny"


def is_vowel(ch: str) -> bool:
    return "ߊ" <= ch <= "ߐ"


def skeleton(nko: str) -> str:
    """Letters only, Latinised, tones dropped; nasal mark -> 'n'; digits kept."""
    out = []
    for ch in nko:
        if ch == "߲":
            out.append("n")
        elif "߀" <= ch <= "߉":
            out.append(str(ord(ch) - 0x7C0))
        elif ch == "ߒ":
            out.append("n")
        else:
            out.append(nko_latin(ch))
    return "".join(out)


# --------------------------------------------------------------------------
# PDF access
# --------------------------------------------------------------------------

def font_metrics(doc, tmp: Path):
    """Return (gid->advance, gid->contour signature) for the embedded legacy font."""
    from fontTools.pens.recordingPen import RecordingPen
    from fontTools.ttLib import TTFont

    for pno in range(doc.page_count):
        for info in doc.get_page_fonts(pno, full=True):
            if LEGACY_FONT in info[3]:
                path = tmp / "legacy.ttf"
                path.write_bytes(doc.extract_font(info[0])[3])
                font = TTFont(str(path))
                order = font.getGlyphOrder()
                gs = font.getGlyphSet()
                adv, contours = {}, {}
                for gid, name in enumerate(order):
                    adv[gid] = font["hmtx"][name][0]
                    rec = RecordingPen()
                    gs[name].draw(rec)
                    parts, cur = [], []
                    for op, args in rec.value:
                        cur.append((op, tuple(args)))
                        if op in ("closePath", "endPath"):
                            parts.append(tuple(cur))
                            cur = []
                    contours[gid] = frozenset(parts)
                return adv, contours
    raise SystemExit("legacy font not found in PDF")


def code_to_gid(doc) -> dict[int, int]:
    """Legacy code -> glyph id, read from the text trace (all pages)."""
    mapping = {}
    for pno in range(doc.page_count):
        for span in doc[pno].get_texttrace():
            if LEGACY_FONT in span["font"]:
                for u, gid, _o, _b in span["chars"]:
                    mapping.setdefault(legacy_code(u), gid)
    return mapping


def page_glyphs(page, fonts=(LEGACY_FONT,)):
    """(legacy glyphs [(x, y, code)], French headwords [(col, baseline, text)]); overprint removed.

    The front matter is set in the author's misnamed "MonotypeKoufi-Bold" font,
    which shares the Manden encoding, so callers pass it in `fonts` there.
    """
    glyphs, heads, seen = [], [], {}
    for block in page.get_text("rawdict")["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                if not span["chars"]:
                    continue
                if any(f in span["font"] for f in fonts):
                    for ch in span["chars"]:
                        x, y = ch["origin"]
                        code = legacy_code(ord(ch["c"]))
                        # Faux-bold front matter repeats each glyph as a shadow
                        # offset by ~0.9 pt; treat the same code within 1.5 pt
                        # as one glyph.
                        near = seen.setdefault(code, [])
                        if any(abs(x - x2) < 1.5 and abs(y - y2) < 1.5 for x2, y2 in near):
                            continue
                        near.append((x, y))
                        glyphs.append((x, y, code))
                elif span["font"] == "ArialNarrow" and round(span["bbox"][0]) in (106, 107, 308, 309, 310):
                    text = "".join(c["c"] for c in span["chars"]).strip()
                    base = span["chars"][0]["origin"][1]
                    if text and base > 85:
                        heads.append((0 if span["bbox"][0] < 300 else 1, base, text))
    return glyphs, heads


def logical_lines(glyphs, marks, tie_break=True):
    """Group glyphs into lines by baseline; order each line right-to-left."""
    lines = collections.defaultdict(list)
    for x, y, c in glyphs:
        key = next((k for k in lines if abs(k - y) < 2.5), y)
        lines[key].append((x, c))
    out = []
    for y in sorted(lines):
        if tie_break:  # at an equal pen position the base precedes its mark
            g = sorted(lines[y], key=lambda t: (-round(t[0], 1), 1 if t[1] in marks else 0))
        else:  # naive reversal of the visual stream, for comparison
            g = sorted(lines[y], key=lambda t: -round(t[0], 1))
        out.append((y, [c for _, c in g]))
    return out


# --------------------------------------------------------------------------
# Decoding with the saved table
# --------------------------------------------------------------------------

def load_tiers(path: Path):
    raw = json.loads(path.read_text(encoding="utf-8"))
    table = {}
    for k, v in raw.items():
        chars = "".join(chr(int(cp[2:], 16)) for cp in v["unicode"].split())
        table[int(k, 16)] = (chars, v["tier"])
    return table


def decode(codes, table, allow=("STRONG",)):
    out = []
    for i, c in enumerate(codes):
        if c == SPACE and i and codes[i - 1] == 0x78 and i + 1 < len(codes) and codes[i + 1] in table:
            continue  # spacer under the tail of 0x78 (report section 6, rule 5)
        if c in table and table[c][1] in allow:
            out.append(table[c][0])
        elif c in PASSTHROUGH:
            out.append(chr(BRACKET_MIRROR.get(c, c)))
        else:
            out.append(f"⟨{c:02X}⟩")  # never silently dropped
    return "".join(out)


# --------------------------------------------------------------------------
# Checks
# --------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pdf", type=Path, default=DEFAULT_PDF)
    ap.add_argument("--tiers", type=Path, default=DEFAULT_TIERS)
    ap.add_argument("--raw", type=Path, default=DEFAULT_RAW)
    ap.add_argument("--json-out", type=Path)
    args = ap.parse_args()

    import fitz

    doc = fitz.open(str(args.pdf))
    table = load_tiers(args.tiers)
    results = {}

    with tempfile.TemporaryDirectory() as tmp:
        adv, contours = font_metrics(doc, Path(tmp))
    c2g = code_to_gid(doc)
    marks = {c for c, g in c2g.items() if adv.get(g) == 0 and contours.get(g)}

    # Gather every page once.
    pages = {}
    for pno in range(1, doc.page_count + 1):
        pages[pno] = page_glyphs(doc[pno - 1])

    # 1. inventory --------------------------------------------------------
    seen_body, seen_front = collections.Counter(), collections.Counter()
    for pno, (glyphs, _h) in pages.items():
        for _x, _y, c in glyphs:
            (seen_body if pno >= BODY_FIRST_PAGE else seen_front)[c] += 1
    letters_seen = {c for c in set(seen_body) | set(seen_front) if c not in PASSTHROUGH}
    inv = {
        "codes_in_table": len(table),
        "table_tiers": dict(collections.Counter(t for _c, t in table.values())),
        "non_passthrough_codes_seen_in_pdf": len(letters_seen),
        "seen_but_missing_from_table": sorted(f"{c:02X}" for c in letters_seen - set(table)),
        "in_table_but_never_seen": sorted(f"{c:02X}" for c in set(table) - letters_seen),
        "in_table_seen_only_in_front_matter": sorted(f"{c:02X}" for c in set(table) if seen_front[c] and not seen_body[c]),
        "table_codes_seen_in_body": sum(1 for c in table if seen_body[c]),
        "strong_codes_seen_in_body": sum(1 for c, (_u, t) in table.items() if seen_body[c] and t == "STRONG"),
        "candidate_codes_seen_in_body": sum(1 for c, (_u, t) in table.items() if seen_body[c] and t == "CANDIDATE"),
        "candidate_occurrences_body": {f"{c:02X}": seen_body[c] for c, (_u, t) in table.items() if t == "CANDIDATE"},
    }
    results["1_inventory"] = inv

    # 2. font structure -----------------------------------------------------
    g = lambda c: contours.get(c2g.get(c))
    same_pairs = [(0x42, 0x5D0), (0x6B, 0x6C), (0x6F, 0x70), (0xA9, 0xAA), (0xAB, 0xAC), (0xBC, 0xBD), (0xC0, 0xC1),
                  (0xC4, 0xD2), (0xC5, 0xD3), (0xC6, 0xD4), (0xC7, 0xD5), (0xC9, 0xD7), (0xCA, 0xD8), (0xCB, 0xD9)]
    composites = [(0xCC, 0xC4, 0xC9), (0xCD, 0xC5, 0xC9), (0xD0, 0xCA, 0xC9), (0xD1, 0xCB, 0xC9), (0xDA, 0xD2, 0xD7), (0xDB, 0xD3, 0xD7)]
    results["2_font_structure"] = {
        "zero_advance_mark_codes": sorted(f"{c:02X}" for c in marks),
        "identical_outline_pairs": {f"{a:02X}={b:02X}": (g(a) == g(b)) for a, b in same_pairs if g(a) and g(b)},
        "composite_is_exact_union": {f"{c:02X}={a:02X}+{b:02X}": (g(c) == (g(a) | g(b))) for c, a, b in composites if g(c)},
        "mark_table_agrees": all((table[c][0][:1] >= "߫" and table[c][0][:1] <= "߳") for c in marks if c in table),
    }

    # 3. ordering --------------------------------------------------------------
    same_x = total_marks = 0
    for pno, (glyphs, _h) in pages.items():
        if pno < BODY_FIRST_PAGE:
            continue
        lines = collections.defaultdict(list)
        for x, y, c in glyphs:
            key = next((k for k in lines if abs(k - y) < 2.5), y)
            lines[key].append((x, c))
        for row in lines.values():
            row.sort()
            for i, (x, c) in enumerate(row):
                if c in marks:
                    total_marks += 1
                    if any(abs(x2 - x) < 0.05 and c2 not in marks for x2, c2 in row):
                        same_x += 1
    results["3_ordering"] = {"marks_sharing_pen_position_with_a_base": f"{same_x}/{total_marks}"}

    # 4. orthography (with correct and naive ordering) ---------------------------
    def ortho(tie_break):
        on = collections.Counter()
        wol = collections.Counter()
        for pno, (glyphs, _h) in pages.items():
            if pno < BODY_FIRST_PAGE:
                continue
            for _y, codes in logical_lines(glyphs, marks, tie_break):
                prev_base, nasal_pending = None, False
                for c in codes:
                    if c in marks:
                        u = table.get(c, ("", ""))[0]
                        if c not in (0xC5, 0xD3):  # dot-above doubles as a consonant modifier
                            on["vowel" if prev_base and is_vowel(prev_base) or prev_base == "ߒ" else "other"] += 1
                        if "߲" in u:
                            nasal_pending = True
                        continue
                    u = table.get(c, ("", ""))[0]
                    if u in ("ߠ", "ߟ", "ߧ", "ߦ"):
                        wol[(u, nasal_pending)] += 1
                    if c == SPACE and prev_base is None:
                        continue
                    if u and not (c == SPACE):
                        if is_vowel(u):
                            nasal_pending = False
                        prev_base = u
                    elif c != SPACE:
                        prev_base, nasal_pending = None, False
        share = lambda ch: round(100 * wol[(ch, True)] / max(1, wol[(ch, True)] + wol[(ch, False)]), 1)
        return {"marks_on_vowels_pct": round(100 * on["vowel"] / max(1, sum(on.values())), 2), "marks_counted": sum(on.values()),
                "after_nasal_pct": {"U+07E0 na-woloso": share("ߠ"), "U+07DF la": share("ߟ"),
                                    "U+07E7 nya-woloso": share("ߧ"), "U+07E6 ya": share("ߦ")}}
    results["4_orthography"] = {"geometric_order_base_before_mark": ortho(True), "naive_reversal": ortho(False)}

    # Entry corpus (in memory only; never written) -------------------------------------
    entries = []
    for pno, (glyphs, heads) in pages.items():
        if pno < BODY_FIRST_PAGE:
            continue
        for col in (0, 1):
            hs = sorted((y, t) for c, y, t in heads if c == col)
            col_glyphs = [gl for gl in glyphs if (gl[0] < 300) == (col == 0) and gl[1] > 85]
            lines = logical_lines(col_glyphs, marks)
            for i, (hy, text) in enumerate(hs):
                ny = hs[i + 1][0] if i + 1 < len(hs) else 1e9
                seqs = [codes for ly, codes in lines if hy - 2.5 <= ly < ny - 2.5]
                entries.append((pno, text, seqs))

    # 5. alphabet entries -------------------------------------------------------------
    expect = {"a": "a", "f": "f", "h": "h", "i": "i", "j": "j", "g": "j", "k": "k", "l": "l", "m": "m", "n": "n",
              "o": "o", "s": "s", "t": "t", "u": "u", "v": "f", "w": "w", "x": "iks", "y": "y", "z": "j"}
    alpha = []
    for pno, text, seqs in entries:
        h = text.strip(" ,.")
        if len(h) != 1 or not h.isalpha() or not seqs:
            continue
        nko = decode(seqs[0], table, allow=("STRONG", "CANDIDATE"))
        # Entries read "<letter>ߕ. ..." where "ߕ." abbreviates the part of speech.
        first = nko.split(".")[0].strip()
        if nko.split(".")[0].endswith("ߕ") and len(first) > 1:
            first = first[:-1].strip()
        m = re.search(r"([߀-߉]+)", nko)
        ordinal = int("".join(str(ord(d) - 0x7C0) for d in m.group(1))) if m else None
        expected_ord = ord(h.lower()) - ord("a") + 1
        alpha.append({"page": pno, "letter": h, "nko_first_token": first, "letter_value": skeleton(first),
                      "letter_expected": expect.get(h.lower()), "letter_ok": skeleton(first) == expect.get(h.lower()),
                      "ordinal": ordinal, "ordinal_expected": expected_ord,
                      "ordinal_ok": None if ordinal is None else ordinal == expected_ord})
    results["5_alphabet"] = {
        "entries": alpha,
        "ordinals_present": sum(1 for a in alpha if a["ordinal"] is not None),
        "ordinals_correct": sum(1 for a in alpha if a["ordinal_ok"]),
        "letters_checked": sum(1 for a in alpha if a["letter_expected"]),
        "letters_correct": sum(1 for a in alpha if a["letter_ok"]),
    }

    # 6. front matter vs French text printed in the same PDF ------------------------------
    front = []
    for pno in (2, 8, 9):
        glyphs, _h = page_glyphs(doc[pno - 1], fonts=(LEGACY_FONT, "Koufi"))
        for _y, codes in logical_lines(glyphs, marks):
            front.append(skeleton(decode(codes, table, allow=("STRONG", "CANDIDATE"))))
    blob = " ".join(front)
    targets = {  # French source text -> exact or normalised expectation
        "KANJAMADI (p1 title)": ("kanjamadi", "exact"),
        "N'KO (p1 title)": ("nko", "exact"),
        "BABA (p1 author)": ("baba", "exact"),
        "MAMADI (p1 author)": ("mamadi", "exact"),
        "2014 (p1 edition)": ("2014", "exact"),
        "DIANE (p1 author)": ("jane", "normalised: French 'di'+vowel = N'Ko j"),
        "Bate (font copyright)": ("bate", "normalised: e/ɛ folded"),
        "Nafadjika (font copyright)": ("nfajika", "normalised: dj = j; vowel elision a->0"),
        "Guine (font copyright)": ("jine", "normalised: French gu/gi = N'Ko j"),
    }
    results["6_front_matter"] = {k: {"expected_skeleton": v, "basis": b, "found": v in blob} for k, (v, b) in targets.items()}

    # 7. coverage ---------------------------------------------------------------------------
    def weakest(codes):
        tiers = set()
        for c in codes:
            if c in PASSTHROUGH:
                continue
            tiers.add(table[c][1] if c in table else "UNMAPPED")
        return "UNMAPPED" if "UNMAPPED" in tiers else "CANDIDATE" if "CANDIDATE" in tiers else "STRONG"
    by_entry = collections.Counter(weakest([c for s in seqs for c in s]) for _p, _t, seqs in entries if seqs)
    glyph_tier = collections.Counter()
    for _p, _t, seqs in entries:
        for s in seqs:
            for c in s:
                glyph_tier["PASSTHROUGH" if c in PASSTHROUGH else table[c][1] if c in table else "UNMAPPED"] += 1
    raw_tier = collections.Counter()
    if args.raw.exists():
        for line in args.raw.open(encoding="utf-8"):
            rec = json.loads(line)
            raw_tier[weakest([legacy_code(ord(ch)) for ch in rec["raw_target"]])] += 1
    pct = lambda c: {k: f"{v} ({100 * v / sum(c.values()):.2f}%)" for k, v in c.items()} if c else {}
    results["7_coverage"] = {"geometric_entries": pct(by_entry), "glyph_occurrences": pct(glyph_tier),
                             "raw_extraction_records": pct(raw_tier), "geometric_entry_count": sum(by_entry.values())}

    print(json.dumps({k: v for k, v in results.items() if k != "5_alphabet"}, ensure_ascii=False, indent=1))
    print(json.dumps({k: v for k, v in results["5_alphabet"].items() if k != "entries"}, indent=1))
    for a in results["5_alphabet"]["entries"]:
        print(f"  p{a['page']:3d} {a['letter']!r:4} value={a['letter_value']!r:7} expected={a['letter_expected']!r:7} "
              f"ordinal={a['ordinal']} expected={a['ordinal_expected']}")
    if args.json_out:
        args.json_out.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\nwrote {args.json_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
