"""Live acceptance/latency evaluation; no LINE messages or database writes.

python -m scripts.evaluate_acceptance --limit 3 --output docs/LIVE_ACCEPTANCE_REPORT.json
Numbers in this report describe automatic contract checks, not a hallucination rate.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.rag.crag_service import run_crag_pipeline

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
    if len(response.answer) > 4200:
        reasons.append("answer_too_long")
    return {"contract_pass": not reasons, "latency_pass": seconds <= case["target_seconds"], "reasons": reasons}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=len(CASES))
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--output", default="docs/LIVE_ACCEPTANCE_REPORT.json")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    rows = []
    for index, case in enumerate(CASES[args.offset:args.offset + args.limit], args.offset + 1):
        started = time.monotonic()
        response = run_crag_pipeline(case["query"])
        seconds = round(time.monotonic() - started, 3)
        check = assess(case, response, seconds)
        rows.append({"id": index, **case, **asdict(response), "seconds": seconds, **check})
        print(f"Q{index:02d}: contract={check['contract_pass']} latency={seconds}s source={response.source_type}", flush=True)
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        durations = sorted(row["seconds"] for row in rows)
        report = {"generated_at": datetime.now(timezone(timedelta(hours=7))).isoformat(), "mode": "live",
            "note": "Automatic evidence/routing/aspect checks; full semantic support requires manual source review. Provider timeouts are request budgets, not latency guarantees.",
            "total": len(rows), "contract_passed": sum(row["contract_pass"] for row in rows),
            "latency_passed": sum(row["latency_pass"] for row in rows), "mean_seconds": round(sum(durations) / len(durations), 3),
            "p95_seconds": durations[max(0, math.ceil(len(durations) * 0.95) - 1)], "results": rows}
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
