from __future__ import annotations

from dataclasses import dataclass

from app.ingestion.models import KnowledgeUnit


# --------------------------------------------------
# Chunk model
# --------------------------------------------------

@dataclass
class Chunk:
    """
    A text chunk used for embedding and retrieval.
    """

    id: str
    content: str

    document_id: str
    source_file: str
    page_number: int
    source_type: str

    metadata: dict[str, str]


# --------------------------------------------------
# Text chunking
# --------------------------------------------------

def split_text(
    text: str,
    chunk_size: int = 800,
    chunk_overlap: int = 120,
) -> list[str]:
    """
    Split text into overlapping character-based chunks.

    MVP baseline:
        chunk_size    = 800 characters
        chunk_overlap = 120 characters
    """

    if not text.strip():
        return []

    if chunk_size < 1 or chunk_overlap < 0 or chunk_overlap >= chunk_size:
        raise ValueError(
            "chunk_overlap must be smaller than chunk_size"
        )

    text = text.strip()

    chunks: list[str] = []

    start = 0
    text_length = len(text)

    while start < text_length:

        end = min(
            start + chunk_size,
            text_length,
        )

        chunk = text[start:end].strip()

        if chunk:
            chunks.append(chunk)

        if end >= text_length:
            break

        start = end - chunk_overlap

    return chunks


# --------------------------------------------------
# KnowledgeUnit -> Chunks
# --------------------------------------------------

def chunk_knowledge_unit(
    unit: KnowledgeUnit,
    chunk_size: int = 800,
    chunk_overlap: int = 120,
) -> list[Chunk]:
    """
    Convert one KnowledgeUnit into retrieval chunks.
    Structured units (tables, diagrams, charts) up to 1200 characters
    are kept intact to avoid separating rows and headers.
    """

    if unit.source_type in {"table", "diagram", "chart"} and len(unit.content) <= 1200:
        text_chunks = [unit.content.strip()] if unit.content.strip() else []
    else:
        text_chunks = split_text(
            text=unit.content,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )

    chunks: list[Chunk] = []

    for index, content in enumerate(
        text_chunks,
        start=1,
    ):

        chunk_id = (
            f"{unit.id}-chunk-{index}"
        )

        chunks.append(
            Chunk(
                id=chunk_id,
                content=content,
                document_id=unit.document_id,
                source_file=unit.source_file,
                page_number=unit.page_number,
                source_type=unit.source_type,
                metadata={
                    "document_id": unit.document_id,
                    "source_file": unit.source_file,
                    "page_number": str(unit.page_number),
                    "source_type": unit.source_type,
                },
            )
        )

    return chunks


def chunk_knowledge_units(
    units: list[KnowledgeUnit],
    chunk_size: int = 800,
    chunk_overlap: int = 120,
) -> list[Chunk]:
    """
    Convert multiple KnowledgeUnits into chunks.
    """

    all_chunks: list[Chunk] = []

    for unit in units:

        chunks = chunk_knowledge_unit(
            unit=unit,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )

        all_chunks.extend(chunks)

    return all_chunks
