from __future__ import annotations

import logging
import os
import time
from typing import Literal

from openai import OpenAI

from app.rag.candidate.context_filter import scope_and_filter_context
from app.rag.candidate.models import CandidateResponse, SourceType, VerificationResult
from app.rag.candidate.prompt import build_candidate_messages
from app.rag.candidate.table_continuation import assemble_candidate_table_evidence
from app.rag.candidate.verifier import verify_and_render_candidate
from app.rag.crag_grader import is_caat_air_law_or_airspace_topic
from app.rag.evidence import ABSTAIN_MESSAGE, Evidence, _is_aviation_regulation, is_drone_rule_topic
from app.rag.intent_router import route_intent
from app.rag.query_normalizer import normalize_query
from app.rag.rag_service import call_llm, llm_pool_error, retrieve_evidence
from app.rag.source_policy import CAAT_PORTAL_INFOGRAPHIC_URL
from app.rag.web_fallback import search_web_fallback, web_evidence
from app.service_status import ERROR_MESSAGES, classify_service_error, common_error

logger = logging.getLogger(__name__)

DEGRADED_MESSAGE = ERROR_MESSAGES.get("provider_unavailable", "ขณะนี้ระบบกำลังปรับปรุงชั่วคราว กรุณาลองใหม่อีกครั้ง")
CURRENT_INFO_TERMS = ("วันนี้", "ล่าสุด", "ปัจจุบัน", "ตอนนี้")


def _is_caat_topic(query: str) -> bool:
    return is_caat_air_law_or_airspace_topic(query) or _is_aviation_regulation(query) or is_drone_rule_topic(query)


def run_candidate_pipeline(
    query: str,
    n_results: int = 8,
    client: OpenAI | None = None,
    mode: Literal["auto", "kb_only", "web_only", "mixed"] = "auto",
    lookup_fn: Callable[[str, str | None], list[tuple[Evidence, dict]]] | None = None,
    table_continuation_enabled: bool = True,
) -> CandidateResponse:
    """Alternative candidate RAG pipeline with clean scoping and honest quality reporting.

    Pipeline flow:
    query -> intent routing -> retrieve evidence -> context scoping/filtering ->
    condition-preserving prompt -> LLM generation -> non-destructive verification & rendering.

    Does not falsely claim CORRECT solely on surface syntax.
    """
    started = time.monotonic()
    deadline = started + float(os.getenv("RAG_REQUEST_TIMEOUT_SECONDS", "22"))
    timings: dict[str, float] = {}
    diagnostics: list[dict] = []

    clean_query = (query or "").strip()
    if not clean_query:
        timings["total_ms"] = round((time.monotonic() - started) * 1000, 2)
        return CandidateResponse(
            answer="กรุณาระบุคำถามเกี่ยวกับโดรนการเกษตรครับ",
            source_type="abstain",
            grade="ABSTAIN",
            grade_reason="Empty query",
            timings=timings,
            error_code="empty_query",
            generation_succeeded=False,
            citation_checks_passed=True,
            semantic_quality="not_assessed",
        )

    # Bot usage intent check (offline fast path)
    intent = route_intent(clean_query)
    if intent.intent == "bot_usage":
        timings["total_ms"] = round((time.monotonic() - started) * 1000, 2)
        return CandidateResponse(
            answer=intent.handled_response or "",
            source_type="bot_usage",
            grade="CANDIDATE",
            grade_reason="Handled by bot_usage intent",
            timings=timings,
            generation_succeeded=True,
            citation_checks_passed=True,
            semantic_quality="not_assessed",
        )

    # Check provider pool availability
    pool_error = llm_pool_error()
    if pool_error:
        diagnostics.append({"stage": "llm_pool", "error_code": pool_error, "llm_unavailable": True})
        timings["total_ms"] = round((time.monotonic() - started) * 1000, 2)
        return CandidateResponse(
            answer=ERROR_MESSAGES.get(pool_error, DEGRADED_MESSAGE),
            source_type="abstain",
            grade="ERROR",
            grade_reason=f"LLM pool unavailable: {pool_error}",
            timings=timings,
            diagnostics=diagnostics,
            error_code=pool_error,
            generation_succeeded=False,
            citation_checks_passed=False,
            semantic_quality="not_assessed",
        )

    search_query = normalize_query(clean_query)
    caat_topic = _is_caat_topic(clean_query)
    current_topic = any(term in clean_query for term in CURRENT_INFO_TERMS)

    # Determine retrieval targets
    retrieve_kb = mode in ("auto", "kb_only", "mixed")
    retrieve_web = mode == "web_only" or (mode == "auto" and (caat_topic or current_topic))

    raw_kb_evidence: list[Evidence] = []
    raw_web_evidence: list[Evidence] = []
    service_failures: list[str] = []

    # 1. KB Retrieval
    if retrieve_kb:
        t0 = time.monotonic()
        try:
            raw_kb_evidence = retrieve_evidence(search_query, n_results=n_results, deadline=deadline)
            raw_kb_evidence, table_diag = assemble_candidate_table_evidence(
                raw_kb_evidence,
                clean_query,
                lookup_fn=lookup_fn,
                enabled=table_continuation_enabled,
            )
            if table_diag.get("table_continuation_applied"):
                diagnostics.append(table_diag)
        except Exception as exc:
            err = classify_service_error(exc)
            logger.warning("Candidate KB retrieval failed (%s: %s)", type(exc).__name__, exc)
            service_failures.append(err)
            diagnostics.append({"stage": "kb_retrieval", "error_code": err})
        timings["kb_retrieval_ms"] = round((time.monotonic() - t0) * 1000, 2)

    # 2. Web Retrieval (if initial mode calls for it)
    if retrieve_web:
        t0 = time.monotonic()
        try:
            web_results = search_web_fallback(search_query, is_caat_topic=caat_topic, deadline=deadline, diagnostics=diagnostics)
            raw_web_evidence = web_evidence(web_results)
        except Exception as exc:
            err = classify_service_error(exc)
            logger.warning("Candidate web retrieval failed (%s: %s)", type(exc).__name__, exc)
            service_failures.append(err)
            diagnostics.append({"stage": "web_retrieval", "error_code": err})
        timings["web_retrieval_ms"] = round((time.monotonic() - t0) * 1000, 2)

    combined_initial = raw_kb_evidence + raw_web_evidence

    # If no evidence found in primary paths
    if not combined_initial:
        if service_failures:
            err = common_error(service_failures)
            timings["total_ms"] = round((time.monotonic() - started) * 1000, 2)
            return CandidateResponse(
                answer=ERROR_MESSAGES.get(err, DEGRADED_MESSAGE),
                source_type="abstain",
                grade="ERROR",
                grade_reason=f"Retrieval services failed: {err}",
                timings=timings,
                diagnostics=diagnostics,
                error_code=err,
                generation_succeeded=False,
                citation_checks_passed=False,
                semantic_quality="not_assessed",
            )
        # In auto or mixed mode, try fallback web search if KB had nothing
        if mode in ("auto", "mixed") and not retrieve_web:
            t0 = time.monotonic()
            try:
                web_results = search_web_fallback(search_query, is_caat_topic=caat_topic, deadline=deadline, diagnostics=diagnostics)
                raw_web_evidence = web_evidence(web_results)
                combined_initial = raw_web_evidence
            except Exception as exc:
                diagnostics.append({"stage": "fallback_web", "error_code": classify_service_error(exc)})
            timings["fallback_web_ms"] = round((time.monotonic() - t0) * 1000, 2)

    if not combined_initial:
        timings["total_ms"] = round((time.monotonic() - started) * 1000, 2)
        abstain_msg = (
            f"ยังไม่พบหลักฐานเพียงพอที่จะยืนยันข้อกำหนดนี้ครับ ตรวจสอบข้อมูลทางการได้ที่ {CAAT_PORTAL_INFOGRAPHIC_URL}"
            if caat_topic else ABSTAIN_MESSAGE
        )
        return CandidateResponse(
            answer=abstain_msg,
            source_type="abstain",
            grade="ABSTAIN",
            grade_reason="No evidence found",
            timings=timings,
            diagnostics=diagnostics,
            generation_succeeded=False,
            citation_checks_passed=True,
            semantic_quality="not_assessed",
        )

    # 3. Context Scoping & Selection
    t0 = time.monotonic()
    # Preserve assembled multi-page table evidence by sizing selection budget to table chunks (up to 12)
    table_diag_applied = any(
        d.get("stage") == "table_continuation" and d.get("table_continuation_applied")
        for d in diagnostics
    )
    selection_budget = 12 if table_diag_applied else 8
    scoped_evidence, pre_sel, post_sel, drop_notes = scope_and_filter_context(
        clean_query, combined_initial, max_chunks=selection_budget
    )
    timings["context_scoping_ms"] = round((time.monotonic() - t0) * 1000, 2)
    diagnostics.append({
        "stage": "context_scoping",
        "pre_count": len(pre_sel),
        "post_count": len(post_sel),
        "dropped_notes": drop_notes,
    })

    # Reconcile table continuation coverage against what actually survived selection
    surviving_chunk_keys = {(ev.source_file, str(ev.page_number), ev.content.strip()) for ev in scoped_evidence}
    surviving_pages_by_doc: dict[str, set[str]] = {}
    for ev in scoped_evidence:
        if ev.source_file and ev.page_number:
            surviving_pages_by_doc.setdefault(ev.source_file, set()).add(str(ev.page_number))

    for diag_item in diagnostics:
        if diag_item.get("stage") == "table_continuation":
            for t in diag_item.get("tables", []):
                s_file = t.get("source_file")
                surviving_pages = surviving_pages_by_doc.get(s_file, set())
                req_chunks = t.get("included_chunks", [])
                lost_chunks = [k for k in req_chunks if k not in surviving_chunk_keys]
                if lost_chunks:
                    t["coverage"] = "incomplete"
                    t["post_selection_dropped_chunks"] = len(lost_chunks)
                    lost_pages = {k[1] for k in lost_chunks if k[1]}
                    completely_lost_pages = {p for p in lost_pages if p not in surviving_pages}
                    t["included_pages"] = [p for p in t.get("included_pages", []) if str(p) in surviving_pages]
                    all_missing = set(t.get("missing_pages", [])) | completely_lost_pages
                    t["missing_pages"] = sorted(list(all_missing), key=lambda p: int(p) if str(p).isdigit() else 9999)
                    if completely_lost_pages:
                        t["post_selection_dropped_pages"] = sorted(list(completely_lost_pages), key=lambda p: int(p) if str(p).isdigit() else 9999)

    table_coverages = [
        t.get("coverage")
        for d in diagnostics
        if d.get("stage") == "table_continuation"
        for t in d.get("tables", [])
    ]
    table_coverage_status: str | None = None
    if "incomplete" in table_coverages:
        table_coverage_status = "incomplete"
    elif "unknown" in table_coverages:
        table_coverage_status = "unknown"
    elif "complete" in table_coverages:
        table_coverage_status = "complete"

    is_table_incomplete = table_coverage_status in ("incomplete", "unknown")

    # 4. LLM Generation
    t0 = time.monotonic()
    messages = build_candidate_messages(
        clean_query,
        scoped_evidence,
        table_incomplete=is_table_incomplete,
        table_coverage=table_coverage_status,
    )
    raw_answer = ""
    gen_succeeded = False
    try:
        raw_answer = call_llm(messages, client=client, deadline=deadline, max_attempts=2, structured=False)
        gen_succeeded = True
    except Exception as exc:
        code = getattr(exc, "error_code", "") or classify_service_error(exc)
        diagnostics.append({"stage": "llm_generation", "error_code": code})
        timings["generation_ms"] = round((time.monotonic() - t0) * 1000, 2)
        timings["total_ms"] = round((time.monotonic() - started) * 1000, 2)
        return CandidateResponse(
            answer=ERROR_MESSAGES.get(code, DEGRADED_MESSAGE),
            source_type="abstain",
            grade="ERROR",
            grade_reason=f"LLM generation failed: {code}",
            timings=timings,
            diagnostics=diagnostics,
            error_code=code,
            raw_answer=raw_answer,
            generation_succeeded=False,
            citation_checks_passed=False,
            semantic_quality="not_assessed",
            pre_selection_evidence=pre_sel,
            post_selection_evidence=post_sel,
            dropped_reasons=drop_notes,
        )
    timings["generation_ms"] = round((time.monotonic() - t0) * 1000, 2)

    # 5. Non-destructive Verification & Rendering
    verification: VerificationResult = verify_and_render_candidate(raw_answer, scoped_evidence)

    pipeline_error_code = ""

    # 6. Mixed-mode Gap Filling (if partial or not found, and mode permits web)
    if mode in ("auto", "mixed") and not retrieve_web and (verification.is_not_found or verification.missing_aspect):
        missing_query = verification.missing_aspect or clean_query
        t0 = time.monotonic()
        web_gap_ev: list[Evidence] = []
        try:
            gap_results = search_web_fallback(f"{search_query} {missing_query[:200]}", is_caat_topic=caat_topic, deadline=deadline, diagnostics=diagnostics)
            web_gap_ev = web_evidence(gap_results)
        except Exception as exc:
            err = getattr(exc, "error_code", "") or classify_service_error(exc)
            pipeline_error_code = err
            diagnostics.append({"stage": "web_gap_search", "error_code": err})
        timings["web_gap_search_ms"] = round((time.monotonic() - t0) * 1000, 2)

        if web_gap_ev:
            if verification.is_not_found:
                # KB was empty, replace with web evidence
                scoped_web, _, post_web, _ = scope_and_filter_context(missing_query, web_gap_ev, max_chunks=4)
                if scoped_web:
                    scoped_evidence = scoped_web
                    post_sel = post_web
                    web_messages = build_candidate_messages(clean_query, scoped_web)
                    try:
                        raw_answer = call_llm(web_messages, client=client, deadline=deadline, max_attempts=2, structured=False)
                        verification = verify_and_render_candidate(raw_answer, scoped_web)
                    except Exception as exc:
                        err = getattr(exc, "error_code", "") or classify_service_error(exc)
                        pipeline_error_code = err
                        diagnostics.append({"stage": "web_gap_generation", "error_code": err})
            else:
                # KB facts exist! Supplement missing aspect without losing verified KB facts
                scoped_web, _, post_web, _ = scope_and_filter_context(missing_query, web_gap_ev, max_chunks=3)
                if scoped_web:
                    gap_messages = build_candidate_messages(f"ค้นหาเพิ่มเติมเฉพาะประเด็น: {missing_query}", scoped_web)
                    try:
                        gap_raw = call_llm(gap_messages, client=client, deadline=deadline, max_attempts=2, structured=False)
                        gap_verif = verify_and_render_candidate(gap_raw, scoped_web)
                        if not gap_verif.is_not_found and gap_verif.rendered_text:
                            # Re-verify and render union of scoped_evidence + scoped_web
                            all_evidence = scoped_evidence + scoped_web
                            combined_raw = f"{raw_answer}\n{gap_raw}"
                            verification = verify_and_render_candidate(combined_raw, all_evidence)
                            scoped_evidence = all_evidence
                            post_sel.extend(post_web)
                    except Exception as exc:
                        err = getattr(exc, "error_code", "") or classify_service_error(exc)
                        pipeline_error_code = err
                        diagnostics.append({"stage": "web_gap_generation", "error_code": err})

    timings["total_ms"] = round((time.monotonic() - started) * 1000, 2)

    # If answer is empty or completely unverified
    if verification.is_not_found or not verification.rendered_text:
        abstain_msg = (
            f"ยังไม่พบหลักฐานเพียงพอที่จะยืนยันข้อกำหนดนี้ครับ ตรวจสอบข้อมูลทางการได้ที่ {CAAT_PORTAL_INFOGRAPHIC_URL}"
            if caat_topic else ABSTAIN_MESSAGE
        )
        return CandidateResponse(
            answer=abstain_msg,
            source_type="abstain",
            grade="ABSTAIN",
            grade_reason="No verified evidence lines survived" if verification.dropped_reasons else "Not found in sources",
            timings=timings,
            diagnostics=diagnostics,
            error_code=pipeline_error_code,
            raw_answer=raw_answer,
            generation_succeeded=gen_succeeded,
            citation_checks_passed=verification.passed_citations,
            semantic_quality="not_assessed",
            pre_selection_evidence=pre_sel,
            post_selection_evidence=post_sel,
            dropped_reasons=verification.dropped_reasons + drop_notes,
            missing_aspect=verification.missing_aspect,
        )

    # Classify final source type
    by_id = {e.id: e for e in scoped_evidence}
    used_items = [by_id[i] for i in verification.used_source_ids if i in by_id]
    has_web = any(bool(e.url) for e in used_items)
    has_kb = any(not bool(e.url) for e in used_items)

    source_type: SourceType = "knowledge_base"
    if has_web and has_kb:
        source_type = "hybrid"
    elif has_web:
        source_type = "caat_portal" if caat_topic else "web_fallback"
    else:
        source_type = "knowledge_base"

    all_dropped = list(dict.fromkeys(drop_notes + verification.dropped_reasons))
    reason = "; ".join(verification.dropped_reasons) if verification.dropped_reasons else "Candidate answer verified"

    return CandidateResponse(
        answer=verification.rendered_text,
        source_type=source_type,
        grade="CANDIDATE",
        grade_reason=reason[:300],
        timings=timings,
        evidence_trace=verification.evidence_trace,
        diagnostics=diagnostics,
        error_code=pipeline_error_code,
        raw_answer=raw_answer,
        generation_succeeded=gen_succeeded,
        citation_checks_passed=verification.passed_citations,
        semantic_quality="not_assessed",
        pre_selection_evidence=pre_sel,
        post_selection_evidence=post_sel,
        dropped_reasons=all_dropped,
        missing_aspect=verification.missing_aspect,
    )
