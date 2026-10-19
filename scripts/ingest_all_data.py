"""Legacy batch ingest (text/direct modes).

For text mode prefer ``python -m scripts.ingest``: it skips unchanged files and never replaces
files already in the index from an older pipeline unless named with --force. This script
re-ingests EVERY PDF in data/ with the older chunker.
"""
from pathlib import Path
import argparse
import sys
import time

from scripts.ingest_pdf import ingest_pdf
from app.rag.source_policy import canonical_document_id, is_excluded_document


def ingest_all(mode: str = "text"):
    data_dir = Path("data")
    if not data_dir.exists():
        print("Data directory 'data/' not found.")
        return

    pdf_files = [pdf for pdf in data_dir.glob("*.pdf") if not is_excluded_document(pdf.name)]
    print(f"Found {len(pdf_files)} PDF files in data/ directory.")
    print("=" * 60)

    failed = []
    for idx, pdf_path in enumerate(pdf_files, start=1):
        doc_id = canonical_document_id(pdf_path.name)
        print(f"\n[{idx}/{len(pdf_files)}] Ingesting: {pdf_path.name} (Doc ID: {doc_id})")
        try:
            report = ingest_pdf(str(pdf_path), doc_id, mode=mode)
            if report and report.get("complete") is False:
                failed.append(pdf_path.name)
                print(f"[INCOMPLETE] {pdf_path.name}; inspect its ingestion report")
            else:
                print(f"[OK] Successfully ingested {pdf_path.name}")
        except Exception as exc:
            print(f"[FAILED] Failed to ingest {pdf_path.name}: {exc}")
            failed.append(pdf_path.name)
        
        time.sleep(2)
    if failed:
        raise SystemExit(f"Ingestion failed for {len(failed)} file(s)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["text", "direct"], default="text")
    ingest_all(mode=parser.parse_args().mode)
