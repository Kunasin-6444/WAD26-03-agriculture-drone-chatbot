from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Literal

from openai import OpenAI

from app.rag.crag_grader import grade_retrieval, is_caat_air_law_or_airspace_topic
from app.rag.rag_service import generate_grounded_answer, retrieve_context
from app.rag.web_fallback import (
    generate_web_grounded_answer,
    search_web_fallback,
)

logger = logging.getLogger(__name__)

SourceType = Literal["knowledge_base", "web_fallback", "caat_portal", "abstain"]


@dataclass
class CragResponse:
    answer: str
    source_type: SourceType
    grade: str
    grade_reason: str


def run_crag_pipeline(
    query: str,
    n_results: int = 15,
    client: OpenAI | None = None,
) -> CragResponse:
    """
    Execute the CRAG (Corrective RAG) pipeline:
    1. Check if query is about CAAT Air Law / Air Space (Rule R1: exclude local PDF, use CAAT portal).
    2. Retrieve top-K chunks from Chroma.
    3. Grade the retrieved context for relevance and sufficiency.
    4. If sufficient (CORRECT): generate grounded answer from local knowledge base.
    5. If insufficient / CAAT topic: fallback to web search (Tavily & official sources).
    6. If neither provides reliable evidence: abstain clearly (Rule R6).
    """
    # ── TIMING: pipeline start ────────────────────────────────────────────────
    _t_pipeline_start = time.perf_counter()
    _timings: dict[str, float] = {}

    clean_query = query.strip()
    if not clean_query:
        return CragResponse(
            answer="กรุณาระบุคำถามที่ต้องการสอบถามเกี่ยวกับโดรนการเกษตรครับ",
            source_type="abstain",
            grade="INCORRECT",
            grade_reason="Empty query",
        )

    # ── STEP 1: CAAT keyword check (fast, in-process) ────────────────────────
    t0 = time.perf_counter()
    is_caat = is_caat_air_law_or_airspace_topic(clean_query)
    _timings["1. CAAT keyword check"] = time.perf_counter() - t0

    # 1. If CAAT Air Law / Air Space topic, route directly according to Rule R1
    if is_caat:
        logger.info(f"Query '{clean_query}' classified as CAAT Air Law/Air Space topic. Routing to CAAT portal.")

        t0 = time.perf_counter()
        web_results = search_web_fallback(
            query=clean_query,
            is_caat_topic=True,
        )
        _timings["2. Tavily search (CAAT route)"] = time.perf_counter() - t0

        t0 = time.perf_counter()
        answer = generate_web_grounded_answer(
            query=clean_query,
            web_results=web_results,
            is_caat_topic=True,
            client=client,
        )
        _timings["3. LLM answer gen (CAAT route)"] = time.perf_counter() - t0

        _print_crag_timing(clean_query, "caat_portal", _timings, _t_pipeline_start)
        return CragResponse(
            answer=answer,
            source_type="caat_portal",
            grade="INCORRECT",  # Local PDF was bypassed as required by R1
            grade_reason="Rule R1: Air Law and Air Space topics are routed to CAAT UAS Portal",
        )

    # ── STEP 2: Local Knowledge Base Retrieval ────────────────────────────────
    t0 = time.perf_counter()
    context = retrieve_context(clean_query, n_results=n_results)
    _timings["2. Vector DB retrieval"] = time.perf_counter() - t0

    # ── STEP 3: CRAG Grading & Semantic Intent Classification ─────────────────
    # Use compact context (top chunks, max 2,500 chars) for grader to minimize prompt processing latency
    grader_context = context[:2500] if len(context) > 2500 else context
    t0 = time.perf_counter()
    grade_result = grade_retrieval(clean_query, grader_context, client=client, model="gemini-3.5-flash-lite")
    _timings["3. Grader LLM call"] = time.perf_counter() - t0
    logger.info(f"CRAG Grade for '{clean_query}': {grade_result.grade} (Reason: {grade_result.reason})")

    # If query was semantically classified as CAAT Air Law/Regulation topic (Rule R1)
    if grade_result.is_caat_topic:
        logger.info(f"Query '{clean_query}' semantically classified as CAAT topic. Routing to CAAT portal.")

        t0 = time.perf_counter()
        web_results = search_web_fallback(
            query=clean_query,
            is_caat_topic=True,
        )
        _timings["4. Tavily search (semantic CAAT)"] = time.perf_counter() - t0

        t0 = time.perf_counter()
        answer = generate_web_grounded_answer(
            query=clean_query,
            web_results=web_results,
            is_caat_topic=True,
            client=client,
        )
        _timings["5. LLM answer gen (semantic CAAT)"] = time.perf_counter() - t0

        _print_crag_timing(clean_query, "caat_portal", _timings, _t_pipeline_start)
        return CragResponse(
            answer=answer,
            source_type="caat_portal",
            grade="INCORRECT",
            grade_reason=grade_result.reason or "Rule R1: Semantically classified as CAAT regulation topic",
        )

    # ── STEP 4: Knowledge Base is sufficient ─────────────────────────────────
    if grade_result.is_relevant:
        t0 = time.perf_counter()
        kb_answer = generate_grounded_answer(clean_query, context, client=client)
        _timings["4. LLM answer gen (KB)"] = time.perf_counter() - t0

        # Verify the LLM didn't return an abstain string
        if "ไม่พบข้อมูลดังกล่าวในเอกสารฐานความรู้" not in kb_answer:
            _print_crag_timing(clean_query, "knowledge_base", _timings, _t_pipeline_start)
            return CragResponse(
                answer=kb_answer,
                source_type="knowledge_base",
                grade=grade_result.grade,
                grade_reason=grade_result.reason,
            )

    # ── STEP 5: Web Fallback via Tavily ──────────────────────────────────────
    logger.info(f"KB evidence insufficient. Initiating Web Fallback for: '{clean_query}'")

    t0 = time.perf_counter()
    web_results = search_web_fallback(
        query=clean_query,
        is_caat_topic=False,
    )
    _timings["4. Tavily search (web fallback)"] = time.perf_counter() - t0

    if web_results:
        t0 = time.perf_counter()
        web_answer = generate_web_grounded_answer(
            query=clean_query,
            web_results=web_results,
            is_caat_topic=False,
            client=client,
        )
        _timings["5. LLM answer gen (web)"] = time.perf_counter() - t0

        if "ไม่พบข้อมูลดังกล่าวในเอกสารฐานความรู้และไม่พบข้อมูลที่น่าเชื่อถือ" not in web_answer:
            _print_crag_timing(clean_query, "web_fallback", _timings, _t_pipeline_start)
            return CragResponse(
                answer=web_answer,
                source_type="web_fallback",
                grade=grade_result.grade,
                grade_reason=grade_result.reason,
            )

    # ── STEP 6: Abstain Path (Rule R6: do not guess or hallucinate) ──────────
    abstain_message = (
        "ไม่พบข้อมูลดังกล่าวในเอกสารฐานความรู้และไม่พบข้อมูลที่น่าเชื่อถือจากแหล่งข้อมูลทางการ "
        "(ระบบไม่สามารถยืนยันความถูกต้องของข้อมูลได้ จึงขออภัยที่ไม่สามารถตอบคำถามนี้ได้ครับ)"
    )
    _print_crag_timing(clean_query, "abstain", _timings, _t_pipeline_start)
    return CragResponse(
        answer=abstain_message,
        source_type="abstain",
        grade=grade_result.grade,
        grade_reason=grade_result.reason,
    )


def _print_crag_timing(
    query: str,
    source_type: str,
    timings: dict[str, float],
    pipeline_start: float,
) -> None:
    """Print a formatted timing breakdown for the CRAG pipeline to stdout."""
    t_total = time.perf_counter() - pipeline_start
    rows = "\n".join(
        f"  {label:<40}: {ms * 1000:7.1f} ms"
        for label, ms in timings.items()
    )
    print(
        "\n"
        "┌─────────────────────────────────────────────────────────┐\n"
        f"│ [CRAG] source={source_type:<10}  query={query[:35]!r:<37}│\n"
        "├─────────────────────────────────────────────────────────┤\n"
        f"{rows}\n"
        "├─────────────────────────────────────────────────────────┤\n"
        f"  {'CRAG pipeline total':<40}: {t_total * 1000:7.1f} ms\n"
        "└─────────────────────────────────────────────────────────┘\n",
        flush=True,
    )

