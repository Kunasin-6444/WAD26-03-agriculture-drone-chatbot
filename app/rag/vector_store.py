from __future__ import annotations

from pathlib import Path
import os

import chromadb

from app.rag.chunking import Chunk
from app.rag.embedding import embed_text
from app.rag.source_policy import is_excluded_document


# --------------------------------------------------
# Chroma configuration
# --------------------------------------------------

CHROMA_PATH = Path(os.getenv("CHROMA_PATH", str(Path(__file__).resolve().parents[2] / "chroma_db")))
COLLECTION_NAME = "drone_knowledge"


# --------------------------------------------------
# Chroma client
# --------------------------------------------------

client = chromadb.PersistentClient(
    path=str(CHROMA_PATH)
)


collection = client.get_or_create_collection(
    name=COLLECTION_NAME
)


# --------------------------------------------------
# Add chunks
# --------------------------------------------------

def add_chunks(
    chunks: list[Chunk],
    replace_source_file: str | None = None,
    replace_pages: range | None = None,
) -> None:
    """
    Add text chunks and their embeddings to Chroma.
    """

    if not chunks:
        return

    if any(is_excluded_document(chunk.source_file) for chunk in chunks):
        raise ValueError("UAV01/UA03 must use CAAT rather than PDF ingestion")

    ids: list[str] = []
    documents: list[str] = []
    embeddings: list[list[float]] = []
    metadatas: list[dict[str, str]] = []
    seen_ids: set[str] = set()

    for idx, chunk in enumerate(chunks, start=1):

        if idx % 10 == 0 or idx == len(chunks):
            print(f"    Embedding progress: {idx}/{len(chunks)} chunks...", flush=True)

        chunk_id = chunk.id
        if chunk_id in seen_ids:
            counter = 1
            while f"{chunk_id}_{counter}" in seen_ids:
                counter += 1
            chunk_id = f"{chunk_id}_{counter}"
        seen_ids.add(chunk_id)

        ids.append(chunk_id)

        documents.append(
            chunk.content
        )

        embeddings.append(
            embed_text(chunk.content)
        )

        metadatas.append(
            chunk.metadata
        )

    if replace_source_file:
        removed = delete_document_pages(replace_source_file, replace_pages)
        if removed:
            print(f"    Replaced {removed} existing chunks for {replace_source_file}", flush=True)

    collection.upsert(
        ids=ids,
        documents=documents,
        embeddings=embeddings,
        metadatas=metadatas,
    )


def delete_document_pages(source_file: str, pages: range | None = None) -> int:
    """
    Remove existing chunks for a source file (optionally only some pages) so a
    re-ingest replaces them instead of leaving stale/duplicate chunks behind.
    """

    found = collection.get(where={"source_file": source_file}, include=["metadatas"])
    ids = [
        chunk_id
        for chunk_id, meta in zip(found["ids"], found["metadatas"])
        if pages is None or int(meta.get("page_number", 0)) in pages
    ]
    if ids:
        collection.delete(ids=ids)
    return len(ids)


# --------------------------------------------------
# Query
# --------------------------------------------------

def search(
    query: str,
    n_results: int = 5,
):
    """
    Search the knowledge base using semantic similarity.
    """

    if not query.strip():
        raise ValueError(
            "Query cannot be empty"
        )

    query_embedding = embed_text(
        query, max_retries=1, timeout_seconds=3.0,
    )

    return collection.query(
        query_embeddings=[
            query_embedding
        ],
        n_results=n_results,
    )
