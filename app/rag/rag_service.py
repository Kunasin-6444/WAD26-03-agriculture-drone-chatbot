from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Lock

from openai import OpenAI

from app.config import LLM_API_KEY, LLM_BASE_URL
from app.rag.evidence import Evidence, GroundedResult, parse_grounded_result

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
# Optional second provider, used only when the primary provider's models are out of quota
# (401/429 answer instantly, so failing over costs no request budget). Disabled unless both
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
_GROUNDED_RESPONSE_FORMAT = {"type": "json_schema", "json_schema": {"name": "grounded_answer", "strict": True, "schema": {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": ["sufficient", "partial", "insufficient"]},
        "reason": {"type": "string"},
        "is_caat_topic": {"type": "boolean"},
        "missing_aspects": {"type": "array", "items": {"type": "string"}},
        "claims": {"type": "array", "items": {"type": "object", "properties": {
            "text": {"type": "string"},
            "evidence": {"type": "array", "items": {"type": "object", "properties": {
                "source_id": {"type": "string"}, "quote": {"type": "string"}},
                "required": ["source_id", "quote"]}}},
            "required": ["text", "evidence"]}},
    },
    "required": ["status", "reason", "is_caat_topic", "missing_aspects", "claims"]}}}
# Per-attempt LLM timeout. Raise it (e.g. 11) for providers with spiky latency; the request
# deadline in crag_service still bounds the total.
ATTEMPT_TIMEOUT_SECONDS = float(os.getenv("LLM_ATTEMPT_TIMEOUT_SECONDS", "8"))
# A "daily limit" 401 won't clear until the quota resets; a transient 401/429 usually will.
DAILY_LIMIT_COOLDOWN_SECONDS = 30 * 60
TRANSIENT_COOLDOWN_SECONDS = 60


class LLMUnavailableError(RuntimeError):
    """Every LLM attempt failed outright (errors/quota), as opposed to a merely unusable response."""


SYSTEM_PROMPT = (Path(__file__).parent / "prompts" / "grounded_answer.txt").read_text(encoding="utf-8")


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
    candidates = [(m, m, False) for m in dict.fromkeys([preferred] + FALLBACK_MODELS)]
    if secondary_enabled():
        candidates += [(_SECONDARY_PREFIX + m, m, True) for m in dict.fromkeys(SECONDARY_MODELS or [preferred])]
    now = time.monotonic()
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
            if STRUCTURED_OUTPUT:
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


def retrieve_context(query: str, n_results: int = 8) -> str:
    from app.rag.slide_retriever import search_slides_pipeline
    return search_slides_pipeline(query, top_k=max(1, n_results))["context"]


def evaluate_evidence(query: str, evidence: list[Evidence], client: OpenAI | None = None,
                      deadline: float | None = None, max_attempts: int = 2) -> GroundedResult:
    if not evidence:
        return GroundedResult(reason="No evidence")
    payload = {"question": query, "today": datetime.now(timezone(timedelta(hours=7))).date().isoformat(),
               "sources": [e.__dict__ for e in evidence]}
    messages = [{"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}]
    result = GroundedResult(reason="No LLM response")
    # A syntactically-fine response that fails strict evidence verification (e.g. the model
    # paraphrased a quote instead of copying it verbatim) is retried once within the same
    # deadline rather than treated as final: the model is not perfectly deterministic even
    # at temperature=0, and a second attempt often produces a verbatim, verifiable quote.
    for _ in range(2):
        try:
            raw = call_llm(messages, client=client, deadline=deadline, max_attempts=max_attempts)
        except RuntimeError as exc:
            return GroundedResult(reason=str(exc), llm_unavailable=isinstance(exc, LLMUnavailableError))
        result = parse_grounded_result(raw, evidence)
        if not result.reason.startswith("Evidence validation failed"):
            return result
        if deadline is not None and deadline - time.monotonic() <= 0.5:
            break
    return result
