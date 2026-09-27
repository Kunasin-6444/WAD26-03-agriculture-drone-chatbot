from __future__ import annotations

import logging
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
    clean_query = query.strip()
    if not clean_query:
        return CragResponse(
            answer="กรุณาระบุคำถามที่ต้องการสอบถามเกี่ยวกับโดรนการเกษตรครับ",
            source_type="abstain",
            grade="INCORRECT",
            grade_reason="Empty query",
        )

    is_caat = is_caat_air_law_or_airspace_topic(clean_query)

    # 1. If CAAT Air Law / Air Space topic, route directly according to Rule R1
    if is_caat:
        logger.info(f"Query '{clean_query}' classified as CAAT Air Law/Air Space topic. Routing to CAAT portal.")
        web_results = search_web_fallback(
            query=clean_query,
            is_caat_topic=True,
        )
        answer = generate_web_grounded_answer(
            query=clean_query,
            web_results=web_results,
            is_caat_topic=True,
            client=client,
        )
        return CragResponse(
            answer=answer,
            source_type="caat_portal",
            grade="INCORRECT",  # Local PDF was bypassed as required by R1
            grade_reason="Rule R1: Air Law and Air Space topics are routed to CAAT UAS Portal",
        )

    # 2. Local Knowledge Base Retrieval
    context = retrieve_context(clean_query, n_results=n_results)

    # 3. CRAG Grading & Semantic Intent Classification
    # Use compact context (top chunks, max 2,500 chars) for grader to minimize prompt processing latency
    grader_context = context[:2500] if len(context) > 2500 else context
    grade_result = grade_retrieval(clean_query, grader_context, client=client)
    logger.info(f"CRAG Grade for '{clean_query}': {grade_result.grade} (Reason: {grade_result.reason})")

    # If query was semantically classified as CAAT Air Law/Regulation topic (Rule R1)
    if grade_result.is_caat_topic:
        logger.info(f"Query '{clean_query}' semantically classified as CAAT topic. Routing to CAAT portal.")
        web_results = search_web_fallback(
            query=clean_query,
            is_caat_topic=True,
        )
        answer = generate_web_grounded_answer(
            query=clean_query,
            web_results=web_results,
            is_caat_topic=True,
            client=client,
        )
        return CragResponse(
            answer=answer,
            source_type="caat_portal",
            grade="INCORRECT",
            grade_reason=grade_result.reason or "Rule R1: Semantically classified as CAAT regulation topic",
        )

    # 4. If Knowledge Base contains sufficient evidence
    if grade_result.is_relevant:
        kb_answer = generate_grounded_answer(clean_query, context, client=client)
        # Verify the LLM didn't return an abstain string
        if "ไม่พบข้อมูลดังกล่าวในเอกสารฐานความรู้" not in kb_answer:
            return CragResponse(
                answer=kb_answer,
                source_type="knowledge_base",
                grade=grade_result.grade,
                grade_reason=grade_result.reason,
            )

    # 5. Web Fallback via Tavily
    logger.info(f"KB evidence insufficient. Initiating Web Fallback for: '{clean_query}'")
    web_results = search_web_fallback(
        query=clean_query,
        is_caat_topic=False,
    )

    if web_results:
        web_answer = generate_web_grounded_answer(
            query=clean_query,
            web_results=web_results,
            is_caat_topic=False,
            client=client,
        )
        if "ไม่พบข้อมูลดังกล่าวในเอกสารฐานความรู้และไม่พบข้อมูลที่น่าเชื่อถือ" not in web_answer:
            return CragResponse(
                answer=web_answer,
                source_type="web_fallback",
                grade=grade_result.grade,
                grade_reason=grade_result.reason,
            )

    # 6. Abstain Path (Rule R6: do not guess or hallucinate)
    abstain_message = (
        "ไม่พบข้อมูลดังกล่าวในเอกสารฐานความรู้และไม่พบข้อมูลที่น่าเชื่อถือจากแหล่งข้อมูลทางการ "
        "(ระบบไม่สามารถยืนยันความถูกต้องของข้อมูลได้ จึงขออภัยที่ไม่สามารถตอบคำถามนี้ได้ครับ)"
    )
    return CragResponse(
        answer=abstain_message,
        source_type="abstain",
        grade=grade_result.grade,
        grade_reason=grade_result.reason,
    )
