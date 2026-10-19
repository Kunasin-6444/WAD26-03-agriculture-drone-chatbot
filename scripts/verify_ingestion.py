"""
Offline ingestion integrity check (no embedding/LLM calls). Exit code 1 on failure.

    python -m scripts.verify_ingestion

Checks, per PDF in data/ (excluded documents must be absent from the KB):
  - every page has at least one chunk
  - numbers printed in the PDF's native text appear in that page's chunks
  - no empty / duplicate chunks, required metadata present
  - document_id is canonical and consistent for each source file
  - every table chunk written by the v2 pipeline starts with its table's header, and all
    chunks of one table agree on that header
  - pages with no chunks are only accepted when the PDF page is truly blank
"""
from __future__ import annotations

import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import chromadb
import pymupdf

from app.ingestion.dedupe import benign_numbers
from app.ingestion.vision_extractor import is_generation_loop
from app.rag.source_policy import canonical_document_id, is_excluded_document

ROOT = Path(__file__).resolve().parents[1]
COLLECTION_NAME = "drone_knowledge"
REQUIRED_META = ("source_file", "page_number", "document_id", "source_type")
NUMBER = re.compile(r"\d+(?:[.,]\d+)?")
MAX_MISSING_NUMBER_RATIO = 0.05


def blank_page(page) -> bool:
    return not page.get_text().strip() and not page.get_images() and not page.get_drawings()


def table_header_problems(data) -> list[str]:
    """v2 table chunks (those with a table_id) must each begin with the table header."""
    problems: list[str] = []
    headers: dict[str, set[str]] = defaultdict(set)
    for chunk_id, meta, text in zip(data["ids"], data["metadatas"], data["documents"]):
        table_id = meta.get("table_id")
        if not table_id or meta.get("has_header") != "true":
            continue
        first = text.strip().splitlines()[0] if text.strip() else ""
        if first.count("|") < 1:
            problems.append(f"{chunk_id}: table chunk does not start with a header row")
        headers[f"{meta.get('source_file')}::{table_id}"].add(first)
    problems += [f"{key}: chunks disagree on the table header ({len(found)} variants)"
                 for key, found in headers.items() if len(found) > 1]
    return problems


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    path = os.getenv("CHROMA_PATH", str(ROOT / "chroma_db"))
    collection = chromadb.PersistentClient(path=path).get_collection(COLLECTION_NAME)
    data = collection.get(include=["metadatas", "documents"])
    problems: list[str] = []

    chunks_by_page: dict[tuple[str, int], list[str]] = defaultdict(list)
    doc_ids: dict[str, set[str]] = defaultdict(set)
    seen: Counter = Counter()
    loops: Counter = Counter()
    for chunk_id, meta, text in zip(data["ids"], data["metadatas"], data["documents"]):
        missing = [k for k in REQUIRED_META if not meta.get(k)]
        if missing:
            problems.append(f"{chunk_id}: missing metadata {missing}")
            continue
        if not text.strip():
            problems.append(f"{chunk_id}: empty chunk")
        key = (meta["source_file"], int(meta["page_number"]))
        seen[(key, text.strip())] += 1
        if is_generation_loop(text):
            loops[key] += 1
        # a table row whose text ran onto following pages (or whose header sits on an earlier page)
        # covers those pages too
        first = int(meta.get("page_from") or key[1])
        last = int(meta.get("page_end") or key[1])
        for covered in range(min(first, key[1]), max(last, key[1]) + 1):
            chunks_by_page[(key[0], covered)].append(text)
        doc_ids[meta["source_file"]].add(meta["document_id"])
    problems += [f"duplicate chunk on {k[0][0]} p{k[0][1]} x{n}" for k, n in seen.items() if n > 1]
    problems += [f"{f} p{p}: {n} chunk(s) of generation-loop text (model output, not the PDF)"
                 for (f, p), n in sorted(loops.items())]

    problems += table_header_problems(data)

    kb_files = {f for f, _ in chunks_by_page}
    for name in sorted(kb_files):
        if is_excluded_document(name):
            problems.append(f"excluded document present in KB: {name}")
        if doc_ids[name] != {canonical_document_id(name)}:
            problems.append(f"{name}: document_id {sorted(doc_ids[name])} != {canonical_document_id(name)}")

    print(f"chroma path: {path}   chunks: {len(data['ids'])}")
    for pdf_path in sorted((ROOT / "data").glob("*.pdf")):
        if is_excluded_document(pdf_path.name):
            continue
        if pdf_path.name not in kb_files:
            problems.append(f"{pdf_path.name}: not ingested")
            continue
        with pymupdf.open(pdf_path) as pdf:
            pages = len(pdf)
            numbers = missing_numbers = 0
            no_chunk = []
            for number, page in enumerate(pdf, 1):
                chunks = chunks_by_page.get((pdf_path.name, number))
                if not chunks:
                    if not blank_page(page):
                        no_chunk.append(number)
                    continue
                text = page.get_text()
                # Slide/page numbers printed on the page are not knowledge content.
                native = set(NUMBER.findall(text)) - benign_numbers(text, number)
                numbers += len(native)
                missing_numbers += len(native - set(NUMBER.findall("\n".join(chunks))))
        ratio = missing_numbers / numbers if numbers else 0.0
        print(f"  {pdf_path.name[:40]:40} pages={pages:3} no_chunk={len(no_chunk)} "
              f"numbers_missing={missing_numbers}/{numbers} ({ratio:.1%})")
        if no_chunk:
            problems.append(f"{pdf_path.name}: pages without chunks {no_chunk}")
        if ratio > MAX_MISSING_NUMBER_RATIO:
            problems.append(f"{pdf_path.name}: {ratio:.1%} of native numbers missing from chunks")

    if problems:
        print(f"\nFAILED ({len(problems)} problems)")
        for problem in problems:
            print(" -", problem)
        return 1
    print("\nOK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
