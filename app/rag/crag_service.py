from __future__ import annotations

import logging
import os
import time
from itertools import zip_longest
from dataclasses import dataclass, field, replace
from typing import Literal

from openai import OpenAI

from app.rag.crag_grader import is_caat_air_law_or_airspace_topic
from app.rag.evidence import (REJECTED_CLAIMS_ASPECT, Evidence, GroundedResult, merge_verified_partial as preserve_partial_answer,
                              pack_evidence, render_grounded_answer)
from app.rag.intent_router import route_intent
from app.rag.page_reranker import split_query_aspects
from app.rag.query_normalizer import normalize_query
from app.rag import natural_answer
from app.rag.evidence import ABSTAIN_MESSAGE, _is_aviation_regulation, is_drone_rule_topic
from app.rag.rag_service import call_llm, evaluate_evidence, llm_pool_error, retrieve_evidence
from app.service_status import ERROR_MESSAGES, classify_service_error, common_error
from app.rag.web_fallback import search_web_fallback, web_evidence
from app.rag.source_policy import CAAT_PORTAL_INFOGRAPHIC_URL

logger = logging.getLogger(__name__)
SourceType = Literal["knowledge_base", "web_fallback", "caat_portal", "bot_usage", "hybrid", "abstain"]
# KB generation has a fallback (web search); cap it to one attempt within a short
# sub-deadline so a slow/overloaded model can't starve web search + final generation
# of the shared request budget (observed: two 8s attempts consumed 12s+ of a 22s budget).
KB_GENERATION_BUDGET_SECONDS = float(os.getenv("KB_GENERATION_BUDGET_SECONDS", "8"))
DEGRADED_MESSAGE = ERROR_MESSAGES["provider_unavailable"]


@dataclass
class CragResponse:
    answer: str
    source_type: SourceType
    grade: str
    grade_reason: str
    timings: dict[str, float] = field(default_factory=dict)
    evidence_trace: list[dict] = field(default_factory=list)
    diagnostics: list[dict] = field(default_factory=list)
    error_code: str = ""


CURRENT_INFO_TERMS = ("วันนี้", "ล่าสุด", "ปัจจุบัน", "ตอนนี้")


def answer_mode() -> str:
    """ANSWER_MODE=natural: plain answer + line checks; anything else: the JSON-claims (CRAG) path."""
    return (os.getenv("ANSWER_MODE") or "grounded").strip().lower()


def interleave_evidence(first: list[Evidence], second: list[Evidence]) -> list[Evidence]:
    """Alternate two document rankings, first-list pages first, each page once, renumbered D1..Dn."""
    merged, seen = [], set()
    for pair in zip_longest(first, second):
        for item in pair:
            key = (item.source_file, item.page_number) if item else None
            if item and key not in seen:
                seen.add(key)
                merged.append(item)
    limit = max(len(first), len(second))
    return [replace(item, id=f"D{index}") for index, item in enumerate(merged[:limit], 1)]


def run_natural_pipeline(query: str, n_results: int = 8, client: OpenAI | None = None,
                         previous_question: str | None = None) -> CragResponse:
    """Documents first; the web only for current/regulatory questions or when the documents have nothing.

    No self-graded sufficiency step: the 2026-10-20 screening found the model's own "partial" verdict
    sent 5 of 7 web detours down the wrong path. The web is searched up front when the question asks
    for current information or CAAT rules, or once afterwards when the model answers NOT_FOUND."""
    started = time.monotonic()
    deadline = started + float(os.getenv("RAG_REQUEST_TIMEOUT_SECONDS", "22"))
    timings: dict[str, float] = {}
    diagnostics: list[dict] = []
    clean_query = query.strip()
    question = normalize_query(clean_query)
    # A short follow-up ("สูงแค่ไหน") is searched and routed together with the user's previous full
    # question; the model sees both and decides whether it continues that topic (LINE test 2026-10-21).
    previous = (previous_question or "").strip()
    topic = f"{previous} {clean_query}" if previous else clean_query
    search_query = normalize_query(topic)
    if not clean_query:
        return CragResponse("กรุณาระบุคำถามเกี่ยวกับโดรนการเกษตรครับ", "abstain", "INCORRECT", "Empty query")
    intent = route_intent(clean_query)
    if intent.intent == "bot_usage":
        return CragResponse(intent.handled_response or "", "bot_usage", "CORRECT", "Bot usage")

    def failure(code: str, reason: str) -> CragResponse:
        timings["total_ms"] = round((time.monotonic() - started) * 1000, 2)
        return CragResponse(ERROR_MESSAGES.get(code, DEGRADED_MESSAGE), "abstain", "INCORRECT", reason,
                            dict(timings), [], list(diagnostics), code)

    pool_error = llm_pool_error()
    if pool_error:
        diagnostics.append({"stage": "llm_pool", "error_code": pool_error, "llm_unavailable": True})
        return failure(pool_error, "No callable LLM models in known cooldown state")

    # Same test the line checker uses, so a question about required drone insurance cover is
    # answered from official CAAT pages like other drone rules.
    caat = is_caat_air_law_or_airspace_topic(topic) or _is_aviation_regulation(topic)
    # Other questions on a subject CAAT rules govern ("อยากทราบประกันของโดรน", "จดทะเบียนโดรนยังไง") keep
    # the documents (they may hold costs or practice) and fetch CAAT up front (2026-10-20: abstained).
    caat_web = caat or is_drone_rule_topic(topic)
    parts = split_query_aspects(search_query) if caat else []
    technical = [part for part in parts if not is_caat_air_law_or_airspace_topic(part)]
    current = any(term in search_query for term in CURRENT_INFO_TERMS)
    failures: list[str] = []
    kb: list[Evidence] = []
    if not caat or technical:
        before = time.monotonic()
        try:
            kb = retrieve_evidence(" ".join(technical) if technical else search_query, n_results=n_results, deadline=deadline)
            if previous and not technical:
                # Searched with the earlier question alone, its words drown the short follow-up's
                # ("หลักการบิน", "สูง เร็ว"): pages for the follow-up itself come first.
                kb = interleave_evidence(retrieve_evidence(question, n_results=n_results, deadline=deadline), kb)
        except Exception as exc:
            logger.warning("Document retrieval unavailable (%s)", type(exc).__name__)
            failures.append(classify_service_error(exc))
            diagnostics.append({"stage": "retrieval", "error_code": failures[-1]})
        timings["retrieval_ms"] = round((time.monotonic() - before) * 1000, 2)

    def search_web(is_caat: bool) -> list[Evidence]:
        before = time.monotonic()
        try:
            results = search_web_fallback(search_query, is_caat_topic=is_caat, deadline=deadline, diagnostics=diagnostics)
        except Exception as exc:
            logger.warning("Web search unavailable (%s)", type(exc).__name__)
            diagnostics.append({"stage": "web_search", "error_code": classify_service_error(exc)})
            results = []
        timings["web_search_ms"] = round((time.monotonic() - before) * 1000, 2)
        found = web_evidence(results)
        diagnostics.append({"stage": "web", "source_count": len(found)})
        return found

    def generate(evidence: list[Evidence], stage: str) -> natural_answer.NaturalAnswer | str:
        before = time.monotonic()
        try:
            raw = call_llm(natural_answer.build_messages(question, evidence, previous), client=client,
                           deadline=deadline, max_attempts=2, structured=False)
        except Exception as exc:
            code = getattr(exc, "error_code", "") or ("invalid_response" if isinstance(exc, RuntimeError)
                                                      and not hasattr(exc, "status_code") else classify_service_error(exc))
            diagnostics.append({"stage": stage, "error_code": code})
            return code
        finally:
            timings[f"{stage}_generation_ms"] = round((time.monotonic() - before) * 1000, 2)
        answer = natural_answer.render(raw, evidence)
        diagnostics.append({"stage": stage, "not_found": answer.not_found, "kept": len(answer.lines),
                            "dropped": answer.dropped})
        return answer

    searched = caat_web or current
    web: list[Evidence] = search_web(caat_web) if searched else []
    evidence = pack_evidence(kb + web, required_ids={e.id for e in web}) if (kb or web) else []
    if not evidence:
        if failures:
            return failure(common_error(failures), "Document retrieval unavailable")
        web = [] if searched else search_web(False)
        searched = True
        evidence = pack_evidence(web) if web else []
    if not evidence:
        timings["total_ms"] = round((time.monotonic() - started) * 1000, 2)
        message = (f"ยังไม่พบหลักฐานเพียงพอที่จะยืนยันข้อกำหนดนี้ครับ ตรวจสอบข้อมูลทางการได้ที่ {CAAT_PORTAL_INFOGRAPHIC_URL}"
                   if caat else ABSTAIN_MESSAGE)
        return CragResponse(message, "abstain", "INCORRECT", "No evidence", dict(timings), [], list(diagnostics))

    result = generate(evidence, "answer")
    if isinstance(result, str):
        return failure(result, "LLM generation failed")
    if result.clarify:
        # The sources hold several things the question could mean: ask, do not answer another topic.
        timings["total_ms"] = round((time.monotonic() - started) * 1000, 2)
        return CragResponse(result.text, "knowledge_base", "AMBIGUOUS", "Clarifying question", dict(timings), [],
                            list(diagnostics))
    needs_caat = any(item.startswith(natural_answer.CAAT_PAGE_REQUIRED) for item in result.dropped)
    if not searched and (result.not_found or not result.text or needs_caat):
        # The documents have nothing on this (R4/R5), or a drone rule was stated without the CAAT
        # page it needs: search once. Document facts stay in the evidence unless there were none.
        web = search_web(caat_web or needs_caat)
        if web:
            evidence = (pack_evidence(kb + web, required_ids={e.id for e in web})
                        if kb and not result.not_found else pack_evidence(web))
            result = generate(evidence, "web_answer")
            if isinstance(result, str):
                return failure(result, "LLM generation failed")

    timings["total_ms"] = round((time.monotonic() - started) * 1000, 2)
    if not result.text:
        message = (f"ยังไม่พบหลักฐานเพียงพอที่จะยืนยันข้อกำหนดนี้ครับ ตรวจสอบข้อมูลทางการได้ที่ {CAAT_PORTAL_INFOGRAPHIC_URL}"
                   if caat else ABSTAIN_MESSAGE)
        reason = "Every answer line failed verification" if result.dropped else "No evidence"
        return CragResponse(message, "abstain", "INCORRECT", reason, dict(timings), [], list(diagnostics))
    by_id = {e.id: e for e in evidence}
    kinds = {bool(by_id[i].url) for i in result.used_ids}
    source: SourceType = ("hybrid" if len(kinds) > 1 else ("caat_portal" if caat_web else "web_fallback")
                          if True in kinds else "knowledge_base")
    grade = "AMBIGUOUS" if (result.gap or result.dropped) else "CORRECT"
    trace = [{"text": line, "evidence": [{"source_id": i, "citation": by_id[i].citation} for i in ids]}
             for line, ids in result.lines if ids]
    return CragResponse(result.text, source, grade, "; ".join(result.dropped)[:300] or "Natural answer",
                        dict(timings), trace, list(diagnostics))


def run_crag_pipeline(query: str, n_results: int = 8, client: OpenAI | None = None,
                      previous_question: str | None = None) -> CragResponse:
    if answer_mode() == "natural":
        return run_natural_pipeline(query, n_results, client, previous_question)
    started = time.monotonic()
    deadline = started + float(os.getenv("RAG_REQUEST_TIMEOUT_SECONDS", "22"))
    timings: dict[str, float] = {}
    diagnostics: list[dict] = []
    llm_down = False
    failure_codes: list[str] = []

    def respond(result: GroundedResult, evidence: list[Evidence], caat: bool = False) -> CragResponse:
        used = {s for claim in result.claims for s in claim.source_ids}
        actual = [e for e in evidence if e.id in used]
        source: SourceType = "abstain"
        if actual:
            kinds = {bool(e.url) for e in actual}
            source = ("hybrid" if len(kinds) > 1 else ("caat_portal" if caat else "web_fallback")
                      if True in kinds else "knowledge_base")
        errors = failure_codes + ([result.error_code] if result.error_code else [])
        if not errors and (result.llm_unavailable or llm_down):
            errors = ["provider_unavailable"]
        error_code = common_error(errors) if errors and result.status != "sufficient" else ""
        message = ERROR_MESSAGES.get(error_code, DEGRADED_MESSAGE) if error_code else ""
        # A partial answer keeps the failure next to the part it explains, not after the references.
        answer = render_grounded_answer(result, evidence, service_note=message)
        if error_code and not actual:
            answer = message
        elif caat and not actual:
            answer = f"ยังไม่พบหลักฐานเพียงพอที่จะยืนยันข้อกำหนดนี้ครับ ตรวจสอบข้อมูลทางการได้ที่ {CAAT_PORTAL_INFOGRAPHIC_URL}"
        timings["total_ms"] = round((time.monotonic() - started) * 1000, 2)
        grade = {"sufficient": "CORRECT", "partial": "AMBIGUOUS", "insufficient": "INCORRECT"}[result.status]
        trace = [{"text": claim.text, "evidence": [
            {"source_id": source_id, "quote": quote, "citation": next(e.citation for e in actual if e.id == source_id),
             **{k: v for e in actual if e.id == source_id for k, v in
                {"source_file": e.source_file, "page_number": e.page_number, "page_from": e.page_from,
                 "page_end": e.page_end, "url": e.url}.items() if v}}
            for source_id, quote in claim.quotes]} for claim in result.claims]
        return CragResponse(answer, source, grade, result.reason, dict(timings), trace, list(diagnostics), error_code)

    clean_query = query.strip()
    # Typos / wrong-layout text are repaired once and used for retrieval, the LLM and web search,
    # so the model never sees "2 gfnvo" while retrieval saw "2 เดือน".
    search_query = normalize_query(clean_query)
    if not clean_query:
        return CragResponse("กรุณาระบุคำถามเกี่ยวกับโดรนการเกษตรครับ", "abstain", "INCORRECT", "Empty query")
    intent = route_intent(clean_query)
    if intent.intent == "bot_usage":
        return CragResponse(intent.handled_response or "", "bot_usage", "CORRECT", "Bot usage")

    pool_error = llm_pool_error()
    if pool_error:
        diagnostics.append({"stage": "llm_pool", "error_code": pool_error, "llm_unavailable": True})
        return respond(GroundedResult(reason="No callable LLM models in known cooldown state",
                                      llm_unavailable=True, error_code=pool_error), [])

    caat = is_caat_air_law_or_airspace_topic(clean_query)
    parts = split_query_aspects(search_query) if caat else []
    technical_parts = [part for part in parts if not is_caat_air_law_or_airspace_topic(part)]
    legal_parts = [part for part in parts if is_caat_air_law_or_airspace_topic(part)]
    mixed_caat = bool(caat and technical_parts and legal_parts)
    kb: list[Evidence] = []
    initial = GroundedResult(reason="No document evidence")
    if not caat or mixed_caat:
        before = time.monotonic()
        try:
            kb_query = " ".join(technical_parts) if mixed_caat else search_query
            kb = pack_evidence(retrieve_evidence(kb_query, n_results=n_results, deadline=deadline))
        except Exception as exc:
            logger.warning("Document retrieval unavailable (%s)", type(exc).__name__)
            initial.reason = "Document retrieval unavailable"
            error_code = classify_service_error(exc)
            failure_codes.append(error_code)
            diagnostics.append({"stage": "retrieval", "error_code": error_code})
        timings["retrieval_ms"] = round((time.monotonic() - before) * 1000, 2)
        if kb:
            before = time.monotonic()
            kb_deadline = min(deadline, before + KB_GENERATION_BUDGET_SECONDS)
            initial = evaluate_evidence(search_query, kb, client, kb_deadline, max_attempts=1)
            diagnostics.append({"stage": "kb", "status": initial.status, "reason": initial.reason,
                                "llm_unavailable": initial.llm_unavailable, "error_code": initial.error_code})
            timings["kb_generation_ms"] = round((time.monotonic() - before) * 1000, 2)
            llm_down = llm_down or initial.llm_unavailable
            if initial.error_code:
                failure_codes.append(initial.error_code)
            caat = caat or initial.is_caat_topic
            if mixed_caat and initial.status == "sufficient":
                initial = GroundedResult("partial", initial.claims, legal_parts,
                                         "Regulatory part requires designated web evidence", True, intro=initial.intro)
            # A PDF cannot establish current prices/news, even if the model says sufficient.
            if initial.status == "sufficient" and any(term in search_query for term in ["วันนี้", "ล่าสุด", "ปัจจุบัน"]):
                aspects = split_query_aspects(search_query)
                current = [part for part in aspects if any(term in part for term in ["วันนี้", "ล่าสุด", "ปัจจุบัน"])]
                static = [part for part in aspects if part not in current]
                safe_claims = [claim for claim in initial.claims if not any(term in claim.text
                              for term in ["ราคา", "บาท", "วันนี้", "ล่าสุด", "ปัจจุบัน", "ตอนนี้"])] if static else []
                initial = GroundedResult("partial" if safe_claims else "insufficient", safe_claims,
                                         current or [search_query], "Current information requires web evidence", caat,
                                         intro=initial.intro if safe_claims else "")
            if not caat and initial.status == "sufficient":
                return respond(initial, kb)
            # The web is for what the documents lack, not for our own failures (2026-10-20 screening:
            # only 2 of 7 web detours were real gaps; the web answers that replaced failed KB
            # generations were slow, irrelevant, twice harmful). A KB generation that failed
            # (timeout, cut-off output, quota) would need the same model again for the web answer,
            # and a gap made only by the verifier dropping claims names no topic to search for.
            kb_llm_failed = initial.llm_unavailable or bool(initial.error_code)
            only_rejected = (initial.status == "partial"
                             and set(initial.missing_aspects) <= {REJECTED_CLAIMS_ASPECT})
            if kb_llm_failed or (only_rejected and not caat):
                diagnostics.append({"stage": "web", "skipped": "kb_llm_failed" if kb_llm_failed else "rejected_claims_only"})
                return respond(initial, kb, caat)
    if caat and not mixed_caat:
        kb = []
        initial = GroundedResult(reason="CAAT designated source required")

    # Generation may have just exhausted the last model. Web/embeddings cannot
    # repair that; preserve any supported partial answer and stop external work.
    pool_error = llm_pool_error()
    if pool_error:
        diagnostics.append({"stage": "llm_pool", "error_code": pool_error, "llm_unavailable": True})
        failure_codes.append(pool_error)
        return respond(initial, kb, caat)

    before = time.monotonic()
    web_diagnostics_start = len(diagnostics)
    web_query = " ".join(legal_parts) if mixed_caat else search_query
    if initial.missing_aspects:
        web_query += " " + " ".join(initial.missing_aspects)
    try:
        results = search_web_fallback(web_query, is_caat_topic=caat, deadline=deadline, diagnostics=diagnostics)
    except Exception as exc:
        logger.warning("Web search unavailable (%s)", type(exc).__name__)
        diagnostics.append({"stage": "web_search", "error_code": classify_service_error(exc)})
        results = []
    failure_codes.extend(d["error_code"] for d in diagnostics[web_diagnostics_start:] if d.get("error_code"))
    timings["web_search_ms"] = round((time.monotonic() - before) * 1000, 2)
    web = web_evidence(results)
    diagnostics.append({"stage": "web", "source_count": len(web)})
    if not web:
        return respond(initial if initial.status == "partial" else GroundedResult(reason="No verified web evidence"), kb, caat)

    # Preserve useful KB sources; irrelevant documents must not contaminate web answers.
    if initial.status == "partial":
        used = {s for claim in initial.claims for s in claim.source_ids}
        kb = [e for e in kb if e.id in used]
    else:
        kb = []
    combined = pack_evidence(kb + web, required_ids={e.id for e in kb})
    if not combined or not any(e.url for e in combined):
        return respond(initial, kb, caat)
    before = time.monotonic()
    final = evaluate_evidence(search_query, combined, client, deadline, verified_claims=initial.claims)
    diagnostics.append({"stage": "combined", "status": final.status, "reason": final.reason,
                        "llm_unavailable": final.llm_unavailable, "error_code": final.error_code})
    timings["final_generation_ms"] = round((time.monotonic() - before) * 1000, 2)
    llm_down = llm_down or final.llm_unavailable
    final = preserve_partial_answer(initial, final)
    return respond(final, combined, caat)
