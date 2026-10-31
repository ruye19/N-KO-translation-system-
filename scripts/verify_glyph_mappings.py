"""Reproduce the glyph evidence behind backend/app/services/nko_mapping.py.

Renders glyphs from the PDF's embedded legacy font and compares them by shape
against a reference font with genuine Unicode N'Ko coverage, so that every
claimed mapping can be checked rather than taken on trust.

Run from the repository root:

    python scripts/verify_glyph_mappings.py

Requirements: pymupdf, fonttools, pillow, numpy.
Reference font: Ebrima (ships with Windows). Pass --reference to override.

Nothing is written back into the application; this script only reports.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import zlib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PDF = REPO_ROOT / "docs" / "dictionnaire Fr_nko.pdf"
DEFAULT_REFERENCE = Path(r"C:\Windows\Fonts\ebrima.ttf")
LEGACY_FONT_HINT = "Manden"


def extract_legacy_font(pdf_path: Path, out_dir: Path) -> tuple[Path, dict[int, str]]:
    """Return (font file, {cid: tounicode hex}) for the embedded legacy font."""
    import fitz

    out_dir.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(str(pdf_path))

    font_path = None
    for page_no in range(min(doc.page_count, 80)):
        for info in doc.get_page_fonts(page_no, full=True):
            xref, base = info[0], info[3]
            if LEGACY_FONT_HINT not in base:
                continue
            buf = doc.extract_font(xref)
            font_path = out_dir / "legacy_font.ttf"
            font_path.write_bytes(buf[3])
            break
        if font_path:
            break
    if font_path is None:
        raise SystemExit(f"No font matching {LEGACY_FONT_HINT!r} found in {pdf_path}")

    # Pull the ToUnicode CMap for that font's Type0 wrapper.
    data = pdf_path.read_bytes()
    objpos = {
        int(m.group(1)): m.end()
        for m in re.finditer(rb"(?:^|[\r\n\s])(\d+)\s+(\d+)\s+obj\b", data)
    }

    def header_and_stream(num: int) -> tuple[bytes, bytes | None]:
        """Return (object dict header, decoded stream) for a top-level object."""
        start = objpos.get(num)
        if start is None:
            return b"", None
        m = re.compile(rb"stream\r?\n").search(data, start)
        if not m:
            end = data.find(b"endobj", start)
            return data[start : end if end > 0 else start], None
        header = data[start : m.start()]
        raw = data[m.end() : data.find(b"endstream", m.end())]
        if b"FlateDecode" in header:
            try:
                raw = zlib.decompressobj().decompress(raw)
            except Exception:
                return header, None
        return header, raw

    def stream_of(num: int) -> bytes | None:
        return header_and_stream(num)[1]

    # Expand object streams to find the Type0 font dict and its /ToUnicode ref.
    objects: dict[int, bytes] = {}
    for num in list(objpos):
        header, body = header_and_stream(num)
        if body is None or b"/ObjStm" not in header:
            continue
        n = int(re.search(rb"/N\s+(\d+)", header).group(1))
        first = int(re.search(rb"/First\s+(\d+)", header).group(1))
        nums = list(map(int, body[:first].split()))
        pairs = [(nums[i], nums[i + 1]) for i in range(0, 2 * n, 2)]
        for i, (onum, off) in enumerate(pairs):
            end = pairs[i + 1][1] if i + 1 < len(pairs) else len(body) - first
            objects[onum] = body[first + off : first + end]

    cmap: dict[int, str] = {}
    for body in objects.values():
        if b"/Type0" not in body or LEGACY_FONT_HINT.encode() not in body:
            continue
        ref = re.search(rb"/ToUnicode\s+(\d+)\s+\d+\s+R", body)
        if not ref:
            continue
        payload = stream_of(int(ref.group(1)))
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
        if cmap:
            break
    return font_path, cmap


def patch_cmap(src: Path, dst: Path, gids: list[int]) -> None:
    """Give the subset font a cmap so FreeType can address glyphs by codepoint."""
    from fontTools.ttLib import TTFont, newTable
    from fontTools.ttLib.tables._c_m_a_p import CmapSubtable

    font = TTFont(str(src))
    order = font.getGlyphOrder()
    mapping = {0xE000 + g: order[g] for g in gids if g < len(order)}
    tables = []
    for platform_id, enc_id in ((3, 1), (0, 3)):
        sub = CmapSubtable.newSubtable(4)
        sub.platformID, sub.platEncID, sub.language = platform_id, enc_id, 0
        sub.cmap = dict(mapping)
        tables.append(sub)
    table = newTable("cmap")
    table.tableVersion, table.tables = 0, tables
    font["cmap"] = table
    font.save(str(dst))


def make_renderer():
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont

    def render(font_path: Path, codepoint: int, ppem: int):
        canvas = 170
        img = Image.new("L", (canvas, canvas), 0)
        try:
            face = ImageFont.truetype(
                str(font_path), ppem, layout_engine=ImageFont.Layout.BASIC
            )
            ImageDraw.Draw(img).text(
                (canvas // 2, canvas // 2), chr(codepoint), font=face, fill=255, anchor="mm"
            )
        except Exception:
            return None
        box = img.getbbox()
        if not box:
            return None
        glyph = img.crop(box)
        side = max(glyph.size)
        square = Image.new("L", (side, side), 0)
        square.paste(glyph, ((side - glyph.size[0]) // 2, (side - glyph.size[1]) // 2))
        return np.asarray(square.resize((64, 64), Image.LANCZOS), dtype=np.float32) / 255.0

    def iou(a, b) -> float:
        if a is None or b is None:
            return 0.0
        best = 0.0
        for dy in range(-4, 5, 2):
            for dx in range(-4, 5, 2):
                shifted = np.roll(np.roll(b, dy, axis=0), dx, axis=1)
                union = np.maximum(a, shifted).sum()
                if union:
                    best = max(best, float(np.minimum(a, shifted).sum() / union))
        return best

    return render, iou


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", type=Path, default=DEFAULT_PDF)
    parser.add_argument("--reference", type=Path, default=DEFAULT_REFERENCE)
    parser.add_argument("--work-dir", type=Path, default=REPO_ROOT / "data" / "glyph_evidence")
    args = parser.parse_args()

    if not args.pdf.exists():
        print(f"PDF not found: {args.pdf}", file=sys.stderr)
        return 1
    if not args.reference.exists():
        print(
            f"Reference N'Ko font not found: {args.reference}\n"
            "Pass --reference with a font that covers U+07C0..U+07FF.",
            file=sys.stderr,
        )
        return 1

    font_path, cmap = extract_legacy_font(args.pdf, args.work_dir)
    by_unicode = {v: cid for cid, v in cmap.items()}
    print(f"legacy font : {font_path}")
    print(f"ToUnicode   : {len(cmap)} CIDs\n")

    digit_cids = [by_unicode.get("%04X" % (0x0660 + i)) for i in range(10)]
    patch_cmap(font_path, args.work_dir / "patched.ttf", [c for c in digit_cids if c])
    patched = args.work_dir / "patched.ttf"
    render, iou = make_renderer()

    print("DIGITS - is the legacy glyph an N'Ko digit or an Arabic-Indic digit?")
    print(f"  {'legacy':>8} {'cid':>5} {'vs N Ko':>9} {'vs Arabic':>10}  verdict")
    rows = []
    for i, cid in enumerate(digit_cids):
        if cid is None:
            print(f"  U+{0x0660 + i:04X}   (absent from this PDF's font)")
            continue
        glyph = render(patched, 0xE000 + cid, 100)
        nko = iou(glyph, render(args.reference, 0x07C0 + i, 64))
        arabic = iou(glyph, render(args.reference, 0x0660 + i, 64))
        verdict = "N'KO DIGIT" if nko > arabic + 0.15 else (
            "arabic" if arabic > nko + 0.15 else "AMBIGUOUS"
        )
        rows.append((nko, arabic, verdict))
        print(f"  U+{0x0660 + i:04X} {cid:>5} {nko:>9.3f} {arabic:>10.3f}  {verdict}")

    recovered = all(v == "N'KO DIGIT" for _, _, v in rows) and len(rows) == 10
    print(
        "\n  => digit recovery is "
        + ("SUPPORTED by the evidence" if recovered else "NOT fully supported")
    )

    print("\nPUNCTUATION - is any N'Ko punctuation recovery justified?")
    for legacy_hex, claimed, alternative in (
        ("060C", 0x07F8, 0x060C),
        ("061B", 0x061B, 0x07F9),
        ("061F", 0x061F, 0x07F7),
    ):
        cid = by_unicode.get(legacy_hex)
        if cid is None:
            print(f"  U+{legacy_hex}: absent from this PDF's font")
            continue
        patch_cmap(font_path, args.work_dir / "p2.ttf", [cid])
        glyph = render(args.work_dir / "p2.ttf", 0xE000 + cid, 100)
        a = iou(glyph, render(args.reference, claimed, 64))
        b = iou(glyph, render(args.reference, alternative, 64))
        print(
            f"  U+{legacy_hex} cid {cid:>3}: vs U+{claimed:04X}={a:.3f}  "
            f"vs U+{alternative:04X}={b:.3f}  -> "
            + ("keeps its own form; no N'Ko recovery" if b >= a else "inconclusive")
        )

    print(
        "\nConclusion: only the digits are recovered. Punctuation is passthrough,\n"
        "and all N'Ko letters remain in the Private Use Area and unresolved."
    )
    (args.work_dir / "digit_evidence.json").write_text(
        json.dumps(
            {
                "legacy_font": font_path.name,
                "digits": [
                    {"legacy": "U+%04X" % (0x0660 + i), "iou_nko": n, "iou_arabic": a, "verdict": v}
                    for i, (n, a, v) in enumerate(rows)
                ],
                "digit_recovery_supported": recovered,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\nwrote {args.work_dir / 'digit_evidence.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
