from __future__ import annotations

import concurrent.futures
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
    n_results: int = 12,
    client: OpenAI | None = None,
) -> CragResponse:
    """
    Execute the CRAG (Corrective RAG) pipeline with Speculative Parallel Execution:
    1. Check if query is about CAAT Air Law / Air Space (Rule R1: exclude local PDF, use CAAT portal).
    2. Retrieve top-K chunks from Chroma (pruned to 8 chunks for fast prefill).
    3. Concurrently run CRAG Grader (evaluation gatekeeper) and Grounded Answer Generator.
    4. If Grader confirms relevance (CORRECT): return grounded answer immediately.
    5. If insufficient / CAAT topic: discard speculative answer, fallback to web search.
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

    # If context is completely empty, skip local LLM calls and proceed to Web Fallback
    if not context or not context.strip():
        logger.info(f"Retrieved context is empty for '{clean_query}'. Initiating Web Fallback.")
        grade_result_empty = "INCORRECT"
        grade_reason_empty = "Retrieved context is empty."
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
                    grade=grade_result_empty,
                    grade_reason=grade_reason_empty,
                )
        return CragResponse(
            answer=(
                "ไม่พบข้อมูลดังกล่าวในเอกสารฐานความรู้และไม่พบข้อมูลที่น่าเชื่อถือจากแหล่งข้อมูลทางการ "
                "(ระบบไม่สามารถยืนยันความถูกต้องของข้อมูลได้ จึงขออภัยที่ไม่สามารถตอบคำถามนี้ได้ครับ)"
            ),
            source_type="abstain",
            grade=grade_result_empty,
            grade_reason=grade_reason_empty,
        )

    # 3. Speculative Parallel Execution:
    # Run CRAG Grader (gatekeeper) and Grounded Generator concurrently for ultra-fast KB response.
    # The Grader's verdict determines whether the speculative KB answer is accepted or discarded.
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        future_grade = executor.submit(grade_retrieval, clean_query, context, client=client)
        future_gen = executor.submit(generate_grounded_answer, clean_query, context, client=client)

        grade_result = future_grade.result()

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

    # 4. If Knowledge Base contains sufficient evidence (CORRECT)
    if grade_result.is_relevant:
        kb_answer = future_gen.result()
        # If the speculative answer was overly strict or missed colloquial synonyms, retry once with grader's hint
        if "ไม่พบข้อมูลดังกล่าวในเอกสารฐานความรู้" in kb_answer and grade_result.reason:
            logger.info(f"Retrying grounded generation with grader hint: {grade_result.reason}")
            kb_answer = generate_grounded_answer(
                f"{clean_query}\n(คำชี้แนะหลักฐานจากเอกสาร: {grade_result.reason})",
                context,
                client=client,
            )

        # Verify the LLM didn't return an abstain string
        if "ไม่พบข้อมูลดังกล่าวในเอกสารฐานความรู้" not in kb_answer:
            return CragResponse(
                answer=kb_answer,
                source_type="knowledge_base",
                grade=grade_result.grade,
                grade_reason=grade_result.reason,
            )

    # 4.1 Resilient CRAG Handling for AMBIGUOUS:
    if grade_result.grade == "AMBIGUOUS":
        kb_answer = future_gen.result()
        if "ไม่พบข้อมูลดังกล่าวในเอกสารฐานความรู้" not in kb_answer and ("แหล่งอ้างอิง:" in kb_answer or "หน้า" in kb_answer):
            logger.info(f"Grader reported AMBIGUOUS, but speculative KB generator successfully grounded answer with citation for '{clean_query}'. Accepting KB answer.")
            return CragResponse(
                answer=kb_answer,
                source_type="knowledge_base",
                grade=grade_result.grade,
                grade_reason=grade_result.reason or "Speculative grounded answer verified with document citation",
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
