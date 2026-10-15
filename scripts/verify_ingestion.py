"""
Offline ingestion integrity check (no embedding/LLM calls). Exit code 1 on failure.

    python -m scripts.verify_ingestion

Checks, per PDF in data/ (excluded documents must be absent from the KB):
  - every page has at least one chunk
  - numbers printed in the PDF's native text appear in that page's chunks
  - no empty / duplicate chunks, required metadata present
  - document_id is canonical and consistent for each source file
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
from app.rag.source_policy import canonical_document_id, is_excluded_document

ROOT = Path(__file__).resolve().parents[1]
COLLECTION_NAME = "drone_knowledge"
REQUIRED_META = ("source_file", "page_number", "document_id", "source_type")
NUMBER = re.compile(r"\d+(?:[.,]\d+)?")
MAX_MISSING_NUMBER_RATIO = 0.05


def main() -> int:
    path = os.getenv("CHROMA_PATH", str(ROOT / "chroma_db"))
    collection = chromadb.PersistentClient(path=path).get_collection(COLLECTION_NAME)
    data = collection.get(include=["metadatas", "documents"])
    problems: list[str] = []

    chunks_by_page: dict[tuple[str, int], list[str]] = defaultdict(list)
    doc_ids: dict[str, set[str]] = defaultdict(set)
    seen: Counter = Counter()
    for chunk_id, meta, text in zip(data["ids"], data["metadatas"], data["documents"]):
        missing = [k for k in REQUIRED_META if not meta.get(k)]
        if missing:
            problems.append(f"{chunk_id}: missing metadata {missing}")
            continue
        if not text.strip():
            problems.append(f"{chunk_id}: empty chunk")
        key = (meta["source_file"], int(meta["page_number"]))
        seen[(key, text.strip())] += 1
        chunks_by_page[key].append(text)
        doc_ids[meta["source_file"]].add(meta["document_id"])
    problems += [f"duplicate chunk on {k[0][0]} p{k[0][1]} x{n}" for k, n in seen.items() if n > 1]

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
