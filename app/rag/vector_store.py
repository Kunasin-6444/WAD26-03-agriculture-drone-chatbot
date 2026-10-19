from __future__ import annotations

from pathlib import Path
import os

import chromadb

from app.rag.chunking import Chunk
from app.rag.embedding import EMBEDDING_MODEL, embed_text
from app.rag.embedding_cache import cached_document_embedding
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
    if replace_source_file and any(chunk.source_file != replace_source_file for chunk in chunks):
        raise ValueError("Replacement chunks must belong to the requested source file")

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
            cached_document_embedding(chunk.content, EMBEDDING_MODEL, CHROMA_PATH / "embedding_cache", embed_text)
        )

        metadatas.append(
            {**chunk.metadata, "embedding_model": EMBEDDING_MODEL, "embedding_dimensions": "3072"}
        )

    old_ids = _document_page_ids(replace_source_file, replace_pages) if replace_source_file else []

    collection.upsert(
        ids=ids,
        documents=documents,
        embeddings=embeddings,
        metadatas=metadatas,
    )
    # Publish first. A rejected upsert must not remove the last usable document.
    stale_ids = sorted(set(old_ids) - set(ids))
    if stale_ids:
        collection.delete(ids=stale_ids)


def delete_document_pages(source_file: str, pages: range | None = None) -> int:
    """
    Remove existing chunks for a source file (optionally only some pages) so a
    re-ingest replaces them instead of leaving stale/duplicate chunks behind.
    """

    ids = _document_page_ids(source_file, pages)
    if ids:
        collection.delete(ids=ids)
    return len(ids)


def _document_page_ids(source_file: str, pages=None) -> list[str]:
    found = collection.get(where={"source_file": source_file}, include=["metadatas"])
    return [
        chunk_id
        for chunk_id, meta in zip(found["ids"], found["metadatas"])
        if pages is None or int(meta.get("page_number", 0)) in pages
    ]


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
