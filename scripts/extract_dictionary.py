"""Reproducible extraction pipeline for French-N'Ko Dictionary PDF.

Preserves the source PDF untouched, parses French headwords and grammatical
labels across pages 22-498, evaluates target character verification via
nko_mapping, indexes entries into SQLite, and generates an audit report.
"""

import argparse
import json
import logging
import os
import re
import sqlite3
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

# Ensure backend modules can be imported
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.services.nko_mapping import (  # noqa: E402
    ConversionResult,
    MappingStatus,
    convert_nko_token,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("dictionary_extractor")

# Common French dictionary POS / grammatical labels
POS_PATTERNS = [
    r"adj\.\s+et\s+n\.",
    r"adj\.\s+n\.m\.\s+pl\.",
    r"adj\.\s+n\.f\.\s+pl\.",
    r"n\.m\.\s+pl\.",
    r"n\.f\.\s+pl\.",
    r"n\.m\.",
    r"n\.f\.",
    r"adj\.",
    r"v\.t\.",
    r"v\.i\.",
    r"adv\.",
    r"prép\.",
    r"locut\.",
    r"loc\.",
    r"conj\.",
    r"interj\.",
    r"pron\.",
    r"prono\.",
    r"propr\.",
    r"inv\.",
    r"part\.",
    r"pass\.",
    r"pêch\.",
    r"phys\.",
    r"méd\.",
    r"bot\.",
    r"zool\.",
    r"milit\.",
    r"math\.",
    r"comm\.",
    r"fam\.",
    r"fig\.",
    r"n\.",
    r"v\.",
]

POS_REGEX = re.compile(
    r"\b(" + "|".join(POS_PATTERNS) + r")\b",
    re.IGNORECASE,
)

# Pattern matching a dictionary entry line:
# [French headword] [POS] [Target / rest of line]
ENTRY_LINE_REGEX = re.compile(
    r"^([a-zA-ZÀ-ÿœŒæÆ'’\-\s,]+?)\s+(" + "|".join(POS_PATTERNS) + r")\s*(.*)$",
    re.IGNORECASE,
)


@dataclass
class ExtractedEntry:
    headword: str
    headword_normalized: str
    pos: str
    sense_number: int
    raw_target: str
    verified_nko: str
    is_verified: bool
    status: str
    page_number: int
    unresolved_chars: list[str]


def normalize_headword(text: str) -> str:
    """Normalize headword for searching: lowercase, stripped, simplified."""
    text = text.lower().strip()
    # Remove variant markers like ',e' or ',aux' or ',trice'
    text = re.sub(r",\s*(e|aux|trice|elle|ve)\b", "", text)
    # Remove extra spaces
    text = " ".join(text.split())
    return text


def parse_page_entries(page_text: str, page_num: int) -> list[ExtractedEntry]:
    """Parse text from a single page into structured dictionary entries."""
    lines = [line.strip() for line in page_text.split("\n")]
    entries: list[ExtractedEntry] = []
    current_entry: Optional[ExtractedEntry] = None

    for line in lines:
        if not line:
            continue

        # Skip running page headers / decorative lines
        if any(hdr in line for hdr in ["J•◊BoB", "…∆¨™Æ", "DICTIONNAIRE", "KANJAMADI"]):
            continue

        # Skip isolated section letters (like single 'A', 'B', 'VI', etc.)
        if re.match(r"^[A-Z0-9IVXLCDM]{1,4}$", line):
            continue

        match = ENTRY_LINE_REGEX.match(line)
        if match:
            raw_hw, pos, target_rest = match.groups()
            headword = raw_hw.strip()

            # Ignore lines that are too long or clearly prose
            if len(headword) > 60:
                continue

            normalized = normalize_headword(headword)
            conversion = convert_nko_token(target_rest.strip())

            # Split senses if multiple are present with '/' or numbered markers
            raw_senses = [s.strip() for s in target_rest.split("/") if s.strip()]
            if not raw_senses:
                raw_senses = [target_rest.strip()]

            for sense_idx, sense_text in enumerate(raw_senses, 1):
                sense_conv = convert_nko_token(sense_text)
                entry = ExtractedEntry(
                    headword=headword,
                    headword_normalized=normalized,
                    pos=pos.strip(),
                    sense_number=sense_idx,
                    raw_target=sense_text,
                    verified_nko=sense_conv.converted_text,
                    is_verified=sense_conv.is_verified,
                    status=sense_conv.status.value,
                    page_number=page_num,
                    unresolved_chars=sense_conv.unresolved_chars,
                )
                entries.append(entry)
                current_entry = entry
        elif current_entry and line:
            # Multi-line continuation: append to raw_target of previous entry
            # if line does not start a new entry and is largely non-Latin
            if not re.match(r"^[a-zA-ZÀ-ÿ]{2,}", line):
                current_entry.raw_target += " " + line
                # Re-evaluate conversion
                reconv = convert_nko_token(current_entry.raw_target)
                current_entry.verified_nko = reconv.converted_text
                current_entry.is_verified = reconv.is_verified
                current_entry.status = reconv.status.value
                current_entry.unresolved_chars = reconv.unresolved_chars

    return entries


def init_database(db_path: Path):
    """Initialize SQLite database schema."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE dictionary_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            headword TEXT NOT NULL,
            headword_normalized TEXT NOT NULL,
            pos TEXT,
            sense_number INTEGER DEFAULT 1,
            raw_target TEXT,
            verified_nko TEXT,
            is_verified INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL,
            page_number INTEGER NOT NULL
        )
    """)
    cur.execute("CREATE INDEX idx_headword ON dictionary_entries(headword_normalized)")
    cur.execute("CREATE INDEX idx_is_verified ON dictionary_entries(is_verified)")
    cur.execute("CREATE INDEX idx_page ON dictionary_entries(page_number)")
    conn.commit()
    conn.close()


def store_entries_in_db(db_path: Path, entries: list[ExtractedEntry]):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.executemany(
        """
        INSERT INTO dictionary_entries (
            headword, headword_normalized, pos, sense_number,
            raw_target, verified_nko, is_verified, status, page_number
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                e.headword,
                e.headword_normalized,
                e.pos,
                e.sense_number,
                e.raw_target,
                e.verified_nko,
                1 if e.is_verified else 0,
                e.status,
                e.page_number,
            )
            for e in entries
        ],
    )
    conn.commit()
    conn.close()


def run_pipeline(
    pdf_path: Path,
    start_page: int,
    end_page: int,
    max_pages: Optional[int],
    output_dir: Path,
    db_path: Path,
    report_path: Path,
) -> dict:
    import pypdf

    logger.info("Opening PDF: %s", pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF file not found at {pdf_path}")

    reader = pypdf.PdfReader(str(pdf_path))
    total_pdf_pages = len(reader.pages)
    logger.info("Total pages in PDF: %d", total_pdf_pages)

    actual_end_page = min(end_page, total_pdf_pages)
    if max_pages:
        actual_end_page = min(start_page + max_pages - 1, actual_end_page)

    output_dir.mkdir(parents=True, exist_ok=True)
    raw_jsonl_path = output_dir / "raw_extraction.jsonl"
    verified_json_path = output_dir / "dictionary_verified.json"

    init_database(db_path)

    all_entries: list[ExtractedEntry] = []
    pages_processed = 0
    duplicate_count = 0
    seen_keys: set[tuple[str, str, int]] = set()

    with open(raw_jsonl_path, "w", encoding="utf-8") as raw_f:
        for p in range(start_page, actual_end_page + 1):
            pages_processed += 1
            page_text = reader.pages[p - 1].extract_text()
            page_entries = parse_page_entries(page_text, p)

            for entry in page_entries:
                key = (entry.headword_normalized, entry.pos, entry.sense_number)
                if key in seen_keys:
                    duplicate_count += 1
                else:
                    seen_keys.add(key)

                all_entries.append(entry)
                raw_f.write(json.dumps(asdict(entry), ensure_ascii=False) + "\n")

            if pages_processed % 50 == 0 or p == actual_end_page:
                logger.info(
                    "Processed %d pages (%d entries extracted so far)",
                    pages_processed,
                    len(all_entries),
                )

    # Insert into SQLite
    store_entries_in_db(db_path, all_entries)

    # Filter verified entries
    verified_entries = [e for e in all_entries if e.is_verified]
    with open(verified_json_path, "w", encoding="utf-8") as vf:
        json.dump(
            [asdict(e) for e in verified_entries],
            vf,
            ensure_ascii=False,
            indent=2,
        )

    # Compute statistics
    incomplete_count = sum(1 for e in all_entries if not e.is_verified)
    distinct_headwords = len({e.headword_normalized for e in all_entries})

    stats = {
        "pdf_source": str(pdf_path),
        "total_pdf_pages": total_pdf_pages,
        "start_page": start_page,
        "end_page": actual_end_page,
        "pages_processed": pages_processed,
        "total_entries_extracted": len(all_entries),
        "distinct_headwords": distinct_headwords,
        "verified_nko_entries": len(verified_entries),
        "incomplete_or_pua_entries": incomplete_count,
        "duplicate_entries_detected": duplicate_count,
        "mapping_status_breakdown": {
            MappingStatus.VERIFIED.value: len(verified_entries),
            MappingStatus.UNVERIFIED_PUA.value: incomplete_count,
        },
        "database_file": str(db_path),
        "raw_jsonl_file": str(raw_jsonl_path),
        "verified_json_file": str(verified_json_path),
    }

    with open(report_path, "w", encoding="utf-8") as rf:
        json.dump(stats, rf, indent=2)

    logger.info(
        "Extraction finished. Extracted %d entries across %d pages. Verified N'Ko: %d, Incomplete: %d.",
        len(all_entries),
        pages_processed,
        len(verified_entries),
        incomplete_count,
    )
    return stats


def main():
    parser = argparse.ArgumentParser(description="Extract French-N'Ko dictionary from PDF")
    parser.add_argument(
        "--pdf",
        type=Path,
        default=Path("docs/dictionnaire Fr_nko.pdf"),
        help="Path to source PDF",
    )
    parser.add_argument(
        "--start-page",
        type=int,
        default=22,
        help="Start page for dictionary entries (default: 22)",
    )
    parser.add_argument(
        "--end-page",
        type=int,
        default=498,
        help="End page for dictionary entries (default: 498)",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=None,
        help="Maximum pages to process (for quick testing)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data"),
        help="Output directory for data files",
    )
    parser.add_argument(
        "--db-path",
        type=Path,
        default=Path("data/dictionary.sqlite"),
        help="Path to output SQLite database",
    )
    parser.add_argument(
        "--report-path",
        type=Path,
        default=Path("data/extraction_report.json"),
        help="Path to output extraction report",
    )

    args = parser.parse_args()
    run_pipeline(
        pdf_path=args.pdf,
        start_page=args.start_page,
        end_page=args.end_page,
        max_pages=args.max_pages,
        output_dir=args.output_dir,
        db_path=args.db_path,
        report_path=args.report_path,
    )


if __name__ == "__main__":
    main()
