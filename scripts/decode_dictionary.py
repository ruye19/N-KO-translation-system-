"""Offline decoder: legacy N'ko2Manden dictionary text -> machine-decoded Unicode N'Ko.

Reads the original PDF directly (never data/raw_extraction.jsonl, which is in
visual order and mixes in other fonts) and writes a SEPARATE database,
data/dictionary_decoded.sqlite. It never writes the PDF, data/dictionary.sqlite
or data/raw_extraction.jsonl, and it checks their hashes before and after.

Pipeline (see docs/dictionary-decoding/DESIGN_PROPOSAL.md):

  1 extract   glyphs with page positions, from the legacy font only
  2 order     visual left-to-right -> logical right-to-left; at an equal pen
              position the base precedes its zero-advance mark
  3 segment   N'Ko lines -> the French headword or sub-entry whose baseline they
              follow; wrapped headwords are joined, column-top text is linked
              to the entry it continues
  4 decode    STRONG-tier codes only. CANDIDATE and unknown codes become
              visible placeholders such as "⟨U+F148⟩"; nothing is guessed or
              dropped. Every glyph is recorded in an alignment, so the original
              code sequence can always be rebuilt. Spacing (v1.2): word gaps
              the typesetter made by moving the pen become spaces; space
              glyphs that only indent or trail a line are dropped. Every such
              decision is recorded (see decode_line).
  5 validate  build-time invariants; the build fails if any is broken
  6 store     new SQLite database; every row has status 'machine_decoded'

Machine-decoded is NOT verified. No row produced here may be presented as
human-verified N'Ko. Coverage figures measure mapping coverage, not accuracy.

Run from the repository root (needs pymupdf + fonttools, see
scripts/requirements-extraction.txt):

    python scripts/decode_dictionary.py
    python scripts/decode_dictionary.py --pages 22-30 --output <scratch>/sample.sqlite
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import logging
import os
import re
import sqlite3
import sys
import tempfile
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PDF = REPO_ROOT / "docs" / "dictionnaire Fr_nko.pdf"
DEFAULT_MAPPING = REPO_ROOT / "docs" / "dictionary-decoding" / "mapping_tiers.v2.json"
DEFAULT_OUTPUT = REPO_ROOT / "data" / "dictionary_decoded.sqlite"
SOURCE_DB = REPO_ROOT / "data" / "dictionary.sqlite"
RAW_JSONL = REPO_ROOT / "data" / "raw_extraction.jsonl"

DECODER_VERSION = "1.2.0"
TOOL_NAME = "decode_dictionary"
STATUS = "machine_decoded"

LEGACY_FONT = "Manden"
# The author's misnamed "MonotypeKoufi-Bold" font shares the Manden encoding and
# glyph layout; a few body pages use it, so its glyphs are decoded too.
LEGACY_FONTS = (LEGACY_FONT, "Koufi")
FIRST_BODY_PAGE = 22
# Running headers end at y=78; the first body baseline on early pages is 82.
# Only blank legacy glyphs (spaces at y=75) sit above this line.
HEADER_LIMIT_Y = 78.0
COLUMN_SPLIT_X = 300.0
HEADWORD_FONT = "ArialNarrow"
MARGIN_TOLERANCE = 1.5          # pt: headwords start at the column's own left margin
LINE_TOLERANCE = 2.5            # pt: glyphs on one baseline
SHADOW_TOLERANCE = 1.5          # pt: faux-bold shadow copies of a glyph

# The segmentation used by the investigation and the reproducibility audit.
# It assumed fixed margins and a header line at 85, which drops whole columns
# on pages laid out at x=105/307 or 108/310 and the first entry on early
# pages. Kept only so the audited 99.13% figure stays a regression check.
AUDIT_V1 = {"header_y": 85.0, "headword_x": (106, 107, 308, 309, 310), "fonts": (LEGACY_FONT,)}

WA_TAIL = 0xF178                # ߥ drawn with a long tail; a spacer follows it
SPACE_CODES = {0xF120, 0x0020}  # glyphs that are themselves spaces

# Spacing (v1.2, see docs/dictionary-decoding/SPACING_AUDIT.md). Besides the
# U+F120 glyph, the typesetter separated words by moving the pen: a gap with no
# glyph in it, almost always exactly one U+F120 advance wide (341/2048 em, 2.5 pt
# at 15 pt), with clear space between the glyph outlines.
SPACE_ADVANCE_EM = 341 / 2048
POSITIONED_SPACE_MIN = 1.95     # pt: one space at the smallest (12 pt label) size is 2.0 pt
POSITIONED_SPACE_MAX = 5.5      # pt: wider gaps separate stray fragments; left alone
GAP_NOTE_MIN = 0.3              # pt: below this, glyphs simply abut
PLACEHOLDER = "⟨U+{:04X}⟩"
MIRROR = {"(": ")", ")": "(", "[": "]", "]": "["}

logger = logging.getLogger("dictionary_decoder")


# --------------------------------------------------------------------------
# Mapping
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Mapping:
    version: str
    sha256: str
    source_pdf_sha256: str
    codes: dict[int, dict]          # codepoint -> {"unicode", "tier", "role", "kind"}
    passthrough: dict[int, dict]    # codepoint -> {"output", "role", ...}

    def is_letter(self, cp: int) -> bool:
        info = self.codes.get(cp)
        return bool(info) and info["role"] == "letter"


def load_mapping(path: Path) -> Mapping:
    raw = path.read_bytes()
    data = json.loads(raw.decode("utf-8"))

    def cp(key: str) -> int:
        if not key.startswith("U+"):
            raise ValueError(f"mapping key {key!r} must look like 'U+F142'")
        return int(key[2:], 16)

    codes = {}
    for key, info in data["codes"].items():
        codes[cp(key)] = {
            "unicode": "".join(chr(int(u[2:], 16)) for u in info["unicode"].split()),
            "tier": info["tier"],
            "role": info["role"],
            "kind": info["kind"],
        }
    passthrough = {cp(k): v for k, v in data["passthrough"].items()}
    overlap = set(codes) & set(passthrough)
    if overlap:
        raise ValueError(f"codes listed both as mapped and passthrough: {sorted(overlap)}")
    return Mapping(
        version=data["version"],
        sha256=hashlib.sha256(raw).hexdigest(),
        source_pdf_sha256=data["source_pdf_sha256"],
        codes=codes,
        passthrough=passthrough,
    )


# --------------------------------------------------------------------------
# Ordering and decoding (pure functions, no PDF needed)
# --------------------------------------------------------------------------

def order_line(glyphs: list[tuple[float, int]], marks: set[int]) -> list[int]:
    """Visual (x, codepoint) pairs -> logical right-to-left codepoints.

    A zero-advance mark is drawn at the same pen position as the base it sits
    on, so at an equal x the base must come first. The investigation measured
    99.97% of marks landing on vowels with this rule and 0.92% without it.
    """
    ordered = sorted(glyphs, key=lambda g: (-round(g[0], 1), 1 if g[1] in marks else 0))
    return [cp for _, cp in ordered]


def positioned_gaps(glyphs: list[tuple[float, int, float, float]], marks: set[int]) -> dict[int, dict]:
    """Gaps the pen skipped with no glyph in them, keyed by logical index.

    glyphs are (x, codepoint, advance width, font size). The result maps the
    logical index of the glyph just LEFT of a gap (it follows the gap in
    reading order) to {"gap": pt, "unit": one space advance in pt, "after": the
    codepoint just right of the gap}. Gaps next to a space glyph are not
    reported: the space is already there. decode_line decides what a gap means.
    """
    order = sorted(range(len(glyphs)), key=lambda i: (-round(glyphs[i][0], 1), 1 if glyphs[i][1] in marks else 0))
    logical = {i: k for k, i in enumerate(order)}
    visual = sorted(range(len(glyphs)), key=lambda i: (round(glyphs[i][0], 1), 1 if glyphs[i][1] in marks else 0))
    gaps, right, prev = {}, None, None
    for i in visual:
        x, cp, w, size = glyphs[i]
        if cp in marks:
            continue
        if right is not None and x - right > GAP_NOTE_MIN and SPACE_CODES.isdisjoint({cp, glyphs[prev][1]}):
            # i is right of the gap (earlier in reading order), prev is left of it.
            gaps[logical[prev]] = {"gap": round(x - right, 2),
                                   "unit": round(SPACE_ADVANCE_EM * max(size, glyphs[prev][3]), 2),
                                   "after": cp}
        right = x + w if right is None else max(right, x + w)
        prev = i
    return gaps


class NkoLine(tuple):
    """One N'Ko line. Unpacks as (baseline, logical codes, (x_min, x_max));
    .gaps holds positioned_gaps() for it (empty when glyph widths are unknown)."""

    def __new__(cls, y: float, codes: list[int], extent: tuple[float, float], gaps: dict | None = None):
        line = super().__new__(cls, (y, codes, extent))
        line.gaps = gaps or {}
        return line


@dataclass
class DecodedLine:
    text: str                       # NFC-normalised output
    alignment: list[list]           # [[codepoint, output], ...] in logical order
    candidate_codes: set[int] = field(default_factory=set)
    unresolved_codes: set[int] = field(default_factory=set)
    transformations: list[dict] = field(default_factory=list)


def decode_line(codes: list[int], mapping: Mapping, line_index: int = 0, gaps: dict | None = None) -> DecodedLine:
    """Decode one logical line. Every input code yields exactly one alignment item;
    a space inserted for a positioned gap is an extra item [None, " "].

    Spacing rules (each recorded in transformations):
      * positioned_space_inserted: a gap of one or two space advances with no
        glyph in it becomes one or two spaces;
      * wa_tail_gap_not_a_space: a gap after ߥ before a letter is the slot its
        tail is drawn into (outline starts 315/2048 em left of its origin), the
        same case as wa_tail_spacer_removed;
      * wide_gap_not_spaced / narrow_gap_not_spaced: measured but left alone;
      * leading_layout_space_removed / trailing_layout_space_removed: space
        glyphs before the first or after the last visible glyph of a line. They
        indent continuation lines or trail the line; they never separate two
        words on the line. A line of nothing but spaces is kept as it is.
    """
    out = DecodedLine(text="", alignment=[])
    gaps = gaps or {}
    is_space = [cp in mapping.passthrough and mapping.passthrough[cp]["role"] == "space" for cp in codes]
    if all(is_space):
        lead = trail = 0
    else:
        lead = is_space.index(False)
        trail = is_space[::-1].index(False)
    for i, cp in enumerate(codes):
        info = mapping.codes.get(cp)
        if i in gaps:
            out.alignment.extend([None, " "] for _ in range(_gap_spaces(gaps[i], cp, mapping, line_index, i, out)))
        if i < lead or i >= len(codes) - trail:
            rule = "leading_layout_space_removed" if i < lead else "trailing_layout_space_removed"
            out.transformations.append({"line": line_index, "index": i, "rule": rule})
            out.alignment.append([cp, ""])
            continue
        if (
            cp in mapping.passthrough
            and mapping.passthrough[cp]["role"] == "space"
            and i > 0
            and codes[i - 1] == WA_TAIL
            and i + 1 < len(codes)
            and mapping.is_letter(codes[i + 1])
        ):
            piece = ""
            out.transformations.append({"line": line_index, "index": i, "rule": "wa_tail_spacer_removed"})
        elif info is not None and info["tier"] == "STRONG":
            piece = info["unicode"]
            if len(piece) > 1:
                out.transformations.append({"line": line_index, "index": i, "rule": "composite_mark_expanded"})
        elif info is not None:
            piece = PLACEHOLDER.format(cp)
            out.candidate_codes.add(cp)
        elif cp in mapping.passthrough:
            piece = mapping.passthrough[cp]["output"]
            if piece in MIRROR:
                piece = MIRROR[piece]
                out.transformations.append({"line": line_index, "index": i, "rule": "bracket_mirrored"})
        else:
            piece = PLACEHOLDER.format(cp)
            out.unresolved_codes.add(cp)
        out.alignment.append([cp, piece])
    out.text = unicodedata.normalize("NFC", "".join(p for _, p in out.alignment))
    return out


def _gap_spaces(gap: dict, next_cp: int, mapping: Mapping, line_index: int, index: int, out: DecodedLine) -> int:
    """How many spaces a positioned gap before codes[index] stands for (0, 1 or 2)."""
    note = {"line": line_index, "index": index, "gap_pt": gap["gap"]}
    width = gap["gap"]
    if gap["after"] == WA_TAIL and mapping.is_letter(next_cp):
        width -= gap["unit"]            # the tail's own slot
        if width < POSITIONED_SPACE_MIN:
            out.transformations.append({**note, "rule": "wa_tail_gap_not_a_space"})
            return 0
    if width > POSITIONED_SPACE_MAX:
        out.transformations.append({**note, "rule": "wide_gap_not_spaced"})
        return 0
    if width < POSITIONED_SPACE_MIN:
        out.transformations.append({**note, "rule": "narrow_gap_not_spaced"})
        return 0
    n = 1 if width < 1.5 * gap["unit"] else 2
    out.transformations.append({**note, "rule": "positioned_space_inserted", "spaces": n})
    return n


def rebuild_codes(alignment: list[list]) -> list[int]:
    """Original legacy code sequence, recovered from an alignment (inserted spaces have no code)."""
    return [cp for cp, _ in alignment if cp is not None]


def rebuild_text(alignment: list[list]) -> str:
    return unicodedata.normalize("NFC", "".join(piece for _, piece in alignment))


def is_pua(ch: str) -> bool:
    o = ord(ch)
    return 0xE000 <= o <= 0xF8FF or 0xF0000 <= o <= 0x10FFFF


def weakest_tier(lines: list[DecodedLine]) -> str:
    if not lines:
        return "EMPTY"
    if any(l.unresolved_codes for l in lines):
        return "UNRESOLVED"
    if any(l.candidate_codes for l in lines):
        return "CANDIDATE"
    return "STRONG"


# The print sets "-nan" both solid and after a one-space gap (q, e), and the
# decoder keeps the gap as printed, so the check accepts either.
_ORDINAL = re.compile(r"([߀-߉]+)(?:߲| ?ߣߊ߲)")


def alphabet_ordinal(decoded_first_line: str) -> int | None:
    """Ordinal in an alphabet entry: N'Ko digits followed by the suffix -n / -nan."""
    m = _ORDINAL.search(decoded_first_line)
    if not m:
        return None
    return int("".join(str(ord(d) - 0x7C0) for d in m.group(1)))


# --------------------------------------------------------------------------
# PDF extraction
# --------------------------------------------------------------------------

@dataclass
class PageData:
    """Everything segmentation needs from one page; filtering happens later."""
    number: int
    glyphs: list[tuple]     # (x, baseline y, codepoint, font[, advance width, font size])
    spans: list[tuple[int, float, float, str]]      # ArialNarrow: (column, baseline y, x0, raw text)
    pos_baselines: set = field(default_factory=set)   # (column, y): non-blank italic POS label
    text_baselines: set = field(default_factory=set)  # (column, y): non-legacy text with a letter
    line_right: dict = field(default_factory=dict)    # (column, y): right edge of the French line


def _column(x0: float) -> int:
    return 0 if x0 < COLUMN_SPLIT_X else 1


def extract_page(page, number: int) -> PageData:
    glyphs, spans, pos, text, right = [], [], set(), set(), {}
    seen: dict[int, list[tuple[float, float]]] = {}
    for block in page.get_text("rawdict")["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                chars = span["chars"]
                if not chars:
                    continue
                font = next((f for f in LEGACY_FONTS if f in span["font"]), None)
                if font:
                    for ch in chars:
                        x, y = ch["origin"]
                        cp = ord(ch["c"])
                        near = seen.setdefault(cp, [])
                        if any(abs(x - x2) < SHADOW_TOLERANCE and abs(y - y2) < SHADOW_TOLERANCE for x2, y2 in near):
                            continue
                        near.append((x, y))
                        glyphs.append((x, y, cp, font, ch["bbox"][2] - x, span["size"]))
                    continue
                raw = "".join(c["c"] for c in chars)
                if not raw.strip():
                    continue
                x0, y = span["bbox"][0], chars[0]["origin"][1]
                key = (_column(x0), round(y, 1))
                # A lone "." is not French text, and italic usage labels ("fig.",
                # "n.m.") carried to the top of a column belong to the entry above.
                if any(ch.isalpha() for ch in raw) and "Italic" not in span["font"]:
                    text.add(key)
                if span["font"] == HEADWORD_FONT:
                    spans.append((key[0], y, x0, raw))
                    right[key] = max(right.get(key, 0.0), span["bbox"][2])
                elif span["font"].startswith(HEADWORD_FONT + "-Italic"):
                    pos.add(key)
    return PageData(number, glyphs, spans, pos, text, right)


def _on_baseline(marks: set, col: int, y: float, tol: float = 1.0) -> bool:
    return any(c == col and abs(yy - y) <= tol for c, yy in marks)


MARGIN_WINDOW = 5.0             # pt: margin jitter is <=2 pt; indents start 7+ pt in


def column_margin(xs: list[float]) -> float:
    """The column's headword margin: the most common left edge near the leftmost.

    The minimum alone is fragile: one span a few points left of the true
    margin (e.g. "de" at x=308 under headwords at 310) would reject every
    real headword. The plain mode is fragile too: a column with more indented
    sub-entry lines than headwords would take the indent as its margin. So
    the mode is taken only among edges within MARGIN_WINDOW of the leftmost.
    Ties go to the leftmost edge.
    """
    lo = min(xs)
    counts = collections.Counter(round(x) for x in xs if x <= lo + MARGIN_WINDOW)
    best = max(counts.values())
    return float(min(x for x, n in counts.items() if n == best))


def page_headwords(page: PageData, mode: str) -> list[tuple[int, float, str]]:
    """(column, baseline, text) of the margin headwords on a page.

    'page_margins': an ArialNarrow span starting at most MARGIN_TOLERANCE
    points right of its column's margin (see column_margin). Indented lines
    are handled separately by segment_page; page numbers are excluded.
    'audit_v1': the fixed-margin rule the audit used.
    """
    if mode == "audit_v1":
        return [(c, y, t.strip()) for c, y, x0, t in page.spans
                if round(x0) in AUDIT_V1["headword_x"] and y > AUDIT_V1["header_y"]]
    heads = []
    for col, spans in _body_spans(page).items():
        margin = column_margin([x0 for _y, x0, _t in spans])
        heads += [(col, y, t.strip()) for y, x0, t in spans if x0 <= margin + MARGIN_TOLERANCE]
    return heads


def _body_spans(page: PageData) -> dict[int, list[tuple[float, float, str]]]:
    out: dict[int, list] = {}
    for c, y, x0, t in page.spans:
        if y > HEADER_LIMIT_Y and not t.strip().isdigit():
            out.setdefault(c, []).append((y, x0, t))
    for spans in out.values():
        spans.sort()
    return out


def page_body_glyphs(page: PageData, mode: str):
    """(body glyphs [(x, y, cp, width, size)], excluded Counter) under a segmentation mode.
    width and size are None when the page data does not carry them."""
    header_y = AUDIT_V1["header_y"] if mode == "audit_v1" else HEADER_LIMIT_Y
    fonts = AUDIT_V1["fonts"] if mode == "audit_v1" else LEGACY_FONTS
    body, excluded = [], collections.Counter()
    for g in page.glyphs:
        x, y, cp, font = g[:4]
        if font in fonts and y > header_y:
            body.append((x, y, cp, *(g[4:6] if len(g) >= 6 else (None, None))))
        else:
            excluded[cp] += 1
    return body, excluded


def legacy_font_marks(doc) -> tuple[set[int], str]:
    """Zero-advance (combining) codepoints, read from the embedded legacy font itself.

    Returns (mark codepoints, sha256 of the font program). Every embedded subset
    of the legacy font must be the same program, or the run stops.
    """
    from fontTools.ttLib import TTFont

    programs = {}
    for pno in range(doc.page_count):
        for info in doc.get_page_fonts(pno, full=True):
            if LEGACY_FONT in info[3] and info[0] not in programs:
                programs[info[0]] = doc.extract_font(info[0])[3]
    digests = {hashlib.sha256(p).hexdigest() for p in programs.values()}
    if len(digests) != 1:
        raise SystemExit(f"legacy font subsets differ ({len(digests)} programs); refusing to guess")
    program = next(iter(programs.values()))

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "legacy.ttf"
        path.write_bytes(program)
        font = TTFont(str(path))
        order = font.getGlyphOrder()
        zero_adv = {
            gid for gid, name in enumerate(order)
            if font["hmtx"][name][0] == 0 and font["glyf"][name].numberOfContours != 0
        }
        font.close()

    marks = set()
    for pno in range(doc.page_count):
        for span in doc[pno].get_texttrace():
            if LEGACY_FONT in span["font"]:
                for u, gid, _o, _b in span["chars"]:
                    if gid in zero_adv:
                        marks.add(u)
    return marks, next(iter(digests))


def group_lines(glyphs, marks):
    """[NkoLine(baseline, [codepoints in logical order], (x_min, x_max))], top to bottom.

    glyphs are (x, y, cp[, width, size]); positioned gaps are measured only
    when every glyph on the line has a width."""
    rows: dict[float, list] = {}
    for g in glyphs:
        x, y, cp = g[:3]
        key = next((k for k in rows if abs(k - y) < LINE_TOLERANCE), y)
        rows.setdefault(key, []).append((x, cp, *(g[3:5] if len(g) >= 5 else (None, None))))
    out = []
    for y in sorted(rows):
        row = rows[y]
        xs = [g[0] for g in row]
        measured = all(g[2] is not None and g[3] is not None for g in row)
        out.append(NkoLine(y, order_line([g[:2] for g in row], marks), (min(xs), max(xs)),
                           positioned_gaps(row, marks) if measured else None))
    return out


INDENT_MAX = 20.0               # pt: indented French lines sit ~7-9 pt right of the margin


@dataclass
class RawEntry:
    page: int
    column: int
    index: int                    # margin-headword index within the column; -1 if none
    kind: str                     # 'headword' | 'subentry' | 'orphan_lines'
    headword: str
    baseline: float | None
    lines: list[tuple[float, list[int], tuple[float, float]]]
    sub_index: int = -1           # sub-entry number under its headword
    headword_lines: list[tuple[float, str]] = field(default_factory=list)   # raw French lines
    headword_join: str = "single"  # 'single' | 'wrapped_confirmed' | 'wrapped_unconfirmed'
    french_on_baseline: bool = False   # orphan lines only: French text shares a baseline
    indented_headword: bool = False    # headword found off the column margin (see is_indented_headword)

    @property
    def ref(self) -> str:
        base = f"p{self.page:03d}-c{self.column}-"
        base += f"e{self.index:03d}" if self.index >= 0 else "orphan"
        if self.kind == "subentry":
            return f"{base}-s{self.sub_index:02d}"
        return base

    @property
    def parent_ref(self) -> str | None:
        if self.kind != "subentry" or self.index < 0:
            return None
        return f"p{self.page:03d}-c{self.column}-e{self.index:03d}"


def join_headword_lines(lines: list[str]) -> str:
    """Join a headword wrapped over several lines.

    The raw span text keeps its trailing space: "abreuvage ou " + "abreuvement"
    joins with a space; "anticonstitutionne" + "l,elle", "antigouvernemental,"
    + "e,aux" and "arrière-grands-" + "parents" join directly.
    """
    out, prev = "", None
    for raw in lines:
        piece = raw.strip()
        if prev is not None and prev[-1:].isspace():
            out += " " + piece
        else:
            out += piece
        prev = raw
    return out.strip()


WRAP_JOINERS = {"ou", "de", "du", "des", "d'", "d’", "en", "à", "au", "aux", "et", "la", "le", "les", "un", "une", "par", "pour", "sur"}
SUBENTRY_MARKERS = ("-", "–", "—")
# The dictionary writes the headword inside its sub-entries as a dash:
# "- à coudre", "avoir une jolie -", "s’- de,", "prendre un air –".
HEADWORD_PLACEHOLDER = re.compile(r"(^|[\s’'(])[-–—~](\s|$|[,.;)])")


def is_indented_headword(raw: str, has_pos: bool) -> bool:
    """An indented line that is really a headword set off its margin.

    It carries its own part-of-speech label and is not a sub-entry phrase
    (no leading dash, no dash standing in for the headword). Examples:
    "antisémite" 3.7 pt in on p.41; two text blocks with different margins
    sharing one column on pp.146-147.
    """
    text = raw.strip()
    return has_pos and not text.startswith(SUBENTRY_MARKERS) and not HEADWORD_PLACEHOLDER.search(text)
# A headword broken mid-word ran out of room: "anticonstitutionne" (83 pt) +
# "l,elle". Short lines without a trailing space ("aéroporté", 61 pt) are
# whole words followed by a separate entry.
MIDWORD_MIN_WIDTH = 70.0


def wrap_decision(last_raw: str, last_has_pos: bool, last_width: float, indented_raw: str,
                  joined: str, source_norms: set | None) -> str | None:
    """'wrapped_confirmed' / 'wrapped_unconfirmed' if the indented line continues
    the headword above it, or None if it starts a sub-entry.

    Confirmed: the joined headword exists in data/dictionary.sqlite.
    Unconfirmed: only the line structure says so: the line above ends in '-',
    ',' or a joining word ('ou', 'de', 'en'...), or it is a long line broken
    mid-word (no trailing space, ends in a letter, continuation in lowercase).
    """
    if indented_raw.lstrip().startswith(SUBENTRY_MARKERS) or last_has_pos:
        return None
    if source_norms and normalize_headword(joined) in source_norms:
        return "wrapped_confirmed"
    tail = last_raw.rstrip()
    words = tail.split()
    if tail.endswith(("-", ",")) or (words and words[-1].lower() in WRAP_JOINERS):
        return "wrapped_unconfirmed"
    nxt = indented_raw.lstrip()
    if (not last_raw[-1:].isspace() and tail[-1:].isalpha() and last_width >= MIDWORD_MIN_WIDTH
            and nxt[:1].islower()):
        return "wrapped_unconfirmed"
    return None


def segment_page(page: PageData, marks: set[int], mode: str = "page_margins",
                 source_norms: set | None = None) -> list[RawEntry]:
    """Assign each N'Ko line to the French line whose baseline it follows (same column).

    'page_margins':
      * margin lines start a headword entry;
      * an indented line either continues the headword above it (a wrapped
        headword, see wrap_decision) or starts a sub-entry with its own N'Ko;
      * lines above a column's first French line continue the previous
        column or page; they are kept as 'orphan_lines', never dropped.
    'audit_v1' reproduces the investigation's segmentation exactly.
    """
    if mode == "audit_v1":
        return _segment_audit_v1(page, marks)
    entries: list[RawEntry] = []
    glyphs, _excluded = page_body_glyphs(page, mode)
    body = _body_spans(page)
    for col in (0, 1):
        lines = group_lines([g for g in glyphs if (g[0] < COLUMN_SPLIT_X) == (col == 0)], marks)
        units: list[RawEntry] = []
        spans = body.get(col, [])
        margin = column_margin([x0 for _y, x0, _t in spans]) if spans else 0.0
        head_index, sub_counts = -1, collections.Counter()
        for y, x0, raw in spans:
            if x0 <= margin + MARGIN_TOLERANCE:
                head_index += 1
                units.append(RawEntry(page.number, col, head_index, "headword", raw.strip(), y, [],
                                      headword_lines=[(y, raw)]))
            elif x0 < margin + INDENT_MAX:
                current = units[-1] if units else None
                decision = None
                if current:
                    last_y, last_raw = current.headword_lines[-1]
                    joined = join_headword_lines([t for _y, t in current.headword_lines] + [raw])
                    width = page.line_right.get((col, round(last_y, 1)), margin) - margin
                    decision = wrap_decision(last_raw, _on_baseline(page.pos_baselines, col, last_y),
                                             width, raw, joined, source_norms)
                if decision:
                    current.headword_lines.append((y, raw))
                    current.headword = joined
                    if current.headword_join != "wrapped_unconfirmed":
                        current.headword_join = decision
                elif is_indented_headword(raw, _on_baseline(page.pos_baselines, col, y)):
                    head_index += 1
                    units.append(RawEntry(page.number, col, head_index, "headword", raw.strip(), y, [],
                                          headword_lines=[(y, raw)], indented_headword=True))
                else:
                    sub_counts[head_index] += 1
                    units.append(RawEntry(page.number, col, head_index, "subentry", raw.strip(), y, [],
                                          sub_index=sub_counts[head_index], headword_lines=[(y, raw)]))
        first = units[0].baseline if units else float("inf")
        orphan = [ln for ln in lines if ln[0] < first - LINE_TOLERANCE]
        if orphan:
            french = any(_on_baseline(page.text_baselines, col, y, LINE_TOLERANCE) for y, _c, _x in orphan)
            entries.append(RawEntry(page.number, col, -1, "orphan_lines", "", None, orphan,
                                    french_on_baseline=french))
        for i, unit in enumerate(units):
            nxt = units[i + 1].baseline if i + 1 < len(units) else float("inf")
            unit.lines = [ln for ln in lines if unit.baseline - LINE_TOLERANCE <= ln[0] < nxt - LINE_TOLERANCE]
            entries.append(unit)
    return entries


def _segment_audit_v1(page: PageData, marks: set[int]) -> list[RawEntry]:
    entries = []
    all_heads = page_headwords(page, "audit_v1")
    glyphs, _excluded = page_body_glyphs(page, "audit_v1")
    for col in (0, 1):
        heads = sorted((y, t) for c, y, t in all_heads if c == col)
        lines = group_lines([g for g in glyphs if (g[0] < COLUMN_SPLIT_X) == (col == 0)], marks)
        first = heads[0][0] if heads else float("inf")
        orphan = [ln for ln in lines if ln[0] < first - LINE_TOLERANCE]
        if orphan:
            entries.append(RawEntry(page.number, col, -1, "orphan_lines", "", None, orphan))
        for i, (hy, text) in enumerate(heads):
            ny = heads[i + 1][0] if i + 1 < len(heads) else float("inf")
            mine = [ln for ln in lines if hy - LINE_TOLERANCE <= ln[0] < ny - LINE_TOLERANCE]
            entries.append(RawEntry(page.number, col, i, "headword", text, hy, mine))
    return entries


# --------------------------------------------------------------------------
# Database
# --------------------------------------------------------------------------

SCHEMA = """
CREATE TABLE decoded_entries (
    id                     INTEGER PRIMARY KEY,
    entry_ref              TEXT NOT NULL UNIQUE,
    entry_kind             TEXT NOT NULL CHECK (entry_kind IN ('headword', 'subentry', 'orphan_lines')),
    page_number            INTEGER NOT NULL,
    column_index           INTEGER NOT NULL,
    entry_index            INTEGER NOT NULL,
    sub_index              INTEGER NOT NULL,
    parent_entry_ref       TEXT,
    headword               TEXT NOT NULL,
    headword_normalized    TEXT NOT NULL,
    headword_lines         TEXT NOT NULL,
    headword_join          TEXT NOT NULL CHECK (headword_join IN ('single', 'wrapped_confirmed', 'wrapped_unconfirmed', 'none')),
    headword_baseline_y    REAL,
    line_count             INTEGER NOT NULL,
    line_positions         TEXT NOT NULL,
    legacy_codes           TEXT NOT NULL,
    legacy_text            TEXT NOT NULL,
    alignment              TEXT NOT NULL,
    decoded_nko            TEXT NOT NULL,
    weakest_tier           TEXT NOT NULL CHECK (weakest_tier IN ('STRONG', 'CANDIDATE', 'UNRESOLVED', 'EMPTY')),
    has_candidate_codes    INTEGER NOT NULL,
    has_unresolved_codes   INTEGER NOT NULL,
    candidate_codes        TEXT NOT NULL,
    unresolved_codes       TEXT NOT NULL,
    transformations        TEXT NOT NULL,
    continued_from         TEXT,
    continuation_evidence  TEXT NOT NULL CHECK (continuation_evidence IN
                           ('not_applicable', 'bracket_balance', 'reading_order', 'blank',
                            'french_text_on_baseline', 'no_previous_entry')),
    continued_by           TEXT NOT NULL,
    dictionary_entry_ids   TEXT NOT NULL,
    link_status            TEXT NOT NULL CHECK (link_status IN
                           ('unique', 'senses', 'paired_by_order', 'ambiguous', 'none', 'not_checked')),
    flags                  TEXT NOT NULL,
    status                 TEXT NOT NULL DEFAULT 'machine_decoded' CHECK (status = 'machine_decoded'),
    decoder_version        TEXT NOT NULL,
    mapping_version        TEXT NOT NULL,
    mapping_sha256         TEXT NOT NULL,
    source_pdf_sha256      TEXT NOT NULL
);
CREATE INDEX idx_decoded_headword ON decoded_entries(headword_normalized);
CREATE INDEX idx_decoded_page ON decoded_entries(page_number);
CREATE INDEX idx_decoded_tier ON decoded_entries(weakest_tier);
CREATE INDEX idx_decoded_parent ON decoded_entries(parent_entry_ref);
CREATE TABLE code_inventory (
    codepoint    TEXT PRIMARY KEY,
    handling     TEXT NOT NULL CHECK (handling IN ('STRONG', 'CANDIDATE', 'PASSTHROUGH', 'UNRESOLVED')),
    role         TEXT,
    output       TEXT,
    occurrences  INTEGER NOT NULL
);
CREATE TABLE decode_metadata (
    key    TEXT PRIMARY KEY,
    value  TEXT NOT NULL
);
"""

ENTRY_COLUMNS = (
    "entry_ref", "entry_kind", "page_number", "column_index", "entry_index", "sub_index",
    "parent_entry_ref", "headword", "headword_normalized", "headword_lines", "headword_join",
    "headword_baseline_y", "line_count", "line_positions", "legacy_codes", "legacy_text", "alignment",
    "decoded_nko", "weakest_tier", "has_candidate_codes", "has_unresolved_codes", "candidate_codes",
    "unresolved_codes", "transformations", "continued_from", "continuation_evidence", "continued_by",
    "dictionary_entry_ids", "link_status", "flags", "status", "decoder_version", "mapping_version",
    "mapping_sha256", "source_pdf_sha256",
)


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def normalize_headword(text: str) -> str:
    """Same normalisation as scripts/extract_dictionary.py, so rows can be linked."""
    text = text.lower().strip()
    text = re.sub(r",\s*(e|aux|trice|elle|ve)\b", "", text)
    return " ".join(text.split())


def build_row(entry: RawEntry, mapping: Mapping, pdf_sha: str) -> dict:
    """One database row. Links, continuations and flags are filled in by later passes."""
    decoded = [decode_line(line[1], mapping, li, getattr(line, "gaps", None)) for li, line in enumerate(entry.lines)]
    candidates = sorted({c for d in decoded for c in d.candidate_codes})
    unresolved = sorted({c for d in decoded for c in d.unresolved_codes})
    has_text = entry.kind != "orphan_lines"
    return {
        "entry_ref": entry.ref,
        "entry_kind": entry.kind,
        "page_number": entry.page,
        "column_index": entry.column,
        "entry_index": entry.index,
        "sub_index": entry.sub_index,
        "parent_entry_ref": entry.parent_ref,
        "headword": entry.headword,
        "headword_normalized": normalize_headword(entry.headword) if has_text else "",
        "headword_lines": _json([[round(y, 2), raw] for y, raw in entry.headword_lines]),
        "headword_join": entry.headword_join if has_text else "none",
        "headword_baseline_y": None if entry.baseline is None else round(entry.baseline, 2),
        "line_count": len(entry.lines),
        "line_positions": _json([[round(y, 2), round(x0, 2), round(x1, 2)] for y, _c, (x0, x1) in entry.lines]),
        "legacy_codes": _json([codes for _y, codes, _x in entry.lines]),
        "legacy_text": "\n".join("".join(chr(c) for c in codes) for _y, codes, _x in entry.lines),
        "alignment": _json([d.alignment for d in decoded]),
        "decoded_nko": "\n".join(d.text for d in decoded),
        "weakest_tier": weakest_tier(decoded),
        "has_candidate_codes": int(bool(candidates)),
        "has_unresolved_codes": int(bool(unresolved)),
        "candidate_codes": _json([f"U+{c:04X}" for c in candidates]),
        "unresolved_codes": _json([f"U+{c:04X}" for c in unresolved]),
        "transformations": _json([t for d in decoded for t in d.transformations]),
        "continued_from": None,
        "continuation_evidence": "not_applicable",
        "continued_by": _json([]),
        "dictionary_entry_ids": _json([]),
        "link_status": "not_checked",
        "flags": _json([]),
        "status": STATUS,
        "decoder_version": DECODER_VERSION,
        "mapping_version": mapping.version,
        "mapping_sha256": mapping.sha256,
        "source_pdf_sha256": pdf_sha,
        "_french_on_baseline": entry.french_on_baseline,  # working values, not stored
        "_indented_headword": entry.indented_headword,
    }


def reading_order_key(row: dict) -> tuple:
    """Page, then column, then position down the column (orphan lines first)."""
    y = row["headword_baseline_y"]
    return (row["page_number"], row["column_index"], -1.0 if y is None else y, row["entry_ref"])


def _is_continuation_candidate(row: dict) -> bool:
    return row["entry_kind"] == "orphan_lines" or (
        row["entry_kind"] == "subentry" and row["parent_entry_ref"] is None)


def assign_continuations(rows: list[dict]) -> None:
    """Link text at the top of a column to the entry it continues.

    The previous entry in reading order (the previous column, or the previous
    page's right column) is recorded in `continued_from`, and the entry gets
    the row in `continued_by`. Nothing is merged: each row keeps its own
    source position. Evidence recorded per row:
      bracket_balance          the previous entry leaves '(' open and this row closes it
      reading_order            position only
      blank                    spaces only; not linked
      french_text_on_baseline  French text sits on the same line, so this is
                               probably an unrecognised headword: NOT linked
    """
    by_ref = {r["entry_ref"]: r for r in rows}
    previous = None
    for row in sorted(rows, key=reading_order_key):
        if not _is_continuation_candidate(row):
            previous = row
            continue
        text = row["decoded_nko"]
        if not text.strip():
            row["continuation_evidence"] = "blank"
        elif row.get("_french_on_baseline"):
            row["continuation_evidence"] = "french_text_on_baseline"
        elif previous is None:
            row["continuation_evidence"] = "no_previous_entry"
        else:
            prev_text = previous["decoded_nko"]
            opens = prev_text.count("(") - prev_text.count(")")
            closes = text.count(")") - text.count("(")
            row["continued_from"] = previous["entry_ref"]
            row["continuation_evidence"] = "bracket_balance" if opens > 0 and closes > 0 else "reading_order"
            target = by_ref[previous["entry_ref"]]
            target["continued_by"] = _json(json.loads(target["continued_by"]) + [row["entry_ref"]])


def assign_links(rows: list[dict], source: dict | None) -> None:
    """Link decoded rows to data/dictionary.sqlite rows (read-only).

    source: (page, headword_normalized) -> [(id, sense_number)] in id order.
    Source rows split into occurrences wherever the sense number restarts.
      unique           one decoded row, one source row
      senses           one decoded row, one occurrence with senses 1..n
      paired_by_order  the headword repeats on that page the same number of
                       times on both sides: k-th decoded <-> k-th occurrence
      ambiguous        repeats that cannot be paired; every candidate id listed
      none             not in the source table on that page
    """
    if source is None:
        return
    groups: dict[tuple, list[dict]] = collections.defaultdict(list)
    for row in sorted(rows, key=reading_order_key):
        if row["entry_kind"] != "orphan_lines":
            groups[(row["page_number"], row["headword_normalized"])].append(row)
    for key, decoded in groups.items():
        src = source.get(key, [])
        occurrences: list[list[int]] = []
        last_sense = None
        for rid, sense in src:
            if not occurrences or sense is None or last_sense is None or sense <= last_sense:
                occurrences.append([])
            occurrences[-1].append(rid)
            last_sense = sense
        for k, row in enumerate(decoded):
            if not src:
                ids, status = [], "none"
            elif len(decoded) == 1 and len(occurrences) == 1:
                ids = occurrences[0]
                status = "unique" if len(ids) == 1 else "senses"
            elif len(decoded) == len(occurrences):
                ids, status = occurrences[k], "paired_by_order"
            else:
                ids, status = [rid for rid, _s in src], "ambiguous"
            row["dictionary_entry_ids"] = _json(ids)
            row["link_status"] = status

    # The old text extractor stored one line of a wrapped headword (often the
    # second: "abreuvement" for "abreuvage ou / abreuvement"). Fall back to the
    # individual lines, and flag that the link came from part of the headword.
    for row in rows:
        if row["link_status"] != "none" or not row["headword_join"].startswith("wrapped"):
            continue
        for _y, raw in json.loads(row["headword_lines"]):
            words = raw.split()
            if words and words[-1].lower() in WRAP_JOINERS:
                words = words[:-1]
            src = source.get((row["page_number"], normalize_headword(" ".join(words))), [])
            if src:
                starts = sum(1 for i, (_rid, s) in enumerate(src) if i == 0 or s is None or s <= src[i - 1][1])
                ids = [rid for rid, _s in src]
                row["dictionary_entry_ids"] = _json(ids)
                row["link_status"] = ("unique" if len(ids) == 1 else "senses") if starts == 1 else "ambiguous"
                row["_linked_via_line"] = True
                break


def assign_flags(rows: list[dict]) -> None:
    """Descriptive flags. They never change decoded text."""
    for row in rows:
        flags = []
        if row["entry_kind"] != "orphan_lines":
            hw = row["headword"]
            letters = [c for c in hw if c.isalpha()]
            if not letters:
                flags.append("non_alphabetic_headword")
            elif len(letters) >= 3 and hw.upper() == hw and not row["line_count"]:
                flags.append("caps_catchword")  # running guide word, not an entry
            if not row["line_count"]:
                flags.append("no_nko")
            if row["link_status"] == "none":
                flags.append("headword_not_in_source")
            if row.get("_linked_via_line"):
                flags.append("linked_via_headword_line")
            if row.get("_indented_headword"):
                flags.append("indented_headword")
        if any(t["rule"] == "wide_gap_not_spaced" for t in json.loads(row["transformations"])):
            flags.append("wide_gap_not_spaced")  # a stray fragment far from the rest of the line
        row["flags"] = _json(flags)


def content_digest(conn: sqlite3.Connection) -> str:
    """SHA-256 over every decoded row and inventory row, in a fixed order."""
    h = hashlib.sha256()
    for row in conn.execute(f"SELECT {', '.join(ENTRY_COLUMNS)} FROM decoded_entries ORDER BY entry_ref"):
        h.update(_json(list(row)).encode("utf-8"))
    for row in conn.execute("SELECT * FROM code_inventory ORDER BY codepoint"):
        h.update(_json(list(row)).encode("utf-8"))
    return h.hexdigest()


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------

NKO_VOWELS = {chr(c) for c in range(0x7CA, 0x7D1)} | {"ߒ"}
TONE_MARKS = {chr(c) for c in range(0x7EB, 0x7F4)} - {"߭"}  # dot-above also marks consonants


def orthography_stats(rows: list[dict]) -> dict:
    """Shape-independent checks on the decoded text (before NFC reordering)."""
    on_vowel = total = 0
    wol = collections.Counter()
    for row in rows:
        for line in json.loads(row["alignment"]):
            text = "".join(p for _, p in line)
            prev_base, nasal = None, False
            for ch in text:
                if ch in TONE_MARKS:
                    total += 1
                    on_vowel += prev_base in NKO_VOWELS
                if ch == "߲":
                    nasal = True
                    continue
                if unicodedata.combining(ch) or ch == " ":
                    continue
                if ch in ("ߠ", "ߟ", "ߧ", "ߦ"):
                    wol[(ch, nasal)] += 1
                if ch in NKO_VOWELS:
                    nasal = False
                prev_base = ch
    share = lambda ch: wol[(ch, True)] / max(1, wol[(ch, True)] + wol[(ch, False)])
    return {
        "tone_marks_on_vowels": on_vowel / max(1, total),
        "tone_marks_counted": total,
        "na_woloso_after_nasal": share("ߠ"),
        "la_after_nasal": share("ߟ"),
        "nya_woloso_after_nasal": share("ߧ"),
        "ya_after_nasal": share("ߦ"),
    }


def alphabet_checks(rows: list[dict]) -> list[dict]:
    out = []
    for row in rows:
        h = row["headword"].strip(" ,.")
        if row["entry_kind"] != "headword" or len(h) != 1 or not h.isalpha() or not row["decoded_nko"]:
            continue
        found = alphabet_ordinal(row["decoded_nko"].split("\n")[0])
        if found is None:
            continue
        position = ord(unicodedata.normalize("NFD", h.lower())[0]) - ord("a") + 1
        out.append({"entry_ref": row["entry_ref"], "letter": h, "ordinal": found,
                    "alphabet_position": position, "ok": found == position})
    return out


def validate(rows: list[dict]) -> dict:
    """Build-time invariants. Raises on any violation; returns the measurements."""
    problems = []
    for row in rows:
        align = json.loads(row["alignment"])
        if [rebuild_codes(l) for l in align] != json.loads(row["legacy_codes"]):
            problems.append(f"{row['entry_ref']}: alignment does not rebuild legacy codes")
        if "\n".join(rebuild_text(l) for l in align) != row["decoded_nko"]:
            problems.append(f"{row['entry_ref']}: alignment does not rebuild decoded text")
        if any(is_pua(ch) for ch in row["decoded_nko"]):
            problems.append(f"{row['entry_ref']}: Private Use Area character in decoded output")
        if row["status"] != STATUS:
            problems.append(f"{row['entry_ref']}: status {row['status']!r}")
        for code in json.loads(row["candidate_codes"]) + json.loads(row["unresolved_codes"]):
            if "⟨" + code + "⟩" not in row["decoded_nko"]:
                problems.append(f"{row['entry_ref']}: {code} not visible as a placeholder")
    stats = orthography_stats(rows)
    if stats["tone_marks_counted"] and stats["tone_marks_on_vowels"] < 0.98:
        problems.append(f"tone marks on vowels {stats['tone_marks_on_vowels']:.4f} < 0.98 (ordering regression?)")
    for key in ("na_woloso_after_nasal", "nya_woloso_after_nasal"):
        if stats[key] and stats[key] < 0.90:
            problems.append(f"{key} {stats[key]:.3f} < 0.90")
    alpha = alphabet_checks(rows)
    if any(not a["ok"] for a in alpha):
        problems.append(f"alphabet ordinal mismatch: {[a for a in alpha if not a['ok']]}")
    if problems:
        raise ValueError("validation failed:\n  " + "\n  ".join(problems[:20]))
    return {"orthography": stats, "alphabet_ordinals": alpha}


# --------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------

def sha256_file(path: Path) -> str | None:
    if not path.exists():
        return None
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_source(db_path: Path) -> tuple[dict | None, set | None]:
    """Read data/dictionary.sqlite (read-only).

    Returns ((page, headword_normalized) -> [(id, sense_number)] in id order,
    set of every headword_normalized), or (None, None) if the file is absent.
    """
    if not db_path.exists():
        return None, None
    conn = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    try:
        links = collections.defaultdict(list)
        for rid, page, norm, sense in conn.execute(
            "SELECT id, page_number, headword_normalized, sense_number FROM dictionary_entries ORDER BY id"
        ):
            links[(page, norm)].append((rid, sense))
        return dict(links), {norm for _page, norm in links}
    finally:
        conn.close()


def check_output_path(output: Path) -> None:
    protected = {p.resolve() for p in (DEFAULT_PDF, SOURCE_DB, RAW_JSONL)}
    if output.resolve() in protected:
        raise SystemExit(f"refusing to write over protected source file {output}")
    if output.exists():
        try:
            conn = sqlite3.connect(f"file:{output.as_posix()}?mode=ro", uri=True)
            tool = conn.execute("SELECT value FROM decode_metadata WHERE key = 'tool'").fetchone()
            conn.close()
        except sqlite3.Error:
            tool = None
        if not tool or tool[0] != TOOL_NAME:
            raise SystemExit(f"{output} exists and was not produced by {TOOL_NAME}; refusing to replace it")


def write_database(output: Path, rows: list[dict], inventory: list[tuple], metadata: dict) -> str:
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp = output.with_name(output.name + ".tmp")
    if tmp.exists():
        tmp.unlink()
    conn = sqlite3.connect(str(tmp))
    try:
        conn.executescript(SCHEMA)
        conn.executemany(
            f"INSERT INTO decoded_entries ({', '.join(ENTRY_COLUMNS)}) VALUES ({', '.join('?' * len(ENTRY_COLUMNS))})",
            [tuple(r[c] for c in ENTRY_COLUMNS) for r in rows],
        )
        conn.executemany("INSERT INTO code_inventory VALUES (?, ?, ?, ?, ?)", inventory)
        conn.commit()
        digest = content_digest(conn)
        meta = dict(metadata, content_sha256=digest)
        conn.executemany("INSERT INTO decode_metadata VALUES (?, ?)",
                         [(k, v if isinstance(v, str) else _json(v)) for k, v in sorted(meta.items())])
        conn.commit()
    finally:
        conn.close()
    os.replace(tmp, output)
    return digest


def parse_pages(spec: str | None, page_count: int) -> list[int]:
    if not spec:
        return list(range(FIRST_BODY_PAGE, page_count + 1))
    pages = set()
    for part in spec.split(","):
        lo, _, hi = part.partition("-")
        pages.update(range(int(lo), int(hi or lo) + 1))
    bad = [p for p in pages if p < FIRST_BODY_PAGE or p > page_count]
    if bad:
        raise SystemExit(f"pages out of range {FIRST_BODY_PAGE}..{page_count}: {sorted(bad)[:5]}")
    return sorted(pages)


def run(pdf: Path, mapping_path: Path, output: Path, pages: str | None = None,
        allow_pdf_mismatch: bool = False) -> dict:
    import fitz

    protected_before = {str(p): sha256_file(p) for p in (pdf, SOURCE_DB, RAW_JSONL)}
    mapping = load_mapping(mapping_path)
    pdf_sha = protected_before[str(pdf)]
    if pdf_sha != mapping.source_pdf_sha256 and not allow_pdf_mismatch:
        raise SystemExit(f"PDF hash {pdf_sha} differs from the mapping's {mapping.source_pdf_sha256}")
    check_output_path(output)

    doc = fitz.open(str(pdf))
    page_list = parse_pages(pages, doc.page_count)
    marks, font_sha = legacy_font_marks(doc)
    mapped_marks = {cp for cp, i in mapping.codes.items() if i["role"] in ("mark", "composite_mark")}
    if marks != mapped_marks:
        raise SystemExit(
            "zero-advance glyphs in the font disagree with the mapping's mark roles: "
            f"font-only {sorted(hex(c) for c in marks - mapped_marks)}, "
            f"mapping-only {sorted(hex(c) for c in mapped_marks - marks)}"
        )

    source, source_norms = load_source(SOURCE_DB)
    raw_entries, excluded, audit_tiers = [], collections.Counter(), collections.Counter()
    for pno in page_list:
        page = extract_page(doc[pno - 1], pno)
        excluded.update(page_body_glyphs(page, "page_margins")[1])
        raw_entries.extend(segment_page(page, marks, "page_margins", source_norms))
        for e in segment_page(page, marks, "audit_v1"):
            if e.kind == "headword" and e.lines:
                audit_tiers[weakest_tier([decode_line(c, mapping) for _y, c, _x in e.lines])] += 1
    doc.close()

    rows = [build_row(e, mapping, pdf_sha) for e in raw_entries]
    assign_continuations(rows)
    assign_links(rows, source)
    assign_flags(rows)
    for row in rows:
        row.pop("_french_on_baseline", None)
        row.pop("_linked_via_line", None)
        row.pop("_indented_headword", None)
    rows.sort(key=lambda r: r["entry_ref"])
    measurements = validate(rows)

    occ = collections.Counter(c for r in rows for line in json.loads(r["legacy_codes"]) for c in line)
    inventory = []
    for cp in sorted(occ):
        if cp in mapping.codes:
            info = mapping.codes[cp]
            handling, role = info["tier"], info["role"]
            output_text = info["unicode"] if handling == "STRONG" else PLACEHOLDER.format(cp)
        elif cp in mapping.passthrough:
            handling, role, output_text = "PASSTHROUGH", mapping.passthrough[cp]["role"], mapping.passthrough[cp]["output"]
        else:
            handling, role, output_text = "UNRESOLVED", None, PLACEHOLDER.format(cp)
        inventory.append((f"U+{cp:04X}", handling, role, output_text, occ[cp]))

    headword_rows = [r for r in rows if r["entry_kind"] == "headword"]
    sub_rows = [r for r in rows if r["entry_kind"] == "subentry"]
    orphan_rows = [r for r in rows if r["entry_kind"] == "orphan_lines"]
    with_nko = [r for r in headword_rows if r["line_count"]]
    tiers = collections.Counter(r["weakest_tier"] for r in with_nko)
    count = lambda rs, key: dict(sorted(collections.Counter(r[key] for r in rs).items()))
    summary = {
        "headword_entries": len(headword_rows),
        "headword_entries_with_nko": len(with_nko),
        "subentries": len(sub_rows),
        "orphan_line_groups": len(orphan_rows),
        "entries_by_weakest_tier": dict(sorted(tiers.items())),
        "strong_entry_coverage": round(tiers["STRONG"] / max(1, len(with_nko)), 6),
        "subentries_by_weakest_tier": count([r for r in sub_rows if r["line_count"]], "weakest_tier"),
        "headword_join": count(headword_rows + sub_rows, "headword_join"),
        "continuation_evidence": count([r for r in rows if _is_continuation_candidate(r)], "continuation_evidence"),
        "link_status": count(headword_rows, "link_status"),
        "subentry_link_status": count(sub_rows, "link_status"),
        "flags": dict(sorted(collections.Counter(f for r in rows for f in json.loads(r["flags"])).items())),
        "transformations": dict(sorted(collections.Counter(
            t["rule"] for r in rows for t in json.loads(r["transformations"])).items())),
        "glyphs_by_handling": dict(sorted(sum(
            (collections.Counter({h: n}) for (_cp, h, _r, _o, n) in inventory), collections.Counter()).items())),
    }
    metadata = {
        "tool": TOOL_NAME,
        "decoder_version": DECODER_VERSION,
        "status_of_all_rows": STATUS,
        "status_note": "Machine-decoded, NOT human-verified. Coverage measures mapping coverage, not linguistic accuracy.",
        "mapping_file": mapping_path.name,
        "mapping_version": mapping.version,
        "mapping_sha256": mapping.sha256,
        "source_pdf": pdf.name,
        "source_pdf_sha256": pdf_sha,
        "legacy_font_program_sha256": font_sha,
        "pages": f"{page_list[0]}-{page_list[-1]}" if page_list == list(range(page_list[0], page_list[-1] + 1)) else _json(page_list),
        "segmentation": "page_margins",
        "header_area_glyphs_excluded": {f"U+{k:04X}": v for k, v in sorted(excluded.items())},
        "summary": summary,
        "audit_v1_regression": {
            "note": "Same pages segmented with the investigation/audit heuristic (fixed margins, header at 85, "
                    "Manden only). Reproduces the audited coverage; it is NOT the decoder's output.",
            "headword_entries_with_nko": sum(audit_tiers.values()),
            "entries_by_weakest_tier": dict(sorted(audit_tiers.items())),
            "strong_entry_coverage": round(audit_tiers["STRONG"] / max(1, sum(audit_tiers.values())), 6),
        },
        "validation": measurements,
    }
    digest = write_database(output, rows, inventory, metadata)

    protected_after = {str(p): sha256_file(p) for p in (pdf, SOURCE_DB, RAW_JSONL)}
    if protected_after != protected_before:
        raise SystemExit("a protected source file changed during the run")
    return {"output": str(output), "content_sha256": digest, "summary": summary,
            "validation": {"orthography": measurements["orthography"],
                           "alphabet_ordinals_ok": sum(a["ok"] for a in measurements["alphabet_ordinals"]),
                           "alphabet_ordinals_found": len(measurements["alphabet_ordinals"])},
            "protected_hashes": protected_after}


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pdf", type=Path, default=DEFAULT_PDF)
    ap.add_argument("--mapping", type=Path, default=DEFAULT_MAPPING)
    ap.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    ap.add_argument("--pages", help="e.g. 22-30 or 22,40-41 (default: all body pages). Continuation links "
                                    "across page boundaries are only complete in a full build.")
    ap.add_argument("--allow-pdf-mismatch", action="store_true",
                    help="decode even if the PDF hash differs from the one the mapping was built on")
    args = ap.parse_args()
    result = run(args.pdf, args.mapping, args.output, args.pages, args.allow_pdf_mismatch)
    print(json.dumps(result, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
