"""Publish embedded chunks to Chroma without ever leaving the index worse than it was.

Same guarantees as ``vector_store.add_chunks``, but vectors are computed beforehand (in
batches) so a quota or network failure while embedding cannot touch the index at all:
new chunks are upserted first, and the document's stale chunks are deleted only after
that succeeded.
"""
from __future__ import annotations

from app.rag.chunking import Chunk
from app.rag.source_policy import is_excluded_document

MAX_UPSERT = 4000
# Chroma's upsert MERGES metadata into an existing id, so a key written by an earlier run would
# survive a re-ingest. Every optional key is therefore always written ("" when unused).
OPTIONAL_KEYS = ("section", "table_id", "table_note", "row_start", "row_end", "header_inherited", "has_header",
                 "group_column", "page_from", "page_end", "partial_range", "vision_status")


def document_ids(collection, source_file: str, pages=None) -> list[str]:
    found = collection.get(where={"source_file": source_file}, include=["metadatas"])
    return [chunk_id for chunk_id, meta in zip(found["ids"], found["metadatas"])
            if pages is None or int((meta or {}).get("page_number", 0)) in pages]


def publish(collection, chunks: list[Chunk], vectors: list[list[float]], source_file: str,
            replace_pages=None, embedding_model: str = "") -> dict:
    """Replace the document's chunks (all, or only ``replace_pages``) with ``chunks``."""
    if len(chunks) != len(vectors):
        raise ValueError("One vector is required per chunk")
    if is_excluded_document(source_file) or any(is_excluded_document(c.source_file) for c in chunks):
        raise ValueError("UAV01/UA03 must use CAAT rather than PDF ingestion")
    if any(chunk.source_file != source_file for chunk in chunks):
        raise ValueError("Replacement chunks must belong to the requested source file")
    ids: list[str] = []
    seen: set[str] = set()
    for chunk in chunks:
        chunk_id, counter = chunk.id, 0
        while chunk_id in seen:
            counter += 1
            chunk_id = f"{chunk.id}_{counter}"
        seen.add(chunk_id)
        ids.append(chunk_id)
    metadatas = [{**dict.fromkeys(OPTIONAL_KEYS, ""), **chunk.metadata, "embedding_model": embedding_model,
                  "embedding_dimensions": str(len(vector))} for chunk, vector in zip(chunks, vectors)]
    old_ids = document_ids(collection, source_file, replace_pages)
    for start in range(0, len(ids), MAX_UPSERT):
        window = slice(start, start + MAX_UPSERT)
        collection.upsert(ids=ids[window], documents=[c.content for c in chunks[window]],
                          embeddings=vectors[window], metadatas=metadatas[window])
    stale = sorted(set(old_ids) - set(ids))
    if stale:
        collection.delete(ids=stale)
    return {"upserted": len(ids), "deleted": len(stale)}
