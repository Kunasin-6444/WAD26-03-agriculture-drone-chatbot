"""Answer-quality evaluation on the owner-reviewed gold set, one pinned model at a time.

    python -m scripts.evaluate_answers --model gemini-3.8-flash --prompt concise --ids "$(cat tests/data/screening_ids.txt)"
    python -m scripts.evaluate_answers --model gemini-3.8-flash --prompt full --judge-model gpt-5.6-terra   # all dev

Each run answers every case with ONE answer model: fallback models and the secondary provider are
switched off, so a quota or timeout failure is counted as "unavailable" instead of being silently
answered by another model. A different KKU model judges each answer against the owner-approved
expected answer (binary correct / complete / harmful). Results go to cache/eval/ as JSON plus a CSV
the owner can open in Excel to spot-check the judge. No LINE messages, database or index writes.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GOLD = ROOT / "tests" / "data" / "source_gold_2026-10-18.json"
OUT_DIR = ROOT / "cache" / "eval"
ABSTAIN_PREFIX = "ยังไม่พบหลักฐานเพียงพอ"
DEGRADED_PREFIX = "ขณะนี้ระบบกำลังปรับปรุงชั่วคราว"
REQUIREMENT_TEXT = {
    "lead_in": "ขึ้นต้นด้วยประโยคเกริ่นที่ทวนคำถาม แล้วตอบเป็นประโยคเต็ม ไม่ห้วนเป็นวลี",
    "complete_list": "ลิสต์ครบทุกรายการที่ตรงเงื่อนไขพร้อมค่า ไม่เขียนว่าอื่นๆ",
    "explain_mixture_rate": "อธิบายอัตราสารผสมที่เขียนด้วย + ว่าแต่ละสารใช้เท่าไร",
    "state_the_risk": "บอกว่าเสี่ยงโรคหรือแมลงอะไร ไม่ใช่แค่เกณฑ์",
    "what_to_check_per_item": "บอกสั้นๆ ว่าแต่ละรายการต้องตรวจอะไร",
    "focused_with_cautions": "ตอบตรงประเด็นที่ถาม เสริมข้อควรระวังได้ แต่ไม่ปนค่าของบริบทอื่น",
}
JUDGE_PROMPT = """คุณเป็นผู้ตรวจคำตอบของแชทบอทผู้ช่วยนักบินโดรนเกษตร
เทียบ bot_answer กับ reference_answer ที่เจ้าของระบบรับรองแล้ว แล้วตัดสินแบบผ่าน/ไม่ผ่านทีละเกณฑ์
- correct: ไม่มีข้อความที่ขัดกับ reference_answer (ตัวเลข หน่วย หมวดหรือประเภท เงื่อนไข สถานะการใช้) ข้อมูลเสริมที่ไม่ขัดไม่ถือว่าผิด
- complete: มีข้อเท็จจริงสำคัญครบตาม reference_answer ถ้า reference เป็นรายการต้องครบทุกรายการ ถ้า reference บอกว่าต้องตอบว่ายืนยันไม่ได้หรือเอกสารไม่มี bot ต้องไม่ให้ค่าที่เดาเอง
- harmful: มีข้อมูลผิดที่อาจทำให้นักบินทำผิด เช่น อัตราสาร ประเภทวัชพืช หรือข้อบังคับผิด หรือให้ค่าทั้งที่ควรบอกว่ายืนยันไม่ได้
- style_ok: ทำตาม requirements ครบ (ถ้าไม่มี requirements ให้ true)
ไม่ต้องตรวจรูปแบบอ้างอิงท้ายคำตอบ และไม่ต้องสนใจหมายเหตุให้ปรึกษาผู้เชี่ยวชาญที่ระบบเติมเอง
คืน JSON เท่านั้น: {"correct":true,"complete":true,"harmful":false,"style_ok":true,"critique":"เหตุผลสั้นๆ ภาษาไทย"}"""


# --------------------------------------------------
# Pure scoring helpers (unit-tested, no network)
# --------------------------------------------------

def compact(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def missing_terms(answer: str, terms: list[str]) -> list[str]:
    body = compact(answer)
    return [term for term in terms if compact(term) not in body]


def cited_pages(answer: str) -> set[tuple[str, str]]:
    """(file, page) pairs from the server-rendered reference list, page ranges expanded."""
    pages = set()
    for file, first, last in re.findall(r"^\[\d+\]\s+(.+?\.pdf),\s*หน้า\s*(\d+)(?:\s*[–-]\s*(\d+))?\s*$",
                                        answer or "", re.MULTILINE):
        for page in range(int(first), int(last or first) + 1):
            pages.add((file.strip(), str(page)))
    return pages


def outcome(answer: str) -> str:
    text = (answer or "").strip()
    if text.startswith(DEGRADED_PREFIX) or text.startswith("[EXCEPTION"):
        return "unavailable"
    if text.startswith(ABSTAIN_PREFIX):
        return "abstain"
    return "answered"


def parse_judge(raw: str) -> dict:
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", (raw or "").strip())
    data = json.loads(cleaned[cleaned.find("{"):cleaned.rfind("}") + 1])
    verdict = {key: data.get(key) for key in ("correct", "complete", "harmful", "style_ok")}
    if any(type(value) is not bool for value in verdict.values()):
        raise ValueError(f"judge verdict is not boolean: {verdict}")
    verdict["critique"] = str(data.get("critique", ""))[:500]
    verdict["passed"] = verdict["correct"] and verdict["complete"] and not verdict["harmful"]
    return verdict


def judge_messages(case: dict, answer: str) -> list[dict]:
    requirements = [REQUIREMENT_TEXT[name] for name in case.get("answer_requirements", []) if name in REQUIREMENT_TEXT]
    payload = {"question": case["query"], "reference_answer": case["expected_answer"],
               "requirements": requirements, "bot_answer": answer}
    return [{"role": "system", "content": JUDGE_PROMPT},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}]


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[min(len(ordered) - 1, int(round(fraction * (len(ordered) - 1))))], 1)


def summarize(rows: list[dict]) -> dict:
    ran = [row for row in rows if row["outcome"] != "not_run"]
    available = [row for row in ran if row["outcome"] != "unavailable"]
    judged = [row for row in available if row.get("judge")]
    with_terms = [row for row in available if row["must_contain"]]
    with_pages = [row for row in available if row["gold_pages"]]
    seconds = [row["seconds"] for row in available]

    def rate(items, predicate):
        return round(sum(1 for item in items if predicate(item)) / len(items), 3) if items else None

    return {
        "cases": len(rows), "ran": len(ran), "unavailable": len(ran) - len(available),
        "pass_rate": rate(judged, lambda r: r["judge"]["passed"]),
        "correct_rate": rate(judged, lambda r: r["judge"]["correct"]),
        "complete_rate": rate(judged, lambda r: r["judge"]["complete"]),
        "harmful": sum(1 for r in judged if r["judge"]["harmful"]),
        "style_ok_rate": rate(judged, lambda r: r["judge"]["style_ok"]),
        "abstain_rate": rate(available, lambda r: r["outcome"] == "abstain"),
        "must_contain_rate": rate(with_terms, lambda r: not r["missing_terms"]),
        "cited_gold_page_rate": rate(with_pages, lambda r: bool(r["cited_gold_pages"])),
        "seconds_p50": percentile(seconds, 0.5), "seconds_p95": percentile(seconds, 0.95),
        "seconds_max": max(seconds) if seconds else None,
        "judge_errors": sum(1 for r in available if r.get("judge_error")),
    }


def load_cases(path: Path, split: str, include_answer_only: bool) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    cases = [c for c in data["cases"] if split == "all" or c["split"] == split]
    if include_answer_only:
        cases += data.get("answer_only_cases", [])
    return [c for c in cases if c.get("review", {}).get("decision") != "drop"]


# --------------------------------------------------
# Live run
# --------------------------------------------------

def pin_model(model: str, prompt: str, attempt: float | None, kb: float | None, request: float | None) -> None:
    """Must run before any app module is imported: those read the environment at import time."""
    os.environ.update({"RAG_MODEL": model, "RAG_PROMPT": prompt,
                       "LLM_FALLBACK_MODELS": "", "LLM_SECONDARY_BASE_URL": ""})
    for name, value in (("LLM_ATTEMPT_TIMEOUT_SECONDS", attempt), ("KB_GENERATION_BUDGET_SECONDS", kb),
                        ("RAG_REQUEST_TIMEOUT_SECONDS", request)):
        if value is not None:
            os.environ[name] = str(value)


def run(args) -> int:
    pin_model(args.model, args.prompt, args.attempt_timeout, args.kb_budget, args.request_timeout)
    from openai import OpenAI
    from app.config import LLM_API_KEY, LLM_BASE_URL
    from app.rag import rag_service
    from app.rag.crag_service import run_crag_pipeline
    from scripts.retrieval_metrics import evidence_groups

    # The 2026-10-19 terra run was silently answered by another model after one timeout. Refuse to
    # measure unless the pin really took effect (it cannot if app modules were imported earlier).
    if rag_service.FALLBACK_MODELS or rag_service.secondary_enabled():
        raise SystemExit("fallback models are still active; run this script in a fresh process")

    judge = None if args.skip_judge else OpenAI(api_key=LLM_API_KEY, base_url=LLM_BASE_URL, timeout=60, max_retries=0)
    cases = load_cases(args.gold, args.split, not args.no_answer_only)
    if args.ids:
        wanted = [case_id.strip() for case_id in args.ids.split(",") if case_id.strip()]
        known = {case["id"]: case for case in cases}
        unknown = [case_id for case_id in wanted if case_id not in known]
        if unknown:
            raise SystemExit(f"--ids not in split {args.split!r}: {unknown}")
        cases = [known[case_id] for case_id in wanted]
    cases = cases[:args.limit or None]
    rows, unavailable_streak, stopped = [], 0, False
    for index, case in enumerate(cases, 1):
        gold = set().union(*evidence_groups(case, [])) if case.get("evidence_groups") else set()
        row = {"id": case["id"], "query": case["query"], "expected": case["expected_answer"],
               "must_contain": case.get("must_contain", []), "gold_pages": sorted(gold), "outcome": "not_run"}
        rows.append(row)
        if stopped:
            continue
        started = time.monotonic()
        try:
            response = run_crag_pipeline(case["query"])
            answer, source_type = response.answer, response.source_type
        except Exception as exc:  # recorded, never retried with another model
            answer, source_type = f"[EXCEPTION {type(exc).__name__}: {exc}]", "error"
        row.update(seconds=round(time.monotonic() - started, 1), answer=answer, source_type=source_type,
                   outcome=outcome(answer), missing_terms=missing_terms(answer, row["must_contain"]),
                   cited_gold_pages=sorted(cited_pages(answer) & gold))
        if row["outcome"] == "unavailable":
            unavailable_streak += 1
            stopped = unavailable_streak >= 2
        else:
            unavailable_streak = 0
            if judge is not None:
                try:
                    reply = judge.chat.completions.create(model=args.judge_model, messages=judge_messages(case, answer),
                                                          temperature=0, max_tokens=600)
                    row["judge"] = parse_judge(reply.choices[0].message.content)
                except Exception as exc:
                    row["judge_error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
        verdict = row.get("judge", {})
        print(f"[{index}/{len(cases)}] {case['id']:6} {row['outcome']:11} {row['seconds']:5.1f}s "
              f"pass={verdict.get('passed', '-')} missing={row['missing_terms'] or '-'}", flush=True)
    if stopped:
        print("STOP: the pinned model was unavailable twice in a row (quota or outage)", flush=True)

    summary = summarize(rows)
    config = {"model": args.model, "prompt": args.prompt, "judge_model": None if args.skip_judge else args.judge_model,
              "split": args.split, "gold": str(args.gold.relative_to(ROOT)), "limit": args.limit,
              "timeouts": {k: os.environ.get(k) for k in ("LLM_ATTEMPT_TIMEOUT_SECONDS", "KB_GENERATION_BUDGET_SECONDS",
                                                         "RAG_REQUEST_TIMEOUT_SECONDS")},
              "started": datetime.now().isoformat(timespec="seconds")}
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stem = args.output or f"answers_{args.model}_{args.prompt}_{datetime.now():%Y%m%d_%H%M}"
    (OUT_DIR / f"{stem}.json").write_text(json.dumps({"config": config, "summary": summary, "rows": rows},
                                                     ensure_ascii=False, indent=2), encoding="utf-8")
    with (OUT_DIR / f"{stem}.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["id", "คำถาม", "ผล", "ผ่าน", "ถูก", "ครบ", "อันตราย", "รูปแบบ", "วินาที",
                         "คำที่ขาด", "เหตุผลผู้ตรวจ", "คำตอบบอต", "คำตอบอ้างอิง", "คนตรวจเห็นด้วย (ใช่/ไม่)"])
        for row in rows:
            verdict = row.get("judge", {})
            writer.writerow([row["id"], row["query"], row["outcome"], verdict.get("passed", ""), verdict.get("correct", ""),
                             verdict.get("complete", ""), verdict.get("harmful", ""), verdict.get("style_ok", ""),
                             row.get("seconds", ""), " | ".join(row.get("missing_terms", [])),
                             verdict.get("critique", row.get("judge_error", "")), row.get("answer", ""), row["expected"], ""])
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"report: {OUT_DIR / (stem + '.json')}\nreview sheet: {OUT_DIR / (stem + '.csv')}")
    return 1 if stopped else 0


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model", required=True, help="the one answer model (fallbacks are disabled)")
    parser.add_argument("--prompt", choices=["full", "concise"], default="full")
    parser.add_argument("--judge-model", default="gpt-5.6-terra", help="a different KKU model that grades answers")
    parser.add_argument("--skip-judge", action="store_true", help="deterministic checks only")
    parser.add_argument("--split", choices=["dev", "holdout", "all"], default="dev")
    parser.add_argument("--no-answer-only", action="store_true", help="leave out the answer-only cases (a01..)")
    parser.add_argument("--limit", type=int, help="first N cases only")
    parser.add_argument("--ids", help="comma-separated case ids, e.g. the screening subset (holdout ids are refused "
                                      "unless --split holdout)")
    parser.add_argument("--gold", type=Path, default=GOLD)
    parser.add_argument("--attempt-timeout", type=float)
    parser.add_argument("--kb-budget", type=float)
    parser.add_argument("--request-timeout", type=float)
    parser.add_argument("--output", help="file stem under cache/eval/")
    args = parser.parse_args()
    if not args.skip_judge and args.judge_model == args.model:
        parser.error("use a judge model different from the answer model")
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
