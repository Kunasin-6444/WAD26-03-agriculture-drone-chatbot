from pathlib import Path
import sys
import time

from app.ingestion.knowledge_builder import (
    build_page_knowledge_units,
)
from app.ingestion.vision_extractor import (
    analyze_pdf_page,
)
from app.rag.chunking import (
    chunk_knowledge_units,
)
from app.rag.vector_store import (
    add_chunks,
)
from app.rag.source_policy import is_excluded_document


def ingest_pdf(
    pdf_path: str,
    document_id: str,
    force_vision: bool = False,
    start_page: int = 1,
    end_page: int | None = None,
) -> None:
    """
    Ingest one PDF into Chroma.

    Pipeline:

        PDF
        -> Text / Native Tables / Vision
        -> Knowledge Units
        -> Chunks
        -> Embeddings
        -> Chroma
    """

    pdf = Path(pdf_path)

    if is_excluded_document(pdf.name):
        raise ValueError("UAV01/UA03 are excluded; use CAAT UAS Portal")

    if not pdf.exists():
        raise FileNotFoundError(pdf)

    # --------------------------------------------------
    # Open PDF only to get page count
    # --------------------------------------------------

    import pymupdf

    doc = pymupdf.open(pdf)

    try:
        total_pages = len(doc)
    finally:
        doc.close()

    actual_start = max(1, start_page)
    actual_end = min(total_pages, end_page) if end_page else total_pages

    print("=" * 60)
    print("PDF INGESTION")
    print("=" * 60)
    print(f"File : {pdf.name}")
    print(f"Pages: {actual_start} to {actual_end} (Total document: {total_pages})")
    print()

    all_units = []

    # --------------------------------------------------
    # Process each page
    # --------------------------------------------------

    for page_number in range(
        actual_start,
        actual_end + 1,
    ):

        print(
            f"[{page_number}/{total_pages}] "
            f"Processing page..."
        )

        # ----------------------------------------------
        # Vision
        # ----------------------------------------------

        vision_result = analyze_pdf_page(
            pdf_path=str(pdf),
            page_number=page_number,
            force_vision=force_vision,
        )

        # Respect free-tier RPM rate limit
        time.sleep(2.5)

        if vision_result.summary and vision_result.summary.startswith("[VISION_SKIPPED]"):
            print(f"    Vision: Skipped ({vision_result.summary[17:]}) -> Native PyMuPDF")
        elif vision_result.summary and vision_result.summary.startswith("[VISION_EXTRACTION_FAILED]"):
            print(f"    Vision: Failed -> Native PyMuPDF fallback")
        else:
            print(f"    Vision: {len(vision_result.elements)} visual elements")

        # ----------------------------------------------
        # Build Knowledge Units
        # ----------------------------------------------

        page_units = build_page_knowledge_units(
            pdf_path=str(pdf),
            document_id=document_id,
            page_number=page_number,
            vision_result=vision_result,
        )

        all_units.extend(page_units)

        print(
            f"    Knowledge Units: "
            f"{len(page_units)}"
        )

    # --------------------------------------------------
    # Chunk
    # --------------------------------------------------

    print()
    print(
        f"Total Knowledge Units: "
        f"{len(all_units)}"
    )

    print()
    print("Chunking...")

    chunks = chunk_knowledge_units(
        units=all_units,
        chunk_size=800,
        chunk_overlap=120,
    )

    print(
        f"Total Chunks: "
        f"{len(chunks)}"
    )

    # --------------------------------------------------
    # Embedding + Chroma
    # --------------------------------------------------

    print()
    print("Embedding + Chroma...")

    # Existing chunks for these pages are replaced only after every embedding
    # succeeded, so a mid-run quota failure cannot leave the KB with holes.
    add_chunks(
        chunks=chunks,
        replace_source_file=pdf.name,
        replace_pages=range(actual_start, actual_end + 1),
    )

    print()
    print("=" * 60)
    print("INGESTION COMPLETE")
    print("=" * 60)


def main():
    if len(sys.argv) < 3:
        print(
            "Usage:\n"
            "python -m scripts.ingest_pdf "
            '"<pdf_path>" <document_id> [--force-vision] [--pages <start>-<end>]'
        )

        raise SystemExit(1)

    pdf_path = sys.argv[1]
    document_id = sys.argv[2]
    force_vision = "--force-vision" in sys.argv

    start_page = 1
    end_page = None

    if "--pages" in sys.argv:
        idx = sys.argv.index("--pages")
        if idx + 1 < len(sys.argv):
            parts = sys.argv[idx + 1].split("-")
            start_page = int(parts[0])
            if len(parts) > 1 and parts[1]:
                end_page = int(parts[1])

    ingest_pdf(
        pdf_path=pdf_path,
        document_id=document_id,
        force_vision=force_vision,
        start_page=start_page,
        end_page=end_page,
    )


if __name__ == "__main__":
    main()
