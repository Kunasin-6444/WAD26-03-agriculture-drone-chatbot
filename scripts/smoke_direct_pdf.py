"""One-page live PDF embedding -> retrieval -> transcription -> grounded answer.

Uses a dedicated smoke collection/cache. No LINE messages or legacy index writes.
Run: python -m scripts.smoke_direct_pdf
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sys
import time


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reader-model")
    parser.add_argument("--output", default="cache/eval/DIRECT_PDF_SMOKE_REPORT.json")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    from app.rag import direct_pdf as pdf
    from app.rag.evidence import render_grounded_answer
    from app.rag.rag_service import evaluate_evidence

    if args.reader_model:
        os.environ["PDF_READER_MODEL"] = args.reader_model
    pdf.COLLECTION_NAME = "drone_pdf_pages_v1_smoke"
    pdf.CACHE_DIR = pdf.ROOT / "cache" / "direct_pdf_smoke"
    report = {"generated_at": datetime.now(timezone(timedelta(hours=7))).isoformat(),
              "mode": "direct_pdf_smoke", "reader_model": os.getenv("PDF_READER_MODEL", "gemini-3.5-flash-lite"),
              "note": "One-page integration probe, not a retrieval quality or throughput benchmark. Cached stages may be faster."}
    report["api_calls"] = {"pdf_embedding": 0, "query_embedding": 0, "pdf_read": 0}
    original_embedding = pdf.embed_pdf_page
    original_query_embedding = pdf.embed_text
    original_reader = pdf.client.models.generate_content

    def bounded_embedding(data):
        report["api_calls"]["pdf_embedding"] += 1
        return original_embedding(data, max_retries=1, timeout_seconds=30)

    def query_embedding(*a, **k):
        report["api_calls"]["query_embedding"] += 1
        return original_query_embedding(*a, **k)

    def diagnostic_reader(*a, **k):
        report["api_calls"]["pdf_read"] += 1
        try:
            return original_reader(*a, **k)
        except Exception as exc:
            # Keep actionable provider errors without printing credentials or request payloads.
            message = str(getattr(exc, "message", type(exc).__name__))
            for key in (os.getenv("GOOGLE_API_KEY"), os.getenv("API_KEY")):
                if key:
                    message = message.replace(key, "[redacted]")
            report["reader_error"] = {"type": type(exc).__name__, "code": getattr(exc, "code", None),
                                      "message": message[:600]}
            raise

    pdf.client.models.generate_content = diagnostic_reader
    pdf.embed_pdf_page = bounded_embedding
    pdf.embed_text = query_embedding
    try:
        source = next((pdf.ROOT / "data").glob("UAV07*.pdf"))
        report["ingestion"] = pdf.ingest_pdf_direct(str(source), "UAV07", 12, 12)
        query = "หัวฉีดพัดส้มมีอัตราการไหลเท่าไร"
        started = time.monotonic()
        evidence = pdf.search_pdf_evidence(query, top_k=1)
        report["retrieval_and_read_seconds"] = round(time.monotonic() - started, 3)
        report["evidence"] = [e.__dict__ for e in evidence]
        if not evidence or evidence[0].page_number != "12" or "500" not in evidence[0].content:
            raise RuntimeError("Expected page-12 nozzle table evidence was not read")
        started = time.monotonic()
        result = evaluate_evidence(query, evidence, deadline=started + 12, max_attempts=1)
        report["answer_seconds"] = round(time.monotonic() - started, 3)
        report["answer_status"] = result.status
        report["answer"] = render_grounded_answer(result, evidence)
        report["passed"] = result.status == "sufficient" and bool(result.claims)
    except Exception as exc:
        report["passed"] = False
        chain = []
        while exc:
            chain.append({"type": type(exc).__name__, "code": getattr(exc, "code", None)})
            exc = exc.__cause__
        report["errors"] = chain
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "evidence"}, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
