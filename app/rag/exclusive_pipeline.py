"""LINE delivery: choose one evidence source per question and never merge sources.

Policy (2026-10-31):
1. Document-first RAG: answer from KB documents first when applicable.
2. Web Fallback: if the KB has no relevant evidence or answers NOT_FOUND, fall back
   to searching the web and answer exclusively from web sources (never merging KB + Web).
3. Strict Mixed-Question Rejection: if a question combines real-time/current calendar
   calculations or web/CAAT topics with KB agronomy/manual rules (e.g. "ปลูกอ้อยตั้งแต่เดือน...
   จนถึงเดือนนี้ ตอนนี้ต้องพ่นอะไร"), abstain cleanly and explain that document and web
   sources are separated.
"""
from __future__ import annotations

import os
import re
import time

from app.rag import crag_service as legacy, natural_answer, official_fuel
from app.rag.application_scope import ApplicationScope, web_source_applicable
from app.rag.crag_grader import is_caat_air_law_or_airspace_topic
from app.rag.evidence import (
    ABSTAIN_MESSAGE,
    _is_aviation_regulation,
    is_drone_rule_topic,
    pack_evidence,
    render_grounded_answer,
)
from app.rag.intent_router import route_intent
from app.rag.page_reranker import split_query_aspects
from app.rag.query_normalizer import normalize_query
from app.rag.source_policy import CAAT_PORTAL_INFOGRAPHIC_URL, SUPPORTED_CROPS, without_document_ids
from app.service_status import ERROR_MESSAGES, classify_service_error

WEB_TERMS = (
    "วันนี้", "ล่าสุด", "ปัจจุบัน", "ตอนนี้", "เมื่อวาน", "เมื่อไม่กี่วัน", "ไม่กี่วันมานี้",
    "ช่วงนี้", "สัปดาห์นี้", "เร็วๆ นี้", "เร็วๆนี้",
    "เว็บ", "เน็ต", "ออนไลน์", "internet", "web search", "online",
)
EXPLICIT_WEB_TERMS = (
    "เว็บ", "เน็ต", "ออนไลน์", "internet", "web search", "online",
    "ราคาน้ำมัน", "ดีเซล", "เบนซิน", "พยากรณ์อากาศ", "สภาพอากาศวันนี้", "ราคาตลาดวันนี้",
)
LIVE_EXTERNAL_TERMS = ("ราคาน้ำมัน", "ดีเซล", "เบนซิน", "พยากรณ์อากาศ", "สภาพอากาศวันนี้", "ฝนตกวันนี้", "อุณหภูมิวันนี้", "ราคาตลาดวันนี้")
MIXED_ABSTAIN_MESSAGE = (
    "ยังไม่พบหลักฐานเพียงพอจากแหล่งเดียว เนื่องจากคำถามนี้ผสมเนื้อหาในเอกสารอ้างอิงเข้ากับข้อมูลจากอินเทอร์เน็ต"
    "หรือข้อมูลเวลาปัจจุบัน ซึ่งระบบแยกการตอบระหว่างเอกสารกับเว็บไซต์ออกจากกันอย่างชัดเจนโดยไม่นำมาผสมกัน "
    "กรุณาแยกถามทีละหัวข้อ หรือระบุเงื่อนไขที่มีในเอกสารโดยตรงครับ"
)

_THAI_MONTHS = (
    r"มกราคม|กุมภาพันธ์|มีนาคม|เมษายน|พฤษภาคม|มิถุนายน|"
    r"กรกฎาคม|สิงหาคม|กันยายน|ตุลาคม|พฤศจิกายน|ธันวาคม|"
    r"ม\.ค\.|ก\.พ\.|มี\.ค\.|เม\.ย\.|พ\.ค\.|มิ\.ย\.|"
    r"ก\.ค\.|ส\.ค\.|ก\.ย\.|ต\.ค\.|พ\.ย\.|ธ\.ค\."
)
_REALTIME_TEMPORAL_DEPENDENCE = re.compile(
    rf"(?:ปลูก[^\n?]*ตั้งแต่\s*เดือน|ตั้งแต่\s*(?:เดือน|วันที่|ต้นปี|กลางปี)?\s*(?:{_THAI_MONTHS})?[^\n?]*(?:ถึง|จนถึง|มาถึง)\s*(?:เดือนนี้|ตอนนี้|ปัจจุบัน|วันนี้|สัปดาห์นี้|ช่วงนี้)|"
    rf"(?:เริ่มปลูก|ปลูกเมื่อ)[^\n?]*(?:เดือนนี้|ตอนนี้|ปัจจุบัน|วันนี้)|"
    rf"(?:เดือนนี้|ตอนนี้|วันนี้|ช่วงนี้|สัปดาห์นี้)\s*(?:ต้อง|ควร)?\s*(?:พ่น|ฉีด|หว่าน|ใส่ปุ๋ย|ใช้สาร|คุมวัชพืช|ระวังโรค|เสี่ยงโรค)|"
    rf"(?:สภาพอากาศ|อากาศ|ฝน|อุณหภูมิ)\s*(?:วันนี้|ตอนนี้|ช่วงนี้|ล่าสุด)[^\n?]*(?:เสี่ยง|โรค|แมลง|พ่น|ฉีด)|"
    rf"(?:วันนี้|ตอนนี้|ช่วงนี้|สัปดาห์นี้)[^\n?]*(?:สภาพอากาศ|อากาศ|ฝน|ร้อน|หนาว|อุณหภูมิ)[^\n?]*(?:เสี่ยง|โรค|แมลง|พ่น|ฉีด))",
    re.IGNORECASE,
)
_KB_MANUAL_TERMS = (
    "พ่น", "ฉีด", "หว่าน", "วัชพืช", "สารเคมี", "ยาคุม", "ยาฆ่า", "สารจับใบ", "ฮอร์โมน",
    "หัวฉีด", "พัดส้ม", "พัดฟ้า", "พัดน้ำเงิน", "พัดเหลือง", "พัดแดง", "อัตราการไหล", "ขนาดหยด", "ไมครอน",
    "ผสมสาร", "ลำดับการผสม", "ค่า ph", "น้ำผสมสาร", "หนอนกอ", "เพลี้ย", "โรคไหม้", "กาบใบเน่า", "ขอบใบแห้ง",
    "จุดคุ้มทุน", "คืนทุน", "ต้นทุนต่อไร่", "ค่าเสื่อมราคา", "ล้างถัง", "ล้างปั๊ม", "แบตเตอรี่บวม", "gsd", "overlap",
)
_DIRECT_WEB_SEARCH_PREFIX = re.compile(
    r"^\s*(?:ช่วย\s*)?(?:ค้น(?:หา)?(?:ข้อมูล)?(?:ใน|จาก)?(?:เว็บ|อินเทอร์เน็ต|เน็ต|ออนไลน์)|"
    r"หา(?:ข้อมูล|คู่มือ)?(?:ใน|จาก)?(?:เว็บ|อินเทอร์เน็ต|เน็ต|ออนไลน์)|web\s*search)",
    re.IGNORECASE,
)
_DRONE_MODEL_CODE = re.compile(
    r"\b(?:T\d{2,3}[A-Z]?|P\d{2,3}[A-Z]?|V\d{2,3}[A-Z]?|G\d{2,3}[A-Z]?|M\d{2,3}[A-Z]?|AR-\d+[A-Za-z0-9/-]*)\b",
    re.IGNORECASE,
)


def _is_caat(text: str) -> bool:
    return (is_caat_air_law_or_airspace_topic(text) or _is_aviation_regulation(text)
            or is_drone_rule_topic(text))


def _has_kb_manual_topic(text: str) -> bool:
    low = text.casefold()
    return any(c in text for c in SUPPORTED_CROPS) or any(t in low for t in _KB_MANUAL_TERMS)


def _is_web_or_realtime_clause(text: str) -> bool:
    low = text.casefold()
    return (
        _is_caat(text)
        or any(t in low for t in EXPLICIT_WEB_TERMS)
        or bool(_REALTIME_TEMPORAL_DEPENDENCE.search(text))
    )


def is_mixed_kb_web_question(question: str) -> bool:
    """True when a question mixes ANY web/real-time/external topic with a KB manual topic."""
    q = normalize_query(question or "")
    if not q:
        return False
    # Explicit user instruction to search the web applies to the whole question, never a mixed conflict
    if _DIRECT_WEB_SEARCH_PREFIX.match(q):
        return False
    # 1. Real-time / relative temporal dependence combined with a KB manual topic
    if _REALTIME_TEMPORAL_DEPENDENCE.search(q) and _has_kb_manual_topic(q):
        return True
    if any(w in q for w in ("เดือนนี้", "ตอนนี้", "วันนี้", "ช่วงนี้")) and ("ปลูก" in q) and _has_kb_manual_topic(q):
        if re.search(rf"เดือน\s*(?:{_THAI_MONTHS})|ตั้งแต่", q):
            return True
    # 2. Multi-clause question combining a KB manual clause with a Web/CAAT/live-price/real-time clause
    clauses = split_query_aspects(q)
    if len(clauses) >= 2:
        has_web_clause = any(_is_web_or_realtime_clause(c) for c in clauses)
        has_kb_clause = any(
            (_has_kb_manual_topic(c) or "ก่อนบิน" in c)
            and not _is_web_or_realtime_clause(c)
            for c in clauses
        )
        if has_web_clause and has_kb_clause:
            return True
    # 3. Single-sentence hybrid combining external live data/CAAT law with KB agronomy/cost/mixing rules
    low = q.casefold()
    has_external = _is_caat(q) or any(t in low for t in LIVE_EXTERNAL_TERMS)
    if has_external and _has_kb_manual_topic(q):
        return True
    return False


def _retrieve_kb(query, scope, n_results, deadline, diagnostics):
    mode = os.getenv("RAG_KB_RETRIEVER", "legacy").strip().lower()
    if mode != "legacy":
        raise ValueError("Unknown KB retriever")
    diagnostics.append({"stage": "retriever_selection", "name": "legacy"})
    return legacy.retrieve_evidence(query, n_results=n_results, deadline=deadline, source_scope=scope)


def _retrieve_web(query, caat, deadline, diagnostics, client):
    mode = os.getenv("RAG_WEB_RETRIEVER", "legacy").strip().lower()
    if mode == "legacy":
        diagnostics.append({"stage": "retriever_selection", "name": "legacy_web"})
        return legacy.search_web_fallback(query, is_caat_topic=caat, deadline=deadline, diagnostics=diagnostics)
    if mode == "read":
        from app.rag.web_retrieval import retrieve_web
        diagnostics.append({"stage": "retriever_selection", "name": "planned_search_and_read"})
        return retrieve_web(query, is_caat_topic=caat, deadline=deadline, diagnostics=diagnostics, client=client)
    raise ValueError("Unknown web retriever")


def _generate_from_evidence(normalized: str, evidence: list, mode: str, caat: bool,
                            client, deadline: float, diagnostics: list[dict], result_fn):
    by_id = {e.id: e for e in evidence}
    if legacy.answer_mode() == "natural":
        # Strip 'today' when answering from KB so the model never guesses relative calendar crop age
        messages = natural_answer.build_messages(normalized, evidence, include_today=(mode == "web"))
        raw = legacy.call_llm(messages, client=client, deadline=deadline, max_attempts=1, structured=False)
        answer = natural_answer.render(raw, evidence)
        first_line = ((raw or "").strip().splitlines() or [""])[0].strip()
        if mode == "kb" and (
            not answer.text
            or re.match(
                r"^(?:ยัง)?(?:ไม่พบ(?:ข้อมูล|รุ่น|รายการ|ในแหล่งข้อมูล|ในตาราง|ในเอกสาร)|ไม่มี(?:ข้อมูล|รุ่น|ระบุ|ในแหล่งข้อมูล|ในตาราง|ในเอกสาร)|ในแหล่งข้อมูลไม่มี|แหล่งข้อมูลไม่(?:ได้)?(?:ระบุ|ปรากฏ))",
                first_line,
            )
        ):
            answer.not_found = True
        diagnostics.append({"stage": "answer", "dropped": answer.dropped, "source_mode": mode, "not_found": answer.not_found})
        if not answer.text:
            return None, answer
        trace = [{"text": line, "evidence": [{"source_id": sid, "citation": by_id[sid].citation} for sid in ids]}
                 for line, ids in answer.lines if ids]
        grade = "AMBIGUOUS" if answer.gap or answer.dropped else "CORRECT"
        return result_fn(
            answer.text,
            "knowledge_base" if mode == "kb" else "caat_portal" if caat else "web_fallback",
            grade,
            "; ".join(answer.dropped)[:300] or "Exclusive natural answer",
            trace=trace,
        ), answer
    checked = legacy.evaluate_evidence(normalized, evidence, client, deadline, max_attempts=1)
    diagnostics.append({"stage": "answer", "status": checked.status, "reason": checked.reason, "source_mode": mode})
    if checked.llm_unavailable or checked.error_code:
        code = checked.error_code or "provider_unavailable"
        if not checked.claims:
            return result_fn(
                ERROR_MESSAGES.get(code, ERROR_MESSAGES["provider_unavailable"]),
                "abstain", "INCORRECT", "Generation failed", error=code,
            ), checked
    if not checked.claims:
        return None, checked
    answer_text = render_grounded_answer(checked, evidence)
    if answer_text == ABSTAIN_MESSAGE:
        return None, checked
    trace = [{"text": claim.text, "evidence": [{"source_id": sid, "quote": quote, "citation": by_id[sid].citation}
             for sid, quote in claim.quotes]} for claim in checked.claims]
    return result_fn(
        answer_text,
        "knowledge_base" if mode == "kb" else "caat_portal" if caat else "web_fallback",
        "CORRECT" if checked.status == "sufficient" else "AMBIGUOUS",
        checked.reason,
        trace=trace,
    ), checked


def run_exclusive_pipeline(query: str, n_results: int = 8, client=None) -> legacy.CragResponse:
    """Answer from KB first; fall back to Web if KB cannot answer; refuse mixed KB+Web questions."""
    started = time.monotonic()
    deadline = started + float(os.getenv("RAG_REQUEST_TIMEOUT_SECONDS", "22"))
    question = (query or "").strip()
    diagnostics = []

    def result(text, source, grade, reason, *, error="", trace=None):
        return legacy.CragResponse(
            text, source, grade, reason,
            {"total_ms": round((time.monotonic() - started) * 1000, 2)},
            trace or [], diagnostics, error,
        )

    if not question:
        return result("กรุณาระบุคำถามเกี่ยวกับโดรนการเกษตรครับ", "abstain", "INCORRECT", "Empty question")
    intent = route_intent(question)
    if intent.intent == "bot_usage":
        return result(intent.handled_response or "", "bot_usage", "CORRECT", "Bot usage")

    normalized = normalize_query(question)
    if is_mixed_kb_web_question(question):
        diagnostics.append({"stage": "source_route", "selected": "abstain_mixed", "exclusive": True})
        return result(MIXED_ABSTAIN_MESSAGE, "abstain", "INCORRECT", "Mixed KB and web question not supported")

    caat = _is_caat(question)
    upfront_web = caat or any(t in normalized.casefold() for t in WEB_TERMS)
    mode = "web" if upfront_web else "kb"
    diagnostics.append({"stage": "source_route", "selected": mode, "exclusive": True})

    pool_error = legacy.llm_pool_error()
    if pool_error:
        return result(
            ERROR_MESSAGES.get(pool_error, ERROR_MESSAGES["provider_unavailable"]),
            "abstain", "INCORRECT", "No callable model", error=pool_error,
        )

    try:
        table_mode = os.getenv("RAG_TABLE_EXECUTOR", "off").strip().lower()
        if table_mode != "off":
            raise ValueError("Unknown table executor")

        kb_fallback_response = None
        if mode == "kb":
            scope = ApplicationScope(question)
            raw_kb = _retrieve_kb(normalized, scope, n_results, deadline, diagnostics)
            raw_kb = [e for e in raw_kb if e.source_file and not e.url]
            scoped_kb = [e for e in raw_kb if scope.allows_source(e.source_file)]
            diagnostics.append(scope.diagnostic())
            evidence = pack_evidence(scoped_kb)
            diagnostics.append({"stage": "retrieval", "source_mode": "kb", "source_count": len(evidence)})

            # If KB had documents filtered out solely by strict application scope (e.g., survey-only manual
            # for a general question), abstain rather than pulling consumer drone web pages.
            if not evidence and raw_kb and not scoped_kb:
                return result(ABSTAIN_MESSAGE, "abstain", "INCORRECT", "No evidence matching application scope")

            kb_model_missing = False
            if evidence:
                queried_models = list(dict.fromkeys(m.upper() for m in _DRONE_MODEL_CODE.findall(normalized)))
                if queried_models:
                    kb_blob = " ".join(f"{e.content} {e.title}" for e in evidence).upper()
                    models_in_kb = [m for m in queried_models if re.search(rf"\b{re.escape(m)}\b", kb_blob)]
                    if len(queried_models) >= 2 and models_in_kb and len(models_in_kb) < len(queried_models):
                        diagnostics.append({"stage": "source_route", "selected": "abstain_mixed_models", "exclusive": True})
                        return result(MIXED_ABSTAIN_MESSAGE, "abstain", "INCORRECT", "Mixed KB and web question not supported")
                    if not models_in_kb:
                        kb_model_missing = True
                        diagnostics.append({"stage": "kb_fast_skip", "reason": "queried_model_not_in_kb", "models": queried_models})
                if not kb_model_missing and not _has_kb_manual_topic(normalized):
                    latin_entities = [
                        tok.upper() for tok in re.findall(r"[A-Za-z][A-Za-z0-9-]{2,}", without_document_ids(normalized))
                        if tok.casefold() not in {"drone", "uav", "uas", "pdf", "app", "line", "bot"}
                    ]
                    if latin_entities:
                        kb_blob = " ".join(f"{e.content} {e.title}" for e in evidence).upper()
                        if not any(re.search(rf"\b{re.escape(ent)}\b", kb_blob) for ent in latin_entities):
                            kb_model_missing = True
                            diagnostics.append({"stage": "kb_fast_skip", "reason": "queried_entity_not_in_kb", "entities": latin_entities})

            if evidence and not kb_model_missing:
                kb_response, kb_state = _generate_from_evidence(
                    normalized, evidence, "kb", False, client, deadline, diagnostics, result,
                )
                # If a multi-part question has one part answered by KB and another part missing from KB (gap),
                # block it as a mixed KB + external question rather than merging or dropping the external part.
                if (
                    kb_response is not None
                    and getattr(kb_state, "gap", "")
                    and len(split_query_aspects(normalized)) >= 2
                    and re.search(
                        r"(?:รุ่น|โดรน|ราคา|ตลาด|วันนี้|ตอนนี้|เว็บ|ออนไลน์|กพท|caat|ขึ้นทะเบียน|กฎหมาย|[A-Za-z]{2,}\s*-?\s*\d+)",
                        kb_state.gap,
                        re.IGNORECASE,
                    )
                ):
                    diagnostics.append({"stage": "source_route", "selected": "abstain_mixed_partial", "exclusive": True})
                    return result(MIXED_ABSTAIN_MESSAGE, "abstain", "INCORRECT", "Mixed KB and web question not supported")
                if kb_response is not None and not getattr(kb_state, "not_found", False):
                    return kb_response
                kb_fallback_response = kb_response
                # If lines were dropped by grounding validator (not NOT_FOUND), do not fall back to web
                if getattr(kb_state, "dropped", None) and not getattr(kb_state, "not_found", False):
                    return result(ABSTAIN_MESSAGE, "abstain", "INCORRECT", "No validated answer")

            # KB had no evidence OR model returned NOT_FOUND -> Fall back to Web (exclusively Web, no KB mixing)
            if os.getenv("RAG_DISABLE_WEB_FALLBACK", "").strip() == "1":
                return kb_fallback_response or result(ABSTAIN_MESSAGE, "abstain", "INCORRECT", "No evidence from KB")
            mode = "web"
            deadline = max(deadline, time.monotonic() + float(os.getenv("RAG_REQUEST_TIMEOUT_SECONDS", "22")))
            diagnostics.append({"stage": "web_fallback_route", "reason": "kb_not_found_or_empty", "exclusive": True})

        # Web execution (either upfront web or fallback from KB NOT_FOUND)
        if official_fuel.matches(question):
            try:
                fuel_res = official_fuel.render_prices(official_fuel.read_prices(question, deadline=deadline))
                diagnostics.extend(fuel_res.diagnostics)
                return result(fuel_res.answer, "web_fallback", "CORRECT", "Official fuel price feed",
                              trace=fuel_res.evidence_trace)
            except Exception as exc:
                diagnostics.append({"stage": "official_fuel_fallback", "reason": type(exc).__name__})

        results = _retrieve_web(normalized, caat, deadline, diagnostics, client)
        excluded = [getattr(r, "url", "") for r in results if not web_source_applicable(question, r)]
        results = [r for r in results if web_source_applicable(question, r)]
        if excluded:
            diagnostics.append({
                "stage": "web_application_scope",
                "excluded_urls": excluded,
                "reason": "consumer_family_for_agricultural_question",
            })
        web_sources = [e for e in legacy.web_evidence(results) if e.url and not e.source_file]
        web_ev = pack_evidence(web_sources)
        diagnostics.append({"stage": "retrieval", "source_mode": "web", "source_count": len(web_ev)})
        if not web_ev:
            errors = [d.get("error_code") for d in diagnostics if d.get("error_code")]
            if errors:
                code = errors[0]
                return result(
                    ERROR_MESSAGES.get(code, ERROR_MESSAGES["provider_unavailable"]),
                    "abstain", "INCORRECT", "Source retrieval failed", error=code,
                )
            message = (
                f"ยังไม่พบหลักฐานเพียงพอที่จะยืนยันข้อกำหนดนี้ครับ ตรวจสอบข้อมูลทางการได้ที่ {CAAT_PORTAL_INFOGRAPHIC_URL}"
                if caat else ABSTAIN_MESSAGE
            )
            return result(message, "abstain", "INCORRECT", "No evidence from selected source")

        web_response, _ = _generate_from_evidence(
            normalized, web_ev, "web", caat, client, deadline, diagnostics, result,
        )
        if web_response is not None:
            return web_response
        return result(ABSTAIN_MESSAGE, "abstain", "INCORRECT", "No validated answer")
    except Exception as exc:
        code = getattr(exc, "error_code", "") or classify_service_error(exc)
        return result(
            ERROR_MESSAGES.get(code, ERROR_MESSAGES["provider_unavailable"]),
            "abstain", "INCORRECT", f"Exclusive pipeline failed: {type(exc).__name__}", error=code,
        )
