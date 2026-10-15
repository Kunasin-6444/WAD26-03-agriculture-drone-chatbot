from __future__ import annotations

from pathlib import Path
from typing import Any
import hashlib

import pymupdf

from app.ingestion.models import KnowledgeUnit
from app.ingestion.thai_text import repair_sara_am
from app.ingestion.vision_extractor import VisionPageResult


# --------------------------------------------------
# Helpers
# --------------------------------------------------

def make_unit_id(
    document_id: str,
    page_number: int,
    source_type: str,
    index: int,
    source_origin: str = "native",
) -> str:
    """
    Create a deterministic ID for a KnowledgeUnit.

    Example:
        uav07-p12-table-native_table-1-a83f91
    """

    raw = (
        f"{document_id}:"
        f"{page_number}:"
        f"{source_type}:"
        f"{source_origin}:"
        f"{index}"
    )

    short_hash = hashlib.sha1(
        raw.encode("utf-8")
    ).hexdigest()[:6]

    return (
        f"{document_id}-"
        f"p{page_number}-"
        f"{source_type}-"
        f"{source_origin}-"
        f"{index}-"
        f"{short_hash}"
    )


def rows_to_text(
    rows: list[list[Any]],
) -> str:
    """
    Convert table rows into readable text.

    Example:

        Header A | Header B
        value 1  | value 2
    """

    lines: list[str] = []

    for row in rows:

        values = []

        for cell in row:

            if cell is None:
                values.append("")
            else:
                values.append(str(cell).strip())

        lines.append(" | ".join(values))

    return "\n".join(lines)


def clean_text(
    text: str | None,
) -> str:
    """
    Normalize whitespace while preserving Thai text.
    """

    if not text:
        return ""

    lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip()
    ]

    return "\n".join(lines)


# --------------------------------------------------
# Native PDF tables
# --------------------------------------------------

def extract_native_tables(
    page,
    table_result=None,
) -> list[str]:
    """
    Extract tables that PyMuPDF can detect natively.

    This does NOT handle image-only tables.
    Image-only tables are handled by Vision.
    """

    results: list[str] = []

    try:
        if table_result is None:
            table_result = page.find_tables()

    except Exception as exc:

        print(
            f"[extract_native_tables] "
            f"failed: {exc!r}"
        )

        return results

    tables = getattr(
        table_result,
        "tables",
        [],
    )

    for table in tables:

        try:

            rows = table.extract()

            if not rows:
                continue

            text = rows_to_text(
                rows
            )

            text = repair_sara_am(clean_text(
                text
            ))

            if text:
                results.append(text)

        except Exception as exc:

            print(
                "[extract_native_tables] "
                f"table failed: {exc!r}"
            )

    return results


# --------------------------------------------------
# Build Knowledge Units from one PDF page
# --------------------------------------------------

def build_page_knowledge_units(
    pdf_path: str,
    document_id: str,
    page_number: int,
    vision_result: VisionPageResult | None = None,
) -> list[KnowledgeUnit]:
    """
    Build KnowledgeUnits for one PDF page.

    Sources:

        1. Native PDF text (excluding native table areas to avoid duplication)
        2. Native PDF tables
        3. Vision-extracted visual information

    Each meaningful content block becomes its own
    KnowledgeUnit.
    """

    pdf = Path(pdf_path)

    if not pdf.exists():
        raise FileNotFoundError(pdf)

    doc = pymupdf.open(pdf)

    units: list[KnowledgeUnit] = []

    try:

        if (
            page_number < 1
            or page_number > len(doc)
        ):
            raise ValueError(
                f"Page must be between 1 and {len(doc)}"
            )

        page = doc[
            page_number - 1
        ]

        # --------------------------------------------------
        # 1. Native PDF tables detection
        # --------------------------------------------------

        table_result = None
        tab_rects: list[pymupdf.Rect] = []

        try:
            table_result = page.find_tables()
            tab_rects = [
                pymupdf.Rect(t.bbox)
                for t in getattr(table_result, "tables", [])
            ]
        except Exception as exc:
            print(
                f"[build_page_knowledge_units] "
                f"find_tables failed: {exc!r}"
            )

        # --------------------------------------------------
        # 2. Normal PDF text (excluding native table bboxes)
        # --------------------------------------------------

        if tab_rects:
            blocks = page.get_text("blocks")
            non_table_blocks = []
            for b in blocks:
                r = pymupdf.Rect(b[:4])
                if not any(r.intersects(tr) for tr in tab_rects):
                    non_table_blocks.append(b[4].strip())
            page_text = clean_text("\n".join(b for b in non_table_blocks if b))
        else:
            page_text = clean_text(
                page.get_text()
            )
        # The PDFs' own text layer has broken SARA AM; repair it before chunking/embedding.
        page_text = repair_sara_am(page_text)

        if page_text:

            unit_id = make_unit_id(
                document_id=document_id,
                page_number=page_number,
                source_type="text",
                index=1,
            )

            units.append(
                KnowledgeUnit(
                    id=unit_id,
                    document_id=document_id,
                    source_file=pdf.name,
                    page_number=page_number,
                    source_type="text",
                    content=page_text,
                    extracted_text=page_text,
                    title=None,
                    metadata={
                        "source": "pdf_text",
                    },
                )
            )

        # --------------------------------------------------
        # 3. Native PDF tables
        # --------------------------------------------------

        native_tables = extract_native_tables(
            page,
            table_result=table_result,
        )

        for index, table_text in enumerate(
            native_tables,
            start=1,
        ):

            unit_id = make_unit_id(
                document_id=document_id,
                page_number=page_number,
                source_type="table",
                index=index,
                source_origin="native_table",
            )

            units.append(
                KnowledgeUnit(
                    id=unit_id,
                    document_id=document_id,
                    source_file=pdf.name,
                    page_number=page_number,
                    source_type="table",
                    content=table_text,
                    extracted_text=table_text,
                    title=None,
                    metadata={
                        "source": "pdf_native_table",
                    },
                )
            )

    finally:
        doc.close()

    # --------------------------------------------------
    # 3. Vision results
    # --------------------------------------------------

    if vision_result is not None:

        for index, element in enumerate(
            vision_result.elements,
            start=1,
        ):

            # ------------------------------------------
            # Determine source type
            # ------------------------------------------

            if element.type == "table":
                source_type = "table"

            elif element.type == "diagram":
                source_type = "diagram"

            elif element.type == "chart":
                source_type = "chart"

            else:
            # photo, image_group, image_text,
            # infographic, figure, other
            # are grouped as image at the KnowledgeUnit level.
                source_type = "image"

            # ------------------------------------------
            # Build RAG content
            # ------------------------------------------

            content_parts: list[str] = []

            if element.description:
                content_parts.append(
                    f"ประเภท: {element.description}"
                )

            if element.extracted_text:
                content_parts.append(
                    "ข้อมูลจากภาพ:\n"
                    + element.extracted_text
                )

            if element.visual_description:
                content_parts.append(
                    "คำอธิบายภาพ:\n"
                    + element.visual_description
                )

            content = "\n\n".join(
                part
                for part in content_parts
                if part.strip()
            )

            # Nothing useful to store
            if not content.strip():
                continue

            unit_id = make_unit_id(
                document_id=document_id,
                page_number=page_number,
                source_type=source_type,
                index=index,
                source_origin="vision",
            )

            units.append(
                KnowledgeUnit(
                    id=unit_id,
                    document_id=document_id,
                    source_file=pdf.name,
                    page_number=page_number,
                    source_type=source_type,
                    content=content,
                    extracted_text=element.extracted_text,
                    visual_description=element.visual_description,
                    title=element.description,
                    metadata={
                        "source": "vision",
                        "vision_status": (
                            element.status
                            or "unknown"
                        ),
                    },
                )
            )

    # --------------------------------------------------
    # Page-level Vision summary
    # --------------------------------------------------

    if (
        vision_result is not None
        and vision_result.summary
        and vision_result.has_meaningful_visual_content
    ):

        summary_unit_id = make_unit_id(
            document_id=document_id,
            page_number=page_number,
            source_type="mixed",
            index=1,
            source_origin="vision_summary",
        )

        units.append(
            KnowledgeUnit(
                id=summary_unit_id,
                document_id=document_id,
                source_file=pdf.name,
                page_number=page_number,
                source_type="mixed",
                content=vision_result.summary,
                title="Visual summary",
                metadata={
                    "source": "vision_summary",
                },
            )
        )

    return units