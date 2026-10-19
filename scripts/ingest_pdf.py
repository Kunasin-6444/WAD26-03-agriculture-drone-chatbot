"""Legacy single-file ingest (text/direct modes). Text mode: prefer ``python -m scripts.ingest``."""
from pathlib import Path
import argparse
import hashlib
import json
import time
from dataclasses import asdict
from uuid import uuid4

from app.ingestion.dedupe import drop_covered_native_units
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
from app.rag.embedding import EMBEDDING_MODEL


def _save_report(report: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def ingest_pdf(
    pdf_path: str,
    document_id: str,
    force_vision: bool = False,
    start_page: int = 1,
    end_page: int | None = None,
    mode: str = "text",
    report_path: str | Path | None = None,
) -> dict | None:
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

    started = time.monotonic()
    if mode == "direct":
        if force_vision:
            raise ValueError("--force-vision is only supported in text mode")
        from app.rag.direct_pdf import ingest_pdf_direct
        report = ingest_pdf_direct(pdf_path, document_id, start_page, end_page)
        if report_path:
            _save_report(report, Path(report_path))
        return report
    if mode != "text":
        raise ValueError("Ingestion mode must be text or direct")
    pdf = Path(pdf_path)

    if is_excluded_document(pdf.name):
        raise ValueError("UAV01/UA03 are excluded; use CAAT UAS Portal")

    if not pdf.exists():
        raise FileNotFoundError(pdf)
    if not document_id.strip():
        raise ValueError("document_id cannot be empty")
    source_sha256 = hashlib.sha256(pdf.read_bytes()).hexdigest()

    # --------------------------------------------------
    # Open PDF only to get page count
    # --------------------------------------------------

    import pymupdf

    doc = pymupdf.open(pdf)

    try:
        total_pages = len(doc)
    finally:
        doc.close()

    actual_start = start_page
    actual_end = total_pages if end_page is None else end_page
    if not 1 <= actual_start <= actual_end <= total_pages:
        raise ValueError(f"Page range must be within 1..{total_pages}")
    requested = list(range(actual_start, actual_end + 1))
    report = {"mode": "text", "source_file": pdf.name, "document_id": document_id,
              "source_sha256": source_sha256, "embedding_model": EMBEDDING_MODEL,
              "requested_pages": requested, "processed_pages": [], "failed_pages": {},
              "degraded_pages": [], "empty_pages": [], "chunks": 0, "complete": False}
    key = hashlib.sha256(f"{pdf.name}:{source_sha256}".encode()).hexdigest()
    destination = Path(report_path) if report_path else Path(__file__).resolve().parents[1] / "cache" / "ingestion" / f"{key}.json"

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

        try:
            vision_result = analyze_pdf_page(
                pdf_path=str(pdf), page_number=page_number, force_vision=force_vision,
                document_sha256=source_sha256,
            )
            degraded = bool(vision_result.summary and vision_result.summary.startswith("[VISION_EXTRACTION_FAILED]"))
            if degraded:
                report["degraded_pages"].append(page_number)
                print("    Vision unavailable; keeping the previously published page", flush=True)
                continue
            page_units = build_page_knowledge_units(
                pdf_path=str(pdf), document_id=document_id, page_number=page_number,
                vision_result=vision_result,
            )
            page_units = drop_covered_native_units(page_units, page_number)
            if not page_units:
                report["empty_pages"].append(page_number)
                continue
            for unit in page_units:
                unit.metadata.update(source_sha256=source_sha256, ingestion_version="text_v3",
                                     extraction_complete="false" if degraded else "true")
            all_units.extend(page_units)
            report["processed_pages"].append(page_number)
            print(f"    Knowledge Units: {len(page_units)}", flush=True)
        except Exception as exc:
            report["failed_pages"][str(page_number)] = type(exc).__name__
            print(f"    Page {page_number} failed ({type(exc).__name__}); continuing", flush=True)

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
    report["chunks"] = len(chunks)
    records_path = destination.with_suffix(".records.json")
    _save_report({"schema": "ingestion_records_v1", "source_file": pdf.name, "source_sha256": source_sha256,
                  "units": [unit.model_dump() for unit in all_units],
                  "chunks": [asdict(chunk) for chunk in chunks]}, records_path)
    report["records_path"] = str(records_path)
    try:
        if hashlib.sha256(pdf.read_bytes()).hexdigest() != source_sha256:
            raise RuntimeError("Source PDF changed during ingestion; refusing to publish mixed versions")
        full_file = (actual_start == 1 and actual_end == total_pages
                     and report["processed_pages"] == requested and not report["degraded_pages"])
        if chunks:
            add_chunks(chunks=chunks, replace_source_file=pdf.name,
                       replace_pages=None if full_file else report["processed_pages"])
    except Exception as exc:
        report["publish_error"] = type(exc).__name__
        report["seconds"] = round(time.monotonic() - started, 3)
        _save_report(report, destination)
        raise
    report["complete"] = bool(chunks and not report["failed_pages"] and not report["degraded_pages"] and not report["empty_pages"])
    report["seconds"] = round(time.monotonic() - started, 3)
    _save_report(report, destination)

    print()
    print("=" * 60)
    print("INGESTION COMPLETE" if report["complete"] else "INGESTION INCOMPLETE — inspect report")
    print("=" * 60)
    print(f"Report: {destination}")
    return report


def main():
    parser = argparse.ArgumentParser(description="Ingest PDFs as text chunks or direct PDF page embeddings")
    parser.add_argument("pdf_path")
    parser.add_argument("document_id")
    parser.add_argument("--mode", choices=["text", "direct"], default="text")
    parser.add_argument("--force-vision", action="store_true")
    parser.add_argument("--pages", help="One page or a range, e.g. 12 or 12-14")
    parser.add_argument("--report", help="Write ingestion coverage, failures and provenance as JSON")
    args = parser.parse_args()
    start_page = 1
    end_page = None
    if args.pages:
        try:
            parts = args.pages.split("-")
            if len(parts) > 2:
                raise ValueError
            start_page = int(parts[0])
            end_page = int(parts[1]) if len(parts) == 2 and parts[1] else (start_page if len(parts) == 1 else None)
            if start_page < 1 or (end_page is not None and end_page < start_page):
                raise ValueError
        except ValueError:
            parser.error("--pages must be a positive page number or an ascending range")

    report = ingest_pdf(
        pdf_path=args.pdf_path,
        document_id=args.document_id,
        force_vision=args.force_vision,
        start_page=start_page,
        end_page=end_page,
        mode=args.mode,
        report_path=args.report,
    )
    if report and report.get("complete") is False:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
