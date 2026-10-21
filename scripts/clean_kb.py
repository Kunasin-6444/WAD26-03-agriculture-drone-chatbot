"""
Offline KB cleanup (no embedding/LLM calls).

    python -m scripts.clean_kb            # dry run: report only
    python -m scripts.clean_kb --apply    # write changes

Actions:
  1. Drop exact-duplicate chunks (same source file + page + content).
  2. Drop very short chunks (< MIN_CHARS) whose text is already contained in
     another chunk of the same page; short chunks carrying unique text are kept.
  3. Normalise metadata.document_id to the canonical id (UAV06 ... UAV12).
"""
from __future__ import annotations

import os
import sys
from collections import defaultdict
from pathlib import Path

import chromadb

from app.rag.source_policy import canonical_document_id, is_excluded_document

MIN_CHARS = 40
COLLECTION_NAME = "drone_knowledge"
DEFAULT_PATH = Path(__file__).resolve().parents[1] / "chroma_db"


def plan(ids, metadatas, documents):
    by_page: dict[tuple, list[int]] = defaultdict(list)
    for i, meta in enumerate(metadatas):
        by_page[(meta["source_file"], meta["page_number"])].append(i)

    drop: dict[str, str] = {}
    for indexes in by_page.values():
        seen: dict[str, int] = {}
        for i in indexes:
            key = documents[i].strip()
            if key in seen:
                drop[ids[i]] = "duplicate"
            else:
                seen[key] = i
        for i in indexes:
            text = documents[i].strip()
            if ids[i] in drop or len(text) >= MIN_CHARS:
                continue
            if any(j != i and ids[j] not in drop and text in documents[j] for j in indexes):
                drop[ids[i]] = "short-contained"

    id_fix = {
        ids[i]: canonical_document_id(meta["source_file"])
        for i, meta in enumerate(metadatas)
        if ids[i] not in drop and meta.get("document_id") != canonical_document_id(meta["source_file"])
    }
    excluded = [ids[i] for i, m in enumerate(metadatas) if is_excluded_document(m["source_file"])]
    return drop, id_fix, excluded


def main() -> None:
    apply = "--apply" in sys.argv
    path = os.getenv("CHROMA_PATH", str(DEFAULT_PATH))
    collection = chromadb.PersistentClient(path=path).get_collection(COLLECTION_NAME)
    data = collection.get(include=["metadatas", "documents"])
    ids, metadatas, documents = data["ids"], data["metadatas"], data["documents"]
    drop, id_fix, excluded = plan(ids, metadatas, documents)
    for id_ in excluded:
        drop.setdefault(id_, "excluded-document")

    reasons: dict[str, int] = defaultdict(int)
    for reason in drop.values():
        reasons[reason] += 1
    print(f"chroma path : {path}")
    print(f"chunks      : {len(ids)}")
    print(f"to delete   : {len(drop)} {dict(reasons)}")
    print(f"metadata fix: {len(id_fix)} document_id values")
    if not apply:
        print("dry run - pass --apply to write")
        return

    if drop:
        collection.delete(ids=list(drop))
    by_value: dict[str, list[str]] = defaultdict(list)
    for chunk_id, doc_id in id_fix.items():
        by_value[doc_id].append(chunk_id)
    for doc_id, chunk_ids in by_value.items():
        current = collection.get(ids=chunk_ids, include=["metadatas"])
        collection.update(ids=chunk_ids, metadatas=[{**m, "document_id": doc_id} for m in current["metadatas"]])
    print(f"applied. chunks now: {collection.count()}")


if __name__ == "__main__":
    main()
