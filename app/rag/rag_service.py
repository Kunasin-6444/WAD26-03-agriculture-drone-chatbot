from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Lock

from openai import APIConnectionError, OpenAI

from app.config import LLM_API_KEY, LLM_BASE_URL
from app.rag.evidence import Claim, Evidence, GroundedResult, document_page_evidence, merge_verified_partial, parse_grounded_result
from app.rag.page_reranker import split_query_aspects

logger = logging.getLogger(__name__)
_llm_client: OpenAI | None = None
_client_lock = Lock()
_DEFAULT_FALLBACK_MODELS = ["gemini-3.5-flash-lite", "gpt-5.6-luna", "nova-2-lite-v1"]
# LLM_FALLBACK_MODELS (comma-separated) overrides this; set it empty to disable fallbacks.
# Needed when LLM_BASE_URL is not the KKU gateway, since those model names don't exist elsewhere.
_fallback_env = os.getenv("LLM_FALLBACK_MODELS")
FALLBACK_MODELS = (
    _DEFAULT_FALLBACK_MODELS if _fallback_env is None
    else [m.strip() for m in _fallback_env.split(",") if m.strip()]
)
_EXHAUSTED_MODELS: dict[str, float] = {}
# Optional second provider for quota/auth or transient transport/server failures.
# Quota rejections are refunded; timeouts still consume the attempt/deadline budget.
# Disabled unless both
# base URL and key are set. Models default to the preferred model name; reasoning effort is
# its own knob because the primary's value may not be valid on another provider.
SECONDARY_BASE_URL = (os.getenv("LLM_SECONDARY_BASE_URL") or "").strip()
SECONDARY_API_KEY = (os.getenv("LLM_SECONDARY_API_KEY") or "").strip()
SECONDARY_MODELS = [m.strip() for m in (os.getenv("LLM_SECONDARY_MODELS") or "").split(",") if m.strip()]
SECONDARY_REASONING_EFFORT = (os.getenv("LLM_SECONDARY_REASONING_EFFORT") or "").strip().lower()
_SECONDARY_PREFIX = "secondary:"
# Optional thinking-budget hint (e.g. none/minimal/low/medium/high) for reasoning-capable models
# such as Gemini 3.x; unset sends nothing so providers that reject the field are unaffected.
REASONING_EFFORT = (os.getenv("LLM_REASONING_EFFORT") or "").strip().lower()
# Enforce the grounded-answer JSON schema server-side (response_format json_schema). Off by
# default because not every OpenAI-compatible provider supports it; parse_grounded_result stays
# the real gate either way.
STRUCTURED_OUTPUT = (os.getenv("LLM_STRUCTURED_OUTPUT") or "").strip().lower() in {"1", "true", "yes", "on"}
SECONDARY_STRUCTURED_OUTPUT = (os.getenv("LLM_SECONDARY_STRUCTURED_OUTPUT") or "").strip().lower() in {"1", "true", "yes", "on"}
_GROUNDED_RESPONSE_FORMAT = {"type": "json_schema", "json_schema": {"name": "grounded_answer", "strict": True, "schema": {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": ["sufficient", "partial", "insufficient"]},
        "reason": {"type": "string"},
        "is_caat_topic": {"type": "boolean"},
        "missing_aspects": {"type": "array", "items": {"type": "string"}},
        "intro": {"type": "string"},
        "claims": {"type": "array", "items": {"type": "object", "properties": {
            "text": {"type": "string"},
            "evidence": {"type": "array", "items": {"type": "object", "properties": {
                "source_id": {"type": "string"}, "quote": {"type": "string"}},
                "required": ["source_id", "quote"]}}},
            "required": ["text", "evidence"]}},
    },
    "required": ["status", "reason", "is_caat_topic", "missing_aspects", "intro", "claims"]}}}
# Per-attempt LLM timeout. Raise it (e.g. 11) for providers with spiky latency; the request
# deadline in crag_service still bounds the total.
ATTEMPT_TIMEOUT_SECONDS = float(os.getenv("LLM_ATTEMPT_TIMEOUT_SECONDS", "8"))
# A "daily limit" 401 won't clear until the quota resets; a transient 401/429 usually will.
DAILY_LIMIT_COOLDOWN_SECONDS = 30 * 60
TRANSIENT_COOLDOWN_SECONDS = 60


class LLMUnavailableError(RuntimeError):
    """Every LLM attempt failed outright (errors/quota), as opposed to a merely unusable response."""


# RAG_PROMPT picks the answer prompt so variants can be measured on the same gold set before one
# becomes the default (scripts.evaluate_answers). "full" is the long rule list; "concise" states
# the same output contract and accuracy rules grouped by principle.
PROMPT_VARIANTS = {"full": "grounded_answer.txt", "concise": "grounded_answer_concise.txt"}
_PROMPTS = {name: (Path(__file__).parent / "prompts" / file).read_text(encoding="utf-8")
            for name, file in PROMPT_VARIANTS.items()}
SYSTEM_PROMPT = _PROMPTS["full"]


def system_prompt() -> str:
    variant = (os.getenv("RAG_PROMPT") or "full").strip().lower()
    if variant not in _PROMPTS:
        raise ValueError(f"RAG_PROMPT must be one of {sorted(_PROMPTS)}, got {variant!r}")
    return _PROMPTS[variant]


def get_llm_client() -> OpenAI:
    global _llm_client
    with _client_lock:
        if _llm_client is None:
            _llm_client = OpenAI(api_key=LLM_API_KEY, base_url=LLM_BASE_URL, timeout=ATTEMPT_TIMEOUT_SECONDS, max_retries=0)
    return _llm_client


_secondary_client: OpenAI | None = None


def secondary_enabled() -> bool:
    return bool(SECONDARY_BASE_URL and SECONDARY_API_KEY)


def get_secondary_client() -> OpenAI:
    global _secondary_client
    with _client_lock:
        if _secondary_client is None:
            _secondary_client = OpenAI(api_key=SECONDARY_API_KEY, base_url=SECONDARY_BASE_URL,
                                       timeout=ATTEMPT_TIMEOUT_SECONDS, max_retries=0)
    return _secondary_client


def call_llm(messages: list[dict], client: OpenAI | None = None, preferred_model: str | None = None,
             temperature: float = 0.0, max_tokens: int | None = None, deadline: float | None = None,
             max_attempts: int = 2) -> str:
    ai_client = client or get_llm_client()
    preferred = preferred_model or os.getenv("RAG_MODEL", "gemini-3.5-flash-lite")
    # (cooldown key, model name, uses secondary provider). Primary keys stay the bare model
    # name; the secondary gets a prefix so the same model name on two providers can't collide.
    primary = [(m, m, False) for m in dict.fromkeys([preferred] + FALLBACK_MODELS)]
    secondary = []
    if secondary_enabled():
        secondary = [(_SECONDARY_PREFIX + m, m, True) for m in dict.fromkeys(SECONDARY_MODELS or [preferred])]
    # After an explicit quota/auth rejection, try the configured alternate provider
    # before slow models on the same exhausted gateway consume the entire budget.
    # A timed-out model is cooled down too, so final generation does not call
    # the same stalled model again after KB generation already spent its budget.
    candidates = primary[:1] + secondary + primary[1:]
    now = time.monotonic()
    allow_secondary = _EXHAUSTED_MODELS.get(preferred, 0) > now
    available = [c for c in candidates if _EXHAUSTED_MODELS.get(c[0], 0) <= now]
    if not available:
        # Everything is cooling down. A short (transient) cooldown means the provider throttled a
        # burst, not that quota is gone: keep trying instead of failing every request for a
        # minute. Long (daily-limit) cooldowns still fail fast so they don't burn the budget.
        available = [c for c in candidates if _EXHAUSTED_MODELS.get(c[0], 0) - now <= TRANSIENT_COOLDOWN_SECONDS]
    candidates = available
    if not candidates:
        raise LLMUnavailableError("All LLM models are in quota/rate-limit cooldown")
    attempted = failed = slow = 0
    for key, model, on_secondary in candidates:
        if on_secondary and not allow_secondary:
            continue
        # max_attempts bounds attempts that can spend time. Quota/auth errors (401/429) come
        # back immediately, so they are refunded below and can walk on to the next model or
        # provider without eating the request budget (the deadline check still applies).
        if slow >= max_attempts:
            break
        remaining = (deadline - time.monotonic()) if deadline is not None else ATTEMPT_TIMEOUT_SECONDS
        if remaining <= 0.2:
            break
        attempted += 1
        slow += 1
        try:
            # Generous headroom for the structured JSON (claims + citation quotes): a
            # real production chat log showed truncated answers at a lower limit. Output
            # that still hits this limit is discarded below rather than used truncated.
            effort = SECONDARY_REASONING_EFFORT if on_secondary else REASONING_EFFORT
            extra = {"extra_body": {"reasoning_effort": effort}} if effort else {}
            if STRUCTURED_OUTPUT or (on_secondary and SECONDARY_STRUCTURED_OUTPUT):
                extra["response_format"] = _GROUNDED_RESPONSE_FORMAT
            response = (get_secondary_client() if on_secondary else ai_client).chat.completions.create(
                model=model, messages=messages, temperature=temperature,
                max_tokens=max_tokens or 2200, stream=False, timeout=min(ATTEMPT_TIMEOUT_SECONDS, remaining), **extra)
            _log_model_quota(model, response)
            if not response or not response.choices:
                continue
            choice = response.choices[0]
            # Reasoning and truncated output are never treated as a final answer.
            if choice.finish_reason not in {"stop", None}:
                continue
            content = choice.message.content
            if isinstance(content, str) and content.strip():
                _EXHAUSTED_MODELS.pop(key, None)
                if on_secondary:
                    logger.warning("LLM failover: answered by secondary provider model %s", model)
                return content
        except Exception as exc:
            failed += 1
            if getattr(exc, "status_code", None) in {401, 429}:
                cooldown = DAILY_LIMIT_COOLDOWN_SECONDS if _is_daily_limit(exc) else TRANSIENT_COOLDOWN_SECONDS
                _EXHAUSTED_MODELS[key] = time.monotonic() + cooldown
                slow -= 1
                if not on_secondary:
                    allow_secondary = True
            elif isinstance(exc, (TimeoutError, ConnectionError, APIConnectionError)) or (
                    isinstance(getattr(exc, "status_code", None), int) and exc.status_code >= 500):
                _EXHAUSTED_MODELS[key] = time.monotonic() + TRANSIENT_COOLDOWN_SECONDS
                if not on_secondary:
                    allow_secondary = True
            logger.warning("LLM request failed for %s%s (%s)", model, " [secondary]" if on_secondary else "",
                           type(exc).__name__)
    if attempted and failed == attempted:
        raise LLMUnavailableError("Every LLM attempt failed outright")
    raise RuntimeError("No complete LLM response within request budget")


def _is_daily_limit(exc: Exception) -> bool:
    body = getattr(exc, "body", None) or getattr(exc, "message", "") or str(exc)
    return "daily limit" in str(body).lower()


def _log_model_quota(model: str, response) -> None:
    """Surface the gateway's quota info (e.g. daily_remaining_tokens) so exhaustion is visible early."""
    try:
        quota = getattr(response, "model_quota", None)
        if quota is None:
            quota = (getattr(response, "model_extra", None) or {}).get("model_quota")
        if quota:
            logger.info("LLM quota for %s: %s", model, quota)
    except Exception:
        pass


def warm_up_retrieval() -> None:
    """Pay the first-request cost at startup: importing slide_retriever opens Chroma (~4.5s,
    measured) and the BM25 index is built (~0.3s). retrieve_context imports it lazily."""
    from app.rag.direct_pdf import enabled, get_collection
    if enabled():
        get_collection().count()
        return
    from app.rag import slide_retriever
    slide_retriever.warm_up()


def retrieve_context(query: str, n_results: int = 8, deadline: float | None = None) -> str:
    from app.rag.direct_pdf import enabled, search_pdf_context
    if enabled():
        return search_pdf_context(query, top_k=max(1, n_results), deadline=deadline)
    from app.rag.slide_retriever import search_slides_pipeline
    return search_slides_pipeline(query, top_k=max(1, n_results))["context"]


def retrieve_evidence(query: str, n_results: int = 8, deadline: float | None = None) -> list[Evidence]:
    """Live citation boundary: metadata comes from the index, never parsed from PDF text."""
    from app.rag.direct_pdf import enabled, search_pdf_evidence
    if enabled():
        return search_pdf_evidence(query, top_k=max(1, n_results), deadline=deadline)
    from app.rag.slide_retriever import search_slides_pipeline
    pages = search_slides_pipeline(query, top_k=max(1, n_results))["top_pages"]
    return document_page_evidence(pages)


def evaluate_evidence(query: str, evidence: list[Evidence], client: OpenAI | None = None,
                      deadline: float | None = None, max_attempts: int = 2,
                      verified_claims: list[Claim] | None = None) -> GroundedResult:
    if not evidence:
        return GroundedResult(reason="No evidence")
    payload = {"question": query, "today": datetime.now(timezone(timedelta(hours=7))).date().isoformat(),
               # Empty fields (a document has no url/title, web has no file/page) carry nothing.
               "sources": [{k: v for k, v in e.__dict__.items() if v} for e in evidence]}
    parts = split_query_aspects(query)
    if parts:
        payload["question_parts"] = parts
    if "พัดฟ้า (พัดน้ำเงิน)" in query:
        # This equivalence already comes from the deterministic query normalizer.
        # Make it explicit so the model does not search for a third nozzle type.
        payload["query_aliases"] = {"พัดฟ้า": "พัดน้ำเงิน"}
    if verified_claims:
        payload["verified_claims"] = [{"text": claim.text, "source_ids": claim.source_ids}
                                      for claim in verified_claims]
    messages = [{"role": "system", "content": system_prompt()},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}]
    result = GroundedResult(reason="No LLM response")
    best_partial = GroundedResult()
    # A syntactically-fine response that fails strict evidence verification (e.g. the model
    # paraphrased a quote instead of copying it verbatim) is retried once within the same
    # deadline rather than treated as final: the model is not perfectly deterministic even
    # at temperature=0, and a second attempt often produces a verbatim, verifiable quote.
    for _ in range(2):
        try:
            raw = call_llm(messages, client=client, deadline=deadline, max_attempts=max_attempts)
        except RuntimeError as exc:
            failure = GroundedResult(reason=str(exc), llm_unavailable=isinstance(exc, LLMUnavailableError))
            return merge_verified_partial(best_partial, failure)
        result = parse_grounded_result(raw, evidence)
        invalid = result.reason.startswith(("Evidence validation failed", "Some claims rejected"))
        if not invalid:
            return merge_verified_partial(best_partial, result)
        if result.status == "partial":
            best_partial = merge_verified_partial(best_partial, result)
        logger.warning("Grounded response rejected: %s", result.reason)
        messages = messages + [{"role": "assistant", "content": raw}, {"role": "user", "content":
            "แก้ JSON ตามข้อผิดพลาดการตรวจนี้: " + result.reason +
            " ใช้เฉพาะหลักฐานเดิม คัด quote ตรงตัว อย่าแก้ตัวเลขให้ผ่านการตรวจ "
            "ถ้าบางประเด็นไม่รองรับ ให้เก็บข้อที่รองรับและตอบ partial พร้อมระบุส่วนที่ขาด "
            "ถ้าใช้ข้อที่ผ่านแล้วซ้ำ ให้คง text เดิมทุกตัวอักษร: " +
            json.dumps([claim.text for claim in best_partial.claims], ensure_ascii=False)}]
        if deadline is not None and deadline - time.monotonic() <= 0.5:
            break
    return merge_verified_partial(best_partial, result)
