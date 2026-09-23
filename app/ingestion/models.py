from typing import Literal

from pydantic import BaseModel, Field


class KnowledgeUnit(BaseModel):
    """
    Normalized knowledge unit produced from PDF content.

    A knowledge unit is an intermediate representation
    between document extraction and chunking.
    """

    id: str

    # --------------------------------------------------
    # Source information
    # --------------------------------------------------

    document_id: str
    source_file: str
    page_number: int

    # --------------------------------------------------
    # Type of source content
    # --------------------------------------------------

    source_type: Literal[
        "text",
        "table",
        "image",
        "diagram",
        "chart",
        "mixed",
    ]

    # --------------------------------------------------
    # Main content used for RAG
    # --------------------------------------------------

    content: str

    # --------------------------------------------------
    # Optional raw evidence
    # --------------------------------------------------

    extracted_text: str | None = None

    visual_description: str | None = None

    # --------------------------------------------------
    # Additional metadata
    # --------------------------------------------------

    title: str | None = None

    metadata: dict[str, str] = Field(
        default_factory=dict
    )