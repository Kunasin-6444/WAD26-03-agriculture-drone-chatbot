from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from typing import Literal

from openai import OpenAI

from app.rag.crag_grader import is_caat_air_law_or_airspace_topic
from app.rag.evidence import Evidence, GroundedResult, document_evidence, pack_evidence, render_grounded_answer
from app.rag.intent_router import route_intent
from app.rag.query_normalizer import normalize_query
from app.rag.rag_service import evaluate_evidence, retrieve_context
from app.rag.web_fallback import search_web_fallback, web_evidence
from app.rag.source_policy import CAAT_PORTAL_INFOGRAPHIC_URL

logger = logging.getLogger(__name__)
SourceType = Literal["knowledge_base", "web_fallback", "caat_portal", "bot_usage", "hybrid", "abstain"]
# KB generation has a fallback (web search); cap it to one attempt within a short
# sub-deadline so a slow/overloaded model can't starve web search + final generation
# of the shared request budget (observed: two 8s attempts consumed 12s+ of a 22s budget).
KB_GENERATION_BUDGET_SECONDS = 8.0
DEGRADED_MESSAGE = "ขณะนี้ระบบกำลังปรับปรุงชั่วคราว ไม่สามารถตอบคำถามได้ในขณะนี้ กรุณาลองใหม่อีกครั้งในภายหลังครับ"


@dataclass
class CragResponse:
    answer: str
    source_type: SourceType
    grade: str
    grade_reason: str
    timings: dict[str, float] = field(default_factory=dict)
    evidence_trace: list[dict] = field(default_factory=list)


def run_crag_pipeline(query: str, n_results: int = 8, client: OpenAI | None = None) -> CragResponse:
    started = time.monotonic()
    deadline = started + float(os.getenv("RAG_REQUEST_TIMEOUT_SECONDS", "22"))
    timings: dict[str, float] = {}
    llm_down = False

    def respond(result: GroundedResult, evidence: list[Evidence], caat: bool = False) -> CragResponse:
        used = {s for claim in result.claims for s in claim.source_ids}
        actual = [e for e in evidence if e.id in used]
        source: SourceType = "abstain"
        if actual:
            kinds = {bool(e.url) for e in actual}
            source = "caat_portal" if caat else "hybrid" if len(kinds) > 1 else "web_fallback" if True in kinds else "knowledge_base"
        answer = render_grounded_answer(result, evidence)
        if not actual and (result.llm_unavailable or llm_down):
            # Distinct from a genuine "no evidence" abstain: the model pool itself failed.
            answer = DEGRADED_MESSAGE
        elif caat and not actual:
            answer = f"ยังไม่พบหลักฐานเพียงพอที่จะยืนยันข้อกำหนดนี้ครับ ตรวจสอบข้อมูลทางการได้ที่ {CAAT_PORTAL_INFOGRAPHIC_URL}"
        timings["total_ms"] = round((time.monotonic() - started) * 1000, 2)
        grade = {"sufficient": "CORRECT", "partial": "AMBIGUOUS", "insufficient": "INCORRECT"}[result.status]
        trace = [{"text": claim.text, "evidence": [
            {"source_id": source_id, "quote": quote, "citation": next(e.citation for e in actual if e.id == source_id)}
            for source_id, quote in claim.quotes]} for claim in result.claims]
        return CragResponse(answer, source, grade, result.reason, dict(timings), trace)

    clean_query = query.strip()
    # Typos / wrong-layout text are repaired once and used for retrieval, the LLM and web search,
    # so the model never sees "2 gfnvo" while retrieval saw "2 เดือน".
    search_query = normalize_query(clean_query)
    if not clean_query:
        return CragResponse("กรุณาระบุคำถามเกี่ยวกับโดรนการเกษตรครับ", "abstain", "INCORRECT", "Empty query")
    intent = route_intent(clean_query)
    if intent.intent == "bot_usage":
        return CragResponse(intent.handled_response or "", "bot_usage", "CORRECT", "Bot usage")

    caat = is_caat_air_law_or_airspace_topic(clean_query)
    kb: list[Evidence] = []
    initial = GroundedResult(reason="No document evidence")
    if not caat:
        before = time.monotonic()
        try:
            kb = pack_evidence(document_evidence(retrieve_context(search_query, n_results=n_results)))
        except Exception as exc:
            logger.warning("Document retrieval unavailable (%s)", type(exc).__name__)
            initial.reason = "Document retrieval unavailable"
        timings["retrieval_ms"] = round((time.monotonic() - before) * 1000, 2)
        if kb:
            before = time.monotonic()
            kb_deadline = min(deadline, before + KB_GENERATION_BUDGET_SECONDS)
            initial = evaluate_evidence(search_query, kb, client, kb_deadline, max_attempts=1)
            timings["kb_generation_ms"] = round((time.monotonic() - before) * 1000, 2)
            llm_down = llm_down or initial.llm_unavailable
            caat = initial.is_caat_topic
            # A PDF cannot establish current prices/news, even if the model says sufficient.
            if initial.status == "sufficient" and any(term in search_query for term in ["วันนี้", "ล่าสุด", "ปัจจุบัน"]):
                initial = GroundedResult(missing_aspects=[search_query], reason="Current information requires web evidence", is_caat_topic=caat)
            if not caat and initial.status == "sufficient":
                return respond(initial, kb)
    if caat:
        kb = []
        initial = GroundedResult(reason="CAAT designated source required")

    before = time.monotonic()
    web_query = search_query
    if initial.missing_aspects:
        web_query += " " + " ".join(initial.missing_aspects)
    try:
        results = search_web_fallback(web_query, is_caat_topic=caat, deadline=deadline)
    except Exception as exc:
        logger.warning("Web search unavailable (%s)", type(exc).__name__)
        results = []
    timings["web_search_ms"] = round((time.monotonic() - before) * 1000, 2)
    web = web_evidence(results)
    if not web:
        return respond(initial if initial.status == "partial" else GroundedResult(reason="No verified web evidence"), kb, caat)

    # Preserve useful KB sources; irrelevant documents must not contaminate web answers.
    if initial.status == "partial":
        used = {s for claim in initial.claims for s in claim.source_ids}
        kb = [e for e in kb if e.id in used]
    else:
        kb = []
    combined = pack_evidence(kb + web)
    before = time.monotonic()
    final = evaluate_evidence(search_query, combined, client, deadline)
    timings["final_generation_ms"] = round((time.monotonic() - before) * 1000, 2)
    llm_down = llm_down or final.llm_unavailable
    # Failed final generation must not erase validated partial document information.
    if not final.claims and initial.status == "partial":
        return respond(initial, kb, caat)
    return respond(final, combined, caat)
