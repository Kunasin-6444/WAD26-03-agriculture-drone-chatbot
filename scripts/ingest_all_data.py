from pathlib import Path
import sys
import time

from scripts.ingest_pdf import ingest_pdf
from app.rag.source_policy import canonical_document_id, is_excluded_document


def ingest_all():
    data_dir = Path("data")
    if not data_dir.exists():
        print("Data directory 'data/' not found.")
        return

    pdf_files = [pdf for pdf in data_dir.glob("*.pdf") if not is_excluded_document(pdf.name)]
    print(f"Found {len(pdf_files)} PDF files in data/ directory.")
    print("=" * 60)

    for idx, pdf_path in enumerate(pdf_files, start=1):
        doc_id = canonical_document_id(pdf_path.name)
        print(f"\n[{idx}/{len(pdf_files)}] Ingesting: {pdf_path.name} (Doc ID: {doc_id})")
        try:
            ingest_pdf(str(pdf_path), doc_id)
            print(f"[OK] Successfully ingested {pdf_path.name}")
        except Exception as exc:
            print(f"[FAILED] Failed to ingest {pdf_path.name}: {exc}")
        
        time.sleep(2)


if __name__ == "__main__":
    ingest_all()
