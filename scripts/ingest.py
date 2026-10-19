"""Ingest PDFs into the knowledge base.

    python -m scripts.ingest --dry-run            # what would run and what it would cost (offline)
    python -m scripts.ingest                      # ingest every PDF in data/ that is new or changed
    python -m scripts.ingest "data/X.pdf"         # one file
    python -m scripts.ingest "data/X.pdf" --pages 3-5 --vision never
    python -m scripts.ingest "data/UAV06 ... .pdf" --force   # replace a file ingested by an older pipeline

Unchanged files are skipped. Files already in the index from an older pipeline ("legacy") are
never replaced unless named with --force. Exit code 1 when any file is incomplete or failed.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _pages(value: str) -> tuple[int, int]:
    try:
        parts = value.split("-")
        start = int(parts[0])
        end = int(parts[1]) if len(parts) == 2 else start
        if len(parts) > 2 or start < 1 or end < start:
            raise ValueError
    except ValueError:
        raise argparse.ArgumentTypeError("--pages must be a page number or an ascending range, e.g. 12 or 12-14")
    return start, end


def _open_collection(create: bool):
    import chromadb
    client = chromadb.PersistentClient(path=os.getenv("CHROMA_PATH", str(ROOT / "chroma_db")))
    return client.get_or_create_collection("drone_knowledge") if create else _existing(client)


def _existing(client):
    try:
        return client.get_collection("drone_knowledge")
    except Exception:
        return None


def dry_run(paths: list[Path], options) -> int:
    from app.ingestion.pipeline import estimated_embedding_calls, plan_document
    from app.ingestion.vision_extractor import get_cache_path

    collection = _open_collection(create=False)
    total_vision = total_chunks = 0
    print(f"{'file':44} {'id':10} {'status':11} {'action':6} {'pages':>5} {'vision':>6} {'cached':>6} {'tables':>6} {'~chunks':>7}")
    for pdf in paths:
        plan = plan_document(pdf, options, collection)
        cached = sum(get_cache_path(pdf, page, document_sha256=plan.sha256, structured_tables=True).exists()
                     for page in plan.vision_pages)
        runs = plan.status != "excluded" and (options.force or bool(options.pages) or plan.status in ("new", "partial", "stale"))
        if runs:
            total_vision += len(plan.vision_pages) - cached
            total_chunks += plan.estimated_chunks
        print(f"{pdf.name[:44]:44} {plan.document_id[:10]:10} {plan.status:11} {'ingest' if runs else 'skip':6} {plan.pages:>5} "
              f"{len(plan.vision_pages):>6} {cached:>6} {plan.native_tables:>6} {plan.estimated_chunks:>7}")
        if plan.blank_pages:
            print(f"    blank pages (not an error): {plan.blank_pages}")
        for note in plan.warnings:
            print(f"    warning: {note}")
    print(f"\nvision calls still needed: {total_vision}   (workers run them concurrently)")
    print(f"chunks from the text layer alone: ~{total_chunks}   "
          f"(vision adds more)  embedding calls: ~{estimated_embedding_calls(total_chunks)} batched")
    print("Files with status new/partial/stale are ingested by default; legacy needs --force.")
    return 0


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Ingest PDFs into the knowledge base")
    parser.add_argument("pdfs", nargs="*", type=Path, help="PDF files (default: every PDF in data/)")
    parser.add_argument("--dry-run", action="store_true", help="plan only; offline, no API calls, no index writes")
    parser.add_argument("--pages", type=_pages, help="one page or a range of the (single) file, e.g. 12 or 12-14")
    parser.add_argument("--vision", choices=["auto", "always", "never"], default="auto")
    parser.add_argument("--workers", type=int, help="concurrent vision calls (default VISION_WORKERS or 3)")
    parser.add_argument("--force", action="store_true", help="re-ingest even if unchanged or legacy")
    parser.add_argument("--doc-id", help="document id for a single file (default: from the file name)")
    parser.add_argument("--report-dir", type=Path)
    args = parser.parse_args(argv)

    from app.ingestion.pipeline import Options
    from app.rag.source_policy import is_excluded_document

    paths = args.pdfs or sorted((ROOT / "data").glob("*.pdf"))
    paths = [p for p in paths if args.pdfs or not is_excluded_document(p.name)]
    if not paths:
        parser.error("no PDF files found")
    if (args.pages or args.doc_id) and len(paths) != 1:
        parser.error("--pages and --doc-id need exactly one PDF")
    options = Options(pages=args.pages, vision=args.vision, force=args.force, document_id=args.doc_id)
    if args.workers:
        options.workers = args.workers
    if args.report_dir:
        options.report_dir = args.report_dir

    if args.dry_run:
        return dry_run(paths, options)

    from app.ingestion.pipeline import default_deps, run
    reports = run(paths, options, default_deps())
    for report in reports:
        if report.get("skipped"):
            print(f"[skipped] {report['source_file']}: {report['skipped']}")
    bad = [r["source_file"] for r in reports if not r.get("complete")]
    if bad:
        print(f"\n{len(bad)} file(s) incomplete or failed: {', '.join(bad)}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
