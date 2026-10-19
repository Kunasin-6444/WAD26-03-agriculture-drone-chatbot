"""Live acceptance/latency evaluation; no LINE messages or database writes.

python -m scripts.evaluate_acceptance --limit 3 --output cache/eval/LIVE_ACCEPTANCE_REPORT.json
Numbers in this report describe automatic contract checks, not a hallucination rate.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
import time
from decimal import Decimal
from statistics import median
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.rag.crag_service import CragResponse, run_crag_pipeline

CASES = [
    {"query": "หัวฉีดพัดส้มมีอัตราการไหลเท่าไรต่อหัวฉีด", "sources": ["knowledge_base"], "terms": ["500", "1600"], "citations": [], "citation_groups": [["UAV07", "หน้า 12"], ["UAV06", "หน้า 5"]], "target_seconds": 8},
    {"query": "ที่ความสูง 1 เมตร หน้ากว้างการฉีดพ่นต่อหัวเท่าไร", "sources": ["knowledge_base"], "terms": ["2.8"], "citations": [], "citation_groups": [["UAV07", "หน้า 12"], ["UAV06", "หน้า 5"]], "target_seconds": 8},
    {"query": "พัดส้มมีอัตราการไหลและหน้ากว้างพ่นที่ความสูง 1 เมตรเท่าไร", "sources": ["knowledge_base"], "terms": ["500", "2.8"], "citations": [], "citation_groups": [["UAV07"], ["UAV06"]], "target_seconds": 8},
    {"query": "หัวฉีดพัดส้มกับพัดน้ำเงินต่างกันอย่างไร", "sources": ["knowledge_base"], "terms": ["ส้ม", "น้ำเงิน"], "citations": ["UAV07"], "target_seconds": 8},
    {"query": "พัดฟ้ากับพัดส้มต่างกันอย่างไร", "sources": ["knowledge_base"], "terms": ["ส้ม"], "citations": ["UAV07"], "target_seconds": 8},
    {"query": "แนะนำการเลือกใช้หัวฉีดโดรนเกษตรและอัตราการไหล", "sources": ["knowledge_base"], "terms": ["หัวฉีด", "500"], "citations": ["UAV07"], "target_seconds": 8},
    {"query": "ฉีดพ่นคุมดินควรใช้หัวฉีดอะไร", "sources": ["knowledge_base"], "terms": ["หัวฉีด"], "citations": ["UAV07"], "target_seconds": 8},
    {"query": "ฉีดดพ่นควรเลือกหัวฉีดแบบไหน", "sources": ["knowledge_base"], "terms": ["หัวฉีด"], "citations": ["UAV"], "target_seconds": 8},
    {"query": "โดรนฉีดพ่นควรบินสูงเท่าไร", "sources": ["knowledge_base"], "terms": ["ความสูง"], "citations": ["UAV"], "target_seconds": 8},
    {"query": "ก่อนอ้อยงอกควรใช้สารอะไรควบคุมวัชพืชใบแคบ", "sources": ["knowledge_base"], "terms": ["สาร"], "citations": ["UAV"], "target_seconds": 8},
    {"query": "ข้อควรระวังในการผสมสารกำจัดวัชพืชมากกว่า 1 ชนิด", "sources": ["knowledge_base"], "terms": ["สาร"], "citations": ["UAV"], "target_seconds": 8},
    {"query": "วัชพืชในข้าวโพดควรควบคุมอย่างไร", "sources": ["knowledge_base"], "terms": ["ข้าวโพด"], "citations": ["UAV"], "target_seconds": 8},
    {"query": "การควบคุมวัชพืชในอ้อยช่วงแตกกอ", "sources": ["knowledge_base"], "terms": ["อ้อย"], "citations": ["UAV"], "target_seconds": 8},
    {"query": "GSD คืออะไรเกี่ยวข้องกับความละเอียดภาพอย่างไร", "sources": ["knowledge_base"], "terms": ["GSD"], "citations": ["UAV1"], "target_seconds": 8},
    {"query": "ควรตั้ง overlap สำหรับสำรวจแปลงอย่างไร", "sources": ["knowledge_base"], "terms": ["overlap"], "citations": ["UAV1"], "target_seconds": 8},
    {"query": "หลักการตั้งค่าโดรนสำรวจแปลงและถ่ายภาพทางอากาศ", "sources": ["knowledge_base"], "terms": ["ภาพ"], "citations": ["UAV1"], "target_seconds": 8},
    {"query": "ข้อจำกัดสภาพอากาศในการถ่ายภาพสำรวจแปลง", "sources": ["knowledge_base"], "terms": ["ภาพ"], "citations": ["UAV1"], "target_seconds": 8},
    {"query": "การขึ้นทะเบียนโดรนต้องทำอย่างไร", "sources": ["caat_portal"], "terms": [], "citations": ["caat.or.th"], "target_seconds": 15},
    {"query": "บินโดรนใกล้สนามบินต้องขออนุญาตอย่างไร", "sources": ["caat_portal"], "terms": [], "citations": ["caat.or.th"], "target_seconds": 15},
    {"query": "กฎหมายโดรนบินสูงได้ไม่เกินกี่เมตร", "sources": ["caat_portal"], "terms": [], "citations": ["caat.or.th"], "target_seconds": 15},
    {"query": "ราคาน้ำมันดีเซลวันนี้เท่าไร", "sources": ["web_fallback", "abstain"], "terms": [], "citations": [], "target_seconds": 15},
    {"query": "หัวฉีดพัดส้มอัตราการไหลเท่าไรและราคาน้ำมันดีเซลวันนี้เท่าไร", "sources": ["hybrid", "knowledge_base"], "terms": ["500"], "citations": ["UAV07"], "target_seconds": 15},
    {"query": "GSD คืออะไร และโดรนสำรวจรุ่นใหม่ล่าสุดราคาเท่าไร", "sources": ["hybrid", "knowledge_base"], "terms": ["GSD"], "citations": ["UAV1"], "target_seconds": 15},
    {"query": "โดรนเกษตรบินไปฉีดปุ๋ยบนดาวอังคารได้ไหม", "sources": ["abstain"], "terms": [], "citations": [], "target_seconds": 15},
    {"query": "โดรนเกษตรดำน้ำฉีดปุ๋ยใต้ทะเลได้ไหม", "sources": ["abstain"], "terms": [], "citations": [], "target_seconds": 15},
    {"query": "อัตราการไหลของหัวฉีดที่ไม่มีชื่อรุ่นเท่าไร", "sources": ["knowledge_base", "abstain"], "terms": [], "citations": [], "target_seconds": 15},
    {"query": "แนะนำวิธีพิมพ์คำถามเพื่อขอข้อมูลโดรนเกษตร", "sources": ["bot_usage"], "terms": ["คำถาม"], "citations": [], "target_seconds": 1},
    {"query": "   ", "sources": ["abstain"], "terms": ["กรุณาระบุคำถาม"], "citations": [], "target_seconds": 1},
]

# Source alternatives were checked visually in the original PDFs, not inferred
# from whichever source a model happened to choose. See tests/data/source_gold.json.
for _index in (3, 4, 5):
    CASES[_index]["citations"] = []
    CASES[_index]["citation_groups"] = [["UAV07", "หน้า 12"], ["UAV06", "หน้า 5"]]
CASES[6]["citations"] = []
CASES[6]["citation_groups"] = [["UAV07"], ["UAV09", "หน้า 17"]]
# Original PDF figures show GSD examples; an explicit definition may require
# an official web supplement. A correct KB+web answer is required by R4.
CASES[13]["sources"] = ["knowledge_base", "hybrid"]
# Weather/camera operating conditions can require official guidance beyond the
# PDF examples. R4 permits web supplementation; this is a web-budget case.
CASES[16].update(sources=["knowledge_base", "hybrid", "web_fallback"], citations=[], target_seconds=15)
# Original UAV06 p18 says BEFORE WEEDS emerge, not before sugarcane emerges.
# Require the actual timing and a supported chemical, rather than the word "สาร".
CASES[9].update(original_query=CASES[9]["query"],
    query="ก่อนวัชพืชงอกในไร่อ้อยควรใช้สารอะไรควบคุมวัชพืชใบแคบ",
    terms=["ก่อนวัชพืชงอก"], answer_any=["อาลาคลอร์", "แอทราซีน", "เมทริบูซีน", "ไดยูรอน",
    "อ๊อกซี่ฟลูออร์เฟน", "ซัลเฟนทราโซน", "เฮ็กซาซิโนน", "เพนดิเมทาลิน"])
# Verified web supplementation after a rejected KB generation is allowed by R4.
# Keep the KB latency target; unnecessary fallback still fails performance checks.
CASES[12]["sources"] = ["knowledge_base", "hybrid"]


def numeric_values(text: str) -> set[Decimal]:
    return {Decimal(n.replace(",", "")) for n in re.findall(r"\d+(?:,\d{3})*(?:\.\d+)?", text)}


def source_cases(path: Path) -> list[dict]:
    from scripts.retrieval_metrics import validate_cases, verify_source_manifest
    data = json.loads(path.read_text(encoding="utf-8"))
    verify_source_manifest(data, Path(__file__).resolve().parents[1] / "data")
    validate_cases(data["cases"])
    result = []
    for case in data["cases"]:
        values = [str(fact["value"]) for fact in case.get("facts", []) if "value" in fact]
        result.append({**case, "sources": ["knowledge_base"], "terms": [], "citations": [],
                       "target_seconds": 8, "required_numbers": " ".join(values), "require_sufficient": True})
    return result


def assess(case: dict, response, seconds: float) -> dict:
    reasons = []
    if response.source_type not in case["sources"]:
        reasons.append("unexpected_source_type")
    if any(term.casefold() not in response.answer.casefold() for term in case["terms"]):
        reasons.append("missing_expected_answer_aspect")
    if any(term not in response.answer for term in case["citations"]):
        reasons.append("missing_expected_source")
    groups = case.get("citation_groups", [])
    if groups and not any(all(term in response.answer for term in group) for group in groups):
        reasons.append("missing_expected_source")
    if response.source_type not in {"abstain", "bot_usage"} and not response.evidence_trace:
        reasons.append("missing_evidence_trace")
    if case.get("require_sufficient") and response.grade != "CORRECT":
        reasons.append("answer_incomplete")
    body = " ".join(c.get("text", "") for c in response.evidence_trace)
    if case.get("answer_any") and not any(term in body for term in case["answer_any"]):
        reasons.append("missing_verified_answer_option")
    if not numeric_values(case.get("required_numbers", "")).issubset(numeric_values(body)):
        reasons.append("missing_verified_numeric_fact")
    cited = {(e.get("source_file"), str(e.get("page_number"))) for c in response.evidence_trace for e in c.get("evidence", [])}
    for group in case.get("evidence_groups", []):
        if not any((p["source_file"], str(p["page_number"])) in cited for p in group["pages"]):
            reasons.append("missing_verified_source_aspect")
            break
    web_urls = [e.get("url", "") for c in response.evidence_trace for e in c.get("evidence", []) if e.get("url")]
    if response.source_type in {"web_fallback", "hybrid", "caat_portal"}:
        from app.rag.source_policy import valid_web_url
        if not web_urls or any(not valid_web_url(url) or url not in response.answer for url in web_urls):
            reasons.append("missing_exact_web_page_citation")
    if case.get("web_domains"):
        from app.rag.web_fallback import get_domain
        for domain in case["web_domains"]:
            if not any((get_domain(url) == domain or get_domain(url).endswith("." + domain)) and url in response.answer for url in web_urls):
                reasons.append("missing_exact_web_page_citation")
                break
    if len(response.answer) > 4200:
        reasons.append("answer_too_long")
    return {"contract_pass": not reasons, "latency_pass": seconds <= case["target_seconds"], "reasons": reasons}


def summarize(rows: list[dict]) -> dict:
    durations = sorted(row["seconds"] for row in rows)
    if not durations:
        raise ValueError("Cannot summarize an empty evaluation")
    return {"total": len(rows), "contract_passed": sum(row["contract_pass"] for row in rows),
            "latency_passed": sum(row["latency_pass"] for row in rows),
            "mean_seconds": round(sum(durations) / len(durations), 3), "p50_seconds": median(durations),
            "p95_seconds": durations[max(0, math.ceil(len(durations) * .95) - 1)],
            "provider_error_requests": sum(any(d.get("error", "").startswith("provider_") or d.get("llm_unavailable")
                                               for d in row.get("diagnostics", [])) for row in rows)}


def run_configuration() -> dict:
    import os
    from app.rag import rag_service
    return {"model": os.getenv("RAG_MODEL", "gemini-3.5-flash-lite"),
            "retrieval_mode": os.getenv("PDF_RETRIEVAL_MODE", "text"),
            "reranker": os.getenv("RETRIEVER_RERANK", "diverse"),
            "structured_output": rag_service.STRUCTURED_OUTPUT,
            "secondary_structured_output": rag_service.SECONDARY_STRUCTURED_OUTPUT}


def runtime_signature() -> str:
    root = Path(__file__).resolve().parents[1]
    files = sorted(p for p in (root / "app").rglob("*") if p.suffix in {".py", ".txt"})
    files.append(Path(__file__).resolve())
    digest = hashlib.sha256()
    for path in files:
        digest.update(str(path.relative_to(root)).replace("\\", "/").encode())
        digest.update(b"\0" + path.read_bytes())
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--gold", type=Path, help="Optional source-annotated answer cases")
    parser.add_argument("--cases", type=Path, help="Optional additional acceptance cases JSON")
    parser.add_argument("--split", choices=["all", "dev", "holdout"], default="all")
    parser.add_argument("--warmup", action="store_true", help="Exclude server startup work, like app lifespan")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--concurrency", type=int, choices=[1, 2, 3], default=1)
    parser.add_argument("--output", default="cache/eval/LIVE_ACCEPTANCE_REPORT.json")
    args = parser.parse_args()
    if args.gold and args.cases:
        parser.error("Choose --gold or --cases")
    if not args.gold and args.split != "all":
        parser.error("--split requires --gold")
    cases = (source_cases(args.gold) if args.gold else json.loads(args.cases.read_text(encoding="utf-8"))["cases"]
             if args.cases else CASES)
    if args.gold and args.split != "all":
        cases = [case for case in cases if case["split"] == args.split]
    limit = args.limit if args.limit is not None else len(cases)
    if limit < 1 or args.repeat < 1 or not 0 <= args.offset < len(cases):
        parser.error("--limit must be positive and --offset must select an existing case")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    signature = runtime_signature()
    if args.warmup:
        from app.rag.rag_service import warm_up_retrieval
        warm_up_retrieval()
    rows = []

    def run_one(iteration, index, case):
        started = time.monotonic()
        try:
            response = run_crag_pipeline(case["query"])
        except Exception as exc:
            response = CragResponse("Pipeline failed", "abstain", "INCORRECT", type(exc).__name__,
                                    diagnostics=[{"stage": "pipeline", "error": "pipeline_exception"}])
        seconds = round(time.monotonic() - started, 3)
        check = assess(case, response, seconds)
        return {**case, "case_id": case.get("id", index), "id": index, "iteration": iteration,
                **asdict(response), "seconds": seconds, **check}

    jobs = [(iteration, index, case) for iteration in range(1, args.repeat + 1)
            for index, case in enumerate(cases[args.offset:args.offset + limit], args.offset + 1)]
    executor = ThreadPoolExecutor(max_workers=args.concurrency) if args.concurrency > 1 else None
    try:
        completed = (as_completed([executor.submit(run_one, *job) for job in jobs]) if executor
                     else (run_one(*job) for job in jobs))
        for value in completed:
            row = value.result() if executor else value
            rows.append(row)
            print(f"Q{row['id']:02d} run={row['iteration']}: contract={row['contract_pass']} latency={row['seconds']}s source={row['source_type']}", flush=True)
            output = Path(args.output)
            output.parent.mkdir(parents=True, exist_ok=True)
            routes = {row["source_type"] for row in rows}
            report = {"generated_at": datetime.now(timezone(timedelta(hours=7))).isoformat(), "mode": "live",
                "note": "Automatic source/aspect checks; semantic review against originals remains necessary. Sample p95 is not a production guarantee. Provider failures stay in the denominator.",
                "warmup": args.warmup, "answer_cache": "bypassed", "repeat": args.repeat,
                "runtime_sha256": signature,
                "runtime_changed_during_run": len(rows) == len(jobs) and signature != runtime_signature(),
                "concurrency": args.concurrency, "configuration": run_configuration(),
                "dataset": str(args.gold or args.cases) if (args.gold or args.cases) else f"acceptance_{len(cases)}",
                "complete_run": len(rows) == len(jobs), **summarize(rows),
                "by_source": {route: summarize([r for r in rows if r["source_type"] == route]) for route in sorted(routes)},
                "results": sorted(rows, key=lambda r: (r["iteration"], r["id"]))}
            output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    finally:
        if executor:
            executor.shutdown(wait=True)
    # An acceptance command must not appear green when its report contains failures.
    return 0 if (report["contract_passed"] == len(rows) and report["latency_passed"] == len(rows)
                 and not report["runtime_changed_during_run"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
