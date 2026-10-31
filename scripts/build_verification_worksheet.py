"""Build a human-verification worksheet for recovering the legacy N'Ko encoding.

READ-ONLY. This script never writes outside data/glyph_evidence/ and never
modifies the PDF, the SQLite database, the extracted JSONL, the application
code, or any existing mapping.

It produces nothing verified. It only assembles the evidence a literate N'Ko
reader needs in order to answer the question we cannot answer ourselves:
which Unicode N'Ko characters do these legacy glyphs represent?

For each selected dictionary entry the worksheet shows:
  * the French headword, part of speech and dictionary page
  * a high-resolution crop of the ORIGINAL PRINTED entry from the PDF
  * the Private Use Area codepoint sequence exactly as the PDF stores it
  * each codepoint's structural classification, derived from font metrics
    (space / combining mark / base glyph) -- never from visual similarity
  * an empty field for the reviewer to type the Unicode N'Ko

Entries are chosen greedily to cover the most frequent legacy codepoints, so a
small worksheet accounts for a large share of the dictionary.

Usage (from the repository root):

    python scripts/build_verification_worksheet.py
    python scripts/build_verification_worksheet.py --entries 20

Requirements: pymupdf, fonttools (see scripts/requirements-extraction.txt).
"""

from __future__ import annotations

import argparse
import base64
import collections
import hashlib
import html
import json
import sqlite3
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PDF_PATH = REPO_ROOT / "docs" / "dictionnaire Fr_nko.pdf"
DB_PATH = REPO_ROOT / "data" / "dictionary.sqlite"
JSONL_PATH = REPO_ROOT / "data" / "raw_extraction.jsonl"
OUT_DIR = REPO_ROOT / "data" / "glyph_evidence"
CROP_DIR = OUT_DIR / "crops"

PUA_START, PUA_END = 0xE000, 0xF8FF
NKO_START, NKO_END = 0x07C0, 0x07FF

# Page geometry of this PDF: US Letter, two columns.
COLUMN_GUTTER = 295.0
COLUMNS = {"L": (96.0, 292.0), "R": (298.0, 500.0)}

# Recognisable words a reviewer can confirm at a glance. Used as seeds; the
# rest of the worksheet is chosen purely by codepoint coverage.
SEED_WORDS = ["eau", "maison", "manger", "bonjour"]

# The only legacy codepoints recovered so far. Everything else is UNKNOWN.
# U+F120: no glyph outline, positive advance width, legacy byte 0x20, 16.2% of
# all characters -- it is the space.
RECOVERED: dict[int, str] = {0xF120: " "}


def is_pua(cp: int) -> bool:
    return PUA_START <= cp <= PUA_END


# --------------------------------------------------------------------------
# Evidence gathering (all read-only)
# --------------------------------------------------------------------------


def pua_frequencies(jsonl_path: Path) -> collections.Counter:
    """Count every legacy codepoint across the whole extraction."""
    counter: collections.Counter = collections.Counter()
    with jsonl_path.open(encoding="utf-8") as handle:
        for line in handle:
            target = json.loads(line).get("raw_target") or ""
            counter.update(ch for ch in target if is_pua(ord(ch)))
    return counter


def extract_legacy_font(pdf) -> bytes | None:
    """Pull the embedded legacy font program out of the PDF (in memory)."""
    for page_no in range(min(pdf.page_count, 80)):
        for info in pdf.get_page_fonts(page_no, full=True):
            if "Manden" in info[3]:
                return pdf.extract_font(info[0])[3]
    return None


def classify_codepoints(font_bytes: bytes, tounicode: dict[int, str]) -> dict[int, str]:
    """Classify each legacy codepoint by FONT METRICS, not by appearance.

    A glyph with no outline but positive advance is a space. A glyph with an
    outline but zero advance width is a combining mark. Anything else is a base
    glyph. This says what KIND of character it is; it never says WHICH.
    """
    import io

    from fontTools.pens.boundsPen import BoundsPen
    from fontTools.ttLib import TTFont

    font = TTFont(io.BytesIO(font_bytes), lazy=True)
    glyph_set = font.getGlyphSet()
    order = font.getGlyphOrder()
    hmtx = font["hmtx"]

    by_unicode = {value.upper(): cid for cid, value in tounicode.items()}
    classes: dict[int, str] = {}
    for hex_value, cid in by_unicode.items():
        try:
            cp = int(hex_value, 16)
        except ValueError:
            continue
        if not is_pua(cp) or cid >= len(order):
            continue
        name = order[cid]
        pen = BoundsPen(glyph_set)
        glyph_set[name].draw(pen)
        advance = hmtx[name][0]
        if pen.bounds is None:
            classes[cp] = "space"
        elif advance == 0:
            classes[cp] = "combining mark"
        else:
            classes[cp] = "base glyph"
    return classes


def read_tounicode(pdf) -> dict[int, str]:
    """CID -> ToUnicode hex for the legacy font, read from the PDF itself."""
    import re
    import zlib

    data = PDF_PATH.read_bytes()
    positions = {
        int(m.group(1)): m.end()
        for m in re.finditer(rb"(?:^|[\r\n\s])(\d+)\s+(\d+)\s+obj\b", data)
    }

    def header_and_stream(num: int):
        start = positions.get(num)
        if start is None:
            return b"", None
        match = re.compile(rb"stream\r?\n").search(data, start)
        if not match:
            end = data.find(b"endobj", start)
            return data[start : end if end > 0 else start], None
        header = data[start : match.start()]
        raw = data[match.end() : data.find(b"endstream", match.end())]
        if b"FlateDecode" in header:
            try:
                raw = zlib.decompressobj().decompress(raw)
            except Exception:
                return header, None
        return header, raw

    objects: dict[int, bytes] = {}
    for num in list(positions):
        header, body = header_and_stream(num)
        if body is None or b"/ObjStm" not in header:
            continue
        count = int(re.search(rb"/N\s+(\d+)", header).group(1))
        first = int(re.search(rb"/First\s+(\d+)", header).group(1))
        nums = list(map(int, body[:first].split()))
        pairs = [(nums[i], nums[i + 1]) for i in range(0, 2 * count, 2)]
        for i, (onum, off) in enumerate(pairs):
            end = pairs[i + 1][1] if i + 1 < len(pairs) else len(body) - first
            objects[onum] = body[first + off : first + end]

    cmap: dict[int, str] = {}
    for body in objects.values():
        if b"/Type0" not in body or b"Manden" not in body:
            continue
        ref = re.search(rb"/ToUnicode\s+(\d+)\s+\d+\s+R", body)
        if not ref:
            continue
        payload = header_and_stream(int(ref.group(1)))[1]
        if not payload:
            continue
        text = payload.decode("latin1", errors="replace")
        for block in re.findall(r"beginbfchar(.*?)endbfchar", text, re.S):
            for src, dst in re.findall(r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", block):
                cmap[int(src, 16)] = dst.upper()
        for block in re.findall(r"beginbfrange(.*?)endbfrange", text, re.S):
            for lo, hi, dst in re.findall(
                r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", block
            ):
                for i in range(int(hi, 16) - int(lo, 16) + 1):
                    cmap[int(lo, 16) + i] = "%04X" % (int(dst, 16) + i)
        # Do not stop at the first subset: the PDF embeds more than one, and
        # each covers a different slice of the alphabet. Merging them lets
        # every codepoint be classified.
    return cmap


# --------------------------------------------------------------------------
# Locating an entry in the printed page
# --------------------------------------------------------------------------


@dataclass
class Entry:
    headword: str
    pos: str | None
    page_number: int
    db_raw_target: str
    pdf_sequence: str = ""
    crop_file: str = ""
    crop_b64: str = ""
    column: str = ""
    pua_codepoints: list[int] = field(default_factory=list)


def locate_entry(pdf, headword: str, page_number: int, pos: str | None = None):
    """Find the printed line for `headword`, restricted to its own column.

    The dictionary is two-column; without the column restriction the
    neighbouring column's N'Ko bleeds in and the sequence stops matching the
    image.
    """
    import fitz

    if not (1 <= page_number <= pdf.page_count):
        return None
    page = pdf[page_number - 1]
    best = None
    page_dict = page.get_text("dict")
    for rect in page.search_for(headword):
        column = "L" if rect.x0 < COLUMN_GUTTER else "R"
        cx0, cx1 = COLUMNS[column]
        # The headword must begin the entry, i.e. sit at the column's edge.
        if rect.x0 - cx0 > 25:
            continue
        spans = []
        for block in page_dict["blocks"]:
            for line in block.get("lines", []):
                for span in line["spans"]:
                    bbox = span["bbox"]
                    if (
                        abs(bbox[1] - rect.y0) < 5
                        and cx0 - 4 <= bbox[0] <= cx1
                        and "Manden" in span["font"]
                        and span["text"].strip()
                    ):
                        spans.append(span)
        if not spans:
            continue
        # A headword can appear several times on a page, once per part of
        # speech. Pick the line whose POS matches the database row, so the
        # boxed line is the entry the worksheet claims it is.
        line_text = "".join(
            span["text"]
            for block in page_dict["blocks"]
            for line in block.get("lines", [])
            for span in line["spans"]
            if abs(span["bbox"][1] - rect.y0) < 5
            and cx0 - 4 <= span["bbox"][0] <= cx1
            and "Manden" not in span["font"]
        )
        score = (2 if pos and pos in line_text else 0, len(spans))
        if best is None or score > best[3]:
            best = (rect, spans, column, score)
    if best is None:
        return None

    rect, spans, column, _score = best
    y0 = min([rect.y0] + [s["bbox"][1] for s in spans])
    y1 = max([rect.y1] + [s["bbox"][3] for s in spans])
    cx0, cx1 = COLUMNS[column]
    clip = fitz.Rect(cx0 - 6, y0 - 4, cx1 + 6, y1 + 4)
    sequence = "".join(s["text"] for s in spans)
    # The N'Ko glyphs stand ~24pt tall on a ~15pt line, so neighbouring
    # entries always intrude into a readable crop. Rather than crop tighter
    # and clip the tone marks, hand back the target band so it can be marked.
    target = fitz.Rect(
        min([rect.x0] + [s["bbox"][0] for s in spans]),
        y0,
        max([rect.x1] + [s["bbox"][2] for s in spans]),
        y1,
    )
    return clip, sequence, column, target


def render_crop(pdf, page_number: int, clip, target, scale: float = 4.0) -> bytes:
    """Render the crop and outline the line the reviewer must transcribe.

    The outline is drawn on the rendered image only. The PDF is never touched.
    """
    import io

    import fitz
    from PIL import Image, ImageDraw

    pixmap = pdf[page_number - 1].get_pixmap(matrix=fitz.Matrix(scale, scale), clip=clip)
    image = Image.open(io.BytesIO(pixmap.tobytes("png"))).convert("RGB")

    box = [
        (target.x0 - clip.x0) * scale,
        (target.y0 - clip.y0) * scale,
        (target.x1 - clip.x0) * scale,
        (target.y1 - clip.y0) * scale,
    ]
    # Dim everything outside the target band so the eye goes to the right line.
    overlay = Image.new("RGBA", image.size, (255, 255, 255, 170))
    ImageDraw.Draw(overlay).rectangle(box, fill=(255, 255, 255, 0))
    image = Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB")
    ImageDraw.Draw(image).rectangle(box, outline=(31, 111, 235), width=3)

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


# --------------------------------------------------------------------------
# Selection
# --------------------------------------------------------------------------


def load_candidates(db_path: Path, limit: int = 4000) -> list[Entry]:
    """Candidate entries, preferring ones with substantial N'Ko content."""
    conn = sqlite3.connect(str(db_path))
    rows = conn.execute(
        """
        SELECT headword, pos, page_number, raw_target
        FROM dictionary_entries
        WHERE raw_target IS NOT NULL AND length(raw_target) >= 6
          AND sense_number = 1
        ORDER BY length(raw_target) DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    conn.close()
    return [Entry(headword=r[0], pos=r[1], page_number=r[2], db_raw_target=r[3]) for r in rows]


def seed_entries(db_path: Path) -> list[Entry]:
    conn = sqlite3.connect(str(db_path))
    found: list[Entry] = []
    for word in SEED_WORDS:
        row = conn.execute(
            """
            SELECT headword, pos, page_number, raw_target
            FROM dictionary_entries
            WHERE headword_normalized = ?
            ORDER BY sense_number LIMIT 1
            """,
            (word,),
        ).fetchone()
        if row:
            found.append(Entry(headword=row[0], pos=row[1], page_number=row[2], db_raw_target=row[3]))
    conn.close()
    return found


def select_entries(pdf, db_path: Path, freq: collections.Counter, target: int) -> list[Entry]:
    """Greedy set cover: each pick maximises newly covered codepoint frequency."""
    chosen: list[Entry] = []
    covered: set[int] = set()

    def finalise(entry: Entry) -> bool:
        located = locate_entry(pdf, entry.headword, entry.page_number, entry.pos)
        if located is None:
            return False
        clip, sequence, column, target = located
        codepoints = [ord(c) for c in sequence if is_pua(ord(c))]
        if not codepoints:
            return False
        entry.pdf_sequence = sequence
        entry.pua_codepoints = codepoints
        entry.column = column
        png = render_crop(pdf, entry.page_number, clip, target)
        CROP_DIR.mkdir(parents=True, exist_ok=True)
        safe = "".join(ch if ch.isalnum() else "_" for ch in entry.headword)[:30]
        name = f"p{entry.page_number:03d}_{safe}.png"
        (CROP_DIR / name).write_bytes(png)
        entry.crop_file = f"crops/{name}"
        entry.crop_b64 = base64.b64encode(png).decode("ascii")
        return True

    for entry in seed_entries(db_path):
        if len(chosen) >= target:
            break
        if finalise(entry):
            chosen.append(entry)
            covered.update(entry.pua_codepoints)

    candidates = load_candidates(db_path)
    weight = {ord(ch): n for ch, n in freq.items()}
    while len(chosen) < target and candidates:
        best_entry, best_gain, best_index = None, 0, -1
        for index, cand in enumerate(candidates):
            cps = {ord(c) for c in cand.db_raw_target if is_pua(ord(c))}
            gain = sum(weight.get(cp, 0) for cp in cps - covered)
            if gain > best_gain:
                best_entry, best_gain, best_index = cand, gain, index
        if best_entry is None:
            break
        candidates.pop(best_index)
        if finalise(best_entry):
            chosen.append(best_entry)
            covered.update(best_entry.pua_codepoints)
    return chosen


# --------------------------------------------------------------------------
# HTML
# --------------------------------------------------------------------------


def build_html(entries, classes, freq, pdf_sha, coverage) -> str:
    total = sum(freq.values())
    esc = html.escape

    def chip(cp: int) -> str:
        label = f"U+{cp:04X}"
        if cp in RECOVERED:
            return (
                f'<span class="cp recovered" title="Recovered: space">{label}'
                f'<em>space</em></span>'
            )
        kind = classes.get(cp, "unclassified")
        css = {"combining mark": "mark", "base glyph": "base", "space": "space"}.get(kind, "unk")
        return f'<span class="cp {css}" title="{kind} - identity UNKNOWN">{label}<em>{kind} · UNKNOWN</em></span>'

    rows = []
    for i, e in enumerate(entries, 1):
        chips = "".join(chip(cp) for cp in e.pua_codepoints)
        unknown = sum(1 for cp in e.pua_codepoints if cp not in RECOVERED)
        rows.append(f"""
<section class="entry">
  <h2><span class="num">{i}</span> {esc(e.headword)}
      <span class="pos">{esc(e.pos or '')}</span>
      <span class="page">dictionary p.{e.page_number} ({'left' if e.column=='L' else 'right'} column)</span></h2>

  <div class="label">Original printed entry — transcribe the <strong>boxed line only</strong> (image from the PDF; this is the ground truth)</div>
  <img src="data:image/png;base64,{e.crop_b64}" alt="printed entry for {esc(e.headword)}">

  <div class="label">Legacy codepoints as stored in the PDF
      <span class="muted">({len(e.pua_codepoints)} characters, {unknown} UNKNOWN)</span></div>
  <div class="cps">{chips}</div>

  <div class="label">Reviewer: type the Unicode N'Ko for this entry</div>
  <textarea class="answer nko" rows="2" placeholder="Type the N'Ko here, exactly as printed above…"></textarea>
  <div class="label">Notes / uncertainty (optional)</div>
  <textarea class="notes" rows="2" placeholder="Anything unclear, ambiguous, or illegible…"></textarea>
</section>""")

    cov_rows = "".join(
        f"<tr><td>U+{cp:04X}</td><td>{classes.get(cp,'unclassified')}</td>"
        f"<td>{freq.get(chr(cp),0):,}</td><td>{freq.get(chr(cp),0)/total:.2%}</td>"
        f"<td>{'space (recovered)' if cp in RECOVERED else 'UNKNOWN'}</td></tr>"
        for cp in sorted(coverage, key=lambda c: -freq.get(chr(c), 0))
    )

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>N'Ko Encoding Verification Worksheet</title>
<style>
:root {{ --bg:#f6f7f9; --surface:#fff; --border:#dfe3e8; --text:#15181d; --muted:#667; --accent:#1f6feb; }}
@media (prefers-color-scheme:dark) {{
  :root {{ --bg:#0f1216; --surface:#171b21; --border:#2a313a; --text:#e7eaee; --muted:#95a0ac; --accent:#4f8ff5; }}
}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--text);
 font-family:Inter,-apple-system,"Segoe UI",Roboto,sans-serif;line-height:1.5}}
.wrap{{max-width:980px;margin:0 auto;padding:28px 16px 64px}}
h1{{font-size:1.6rem;margin:0 0 4px}}
.sub{{color:var(--muted);margin:0 0 20px}}
.card{{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:16px 18px;margin-bottom:18px}}
.warn{{border-left:4px solid #d9822b}}
.entry{{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:16px 18px;margin-bottom:18px}}
.entry h2{{font-size:1.1rem;margin:0 0 12px;display:flex;align-items:center;gap:10px;flex-wrap:wrap}}
.num{{background:var(--accent);color:#fff;border-radius:50%;width:26px;height:26px;
 display:inline-flex;align-items:center;justify-content:center;font-size:.82rem;flex:0 0 auto}}
.pos{{font-style:italic;color:var(--muted);font-weight:400;font-size:.9rem}}
.page{{margin-left:auto;font-size:.8rem;color:var(--muted);font-weight:400}}
.label{{font-size:.76rem;text-transform:uppercase;letter-spacing:.04em;color:var(--muted);
 margin:14px 0 6px;font-weight:600}}
.muted{{text-transform:none;letter-spacing:0;font-weight:400}}
img{{max-width:100%;border:1px solid var(--border);border-radius:6px;background:#fff;display:block}}
.cps{{display:flex;flex-wrap:wrap;gap:5px}}
.cp{{display:inline-flex;flex-direction:column;align-items:center;font-family:ui-monospace,Consolas,monospace;
 font-size:.72rem;padding:4px 7px;border-radius:5px;border:1px solid var(--border);background:var(--bg)}}
.cp em{{font-style:normal;font-size:.62rem;color:var(--muted);margin-top:2px}}
.cp.mark{{border-color:#9b59b6}} .cp.base{{border-color:#2d8}} .cp.space{{border-color:#888;opacity:.65}}
.cp.recovered{{border-color:#2d8;background:rgba(40,200,120,.12)}}
textarea{{width:100%;padding:10px 12px;border:1px solid var(--border);border-radius:7px;
 background:var(--bg);color:var(--text);font-family:inherit;font-size:1rem;resize:vertical}}
.nko{{font-family:"Noto Sans NKo",Ebrima,Conakry,sans-serif;font-size:1.5rem;line-height:2;direction:rtl;text-align:right}}
table{{width:100%;border-collapse:collapse;font-size:.85rem}}
th,td{{text-align:left;padding:6px 8px;border-bottom:1px solid var(--border)}}
th{{font-size:.74rem;text-transform:uppercase;letter-spacing:.04em;color:var(--muted)}}
code{{background:rgba(127,127,127,.15);padding:1px 5px;border-radius:4px;font-size:.88em}}
ol,ul{{padding-left:20px}} li{{margin:5px 0}}
</style></head><body><div class="wrap">

<h1>N'Ko Encoding Verification Worksheet</h1>
<p class="sub">Proof of concept — {len(entries)} entries from <em>Dictionnaire Bilingue Français&nbsp;–&nbsp;N'Ko</em>
(Baba Mamadi Diané, 2014). Generated for human review.</p>

<div class="card warn">
<strong>Nothing in this worksheet is verified.</strong>
<p>The dictionary's N'Ko is stored in a legacy font (<code>N'ko2Manden-1saDofanen</code>) whose
characters land in the Unicode Private Use Area. The embedded font contains no
<code>cmap</code> and no glyph names, so the PDF does not record which letters these are.</p>
<p>Every codepoint below is marked <strong>UNKNOWN</strong> except the space, which is
established by three independent signals (no glyph outline, positive advance width,
legacy byte <code>0x20</code>, 16.2% of all characters). Classifications such as
“base glyph” or “combining mark” come from <strong>font metrics only</strong> — they say what
<em>kind</em> of character it is, never <em>which</em> character. No identity has been
guessed from visual similarity.</p>
</div>

<div class="card">
<strong>How to complete this worksheet</strong>
<ol>
<li>For each entry, read the <strong>printed image</strong> — that is the authority, not the codepoints.</li>
<li>Type the N'Ko into the answer box using a standard Unicode N'Ko keyboard.</li>
<li>Transcribe exactly what is printed, including tone marks. Do not correct spelling or modernise.</li>
<li>If any part is unclear or illegible, say so in the notes and leave it out rather than guessing.</li>
<li>Save the page when done (<code>Ctrl&nbsp;+&nbsp;S</code>), or copy each answer into a plain text file
    numbered to match.</li>
</ol>
<p class="sub">A mapping will only be derived after the answers come back, and only where a
transcription aligns unambiguously with its codepoint sequence. Anything ambiguous stays UNKNOWN,
and every derived mapping must then be cross-validated against entries the reviewer has not seen.</p>
</div>

<div class="card">
<strong>Coverage</strong>
<p class="sub">These {len(entries)} entries contain {len(coverage)} distinct legacy codepoints,
accounting for <strong>{sum(freq.get(chr(c),0) for c in coverage)/total:.1%}</strong>
of all N'Ko characters in the 32,057-entry dictionary.</p>
<table><thead><tr><th>Codepoint</th><th>Class (from metrics)</th><th>Occurrences</th><th>Share</th><th>Identity</th></tr></thead>
<tbody>{cov_rows}</tbody></table>
</div>

{''.join(rows)}

<div class="card">
<strong>Provenance</strong>
<ul>
<li>Source PDF SHA-256: <code>{pdf_sha}</code> (unmodified)</li>
<li>Images rendered directly from the PDF at 4× scale; no OCR, no reconstruction.</li>
<li>Codepoint sequences taken from the PDF's own text layer for the same printed line.</li>
</ul>
</div>

</div></body></html>"""


# --------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--entries", type=int, default=15, help="how many entries (default 15)")
    parser.add_argument("--out", type=Path, default=OUT_DIR / "verification_worksheet.html")
    args = parser.parse_args()

    for path, label in ((PDF_PATH, "PDF"), (DB_PATH, "database"), (JSONL_PATH, "raw extraction")):
        if not path.exists():
            print(f"Missing {label}: {path}", file=sys.stderr)
            return 1

    try:
        import fitz
    except ImportError:
        print(
            "pymupdf is required: pip install -r scripts/requirements-extraction.txt",
            file=sys.stderr,
        )
        return 1

    pdf_sha = hashlib.sha256(PDF_PATH.read_bytes()).hexdigest()
    print(f"PDF sha256 : {pdf_sha}")

    freq = pua_frequencies(JSONL_PATH)
    total = sum(freq.values())
    print(f"corpus     : {len(freq)} distinct legacy codepoints, {total:,} occurrences")

    pdf = fitz.open(str(PDF_PATH))
    tounicode = read_tounicode(pdf)
    font_bytes = extract_legacy_font(pdf)
    classes = classify_codepoints(font_bytes, tounicode) if font_bytes else {}
    print(f"classified : {len(classes)} codepoints by font metrics")

    entries = select_entries(pdf, DB_PATH, freq, args.entries)
    if not entries:
        print("No entries could be located in the PDF.", file=sys.stderr)
        return 1

    coverage = sorted({cp for e in entries for cp in e.pua_codepoints})
    share = sum(freq.get(chr(cp), 0) for cp in coverage) / total

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        build_html(entries, classes, freq, pdf_sha, coverage), encoding="utf-8"
    )

    summary = {
        "pdf_sha256": pdf_sha,
        "generated_entries": len(entries),
        "distinct_codepoints_covered": len(coverage),
        "corpus_share_covered": round(share, 4),
        "verified_mappings_produced": 0,
        "entries": [
            {
                "headword": e.headword,
                "pos": e.pos,
                "page": e.page_number,
                "codepoints": [f"U+{cp:04X}" for cp in e.pua_codepoints],
                "crop": e.crop_file,
            }
            for e in entries
        ],
    }
    (OUT_DIR / "worksheet_manifest.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print(f"\nentries    : {len(entries)}")
    print(f"coverage   : {len(coverage)} distinct codepoints = {share:.1%} of all N'Ko characters")
    print(f"worksheet  : {args.out}")
    print(f"crops      : {CROP_DIR}")
    print(f"manifest   : {OUT_DIR / 'worksheet_manifest.json'}")
    print("\nNo mapping was created. Nothing is marked verified.")

    after = hashlib.sha256(PDF_PATH.read_bytes()).hexdigest()
    print(f"PDF unchanged: {after == pdf_sha}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
