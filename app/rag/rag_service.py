from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Lock

from openai import OpenAI

from app.config import API_KEY
from app.rag.evidence import Evidence, GroundedResult, parse_grounded_result

logger = logging.getLogger(__name__)
_llm_client: OpenAI | None = None
_client_lock = Lock()
FALLBACK_MODELS = ["gemini-3.5-flash-lite", "gpt-5.6-luna", "nova-2-lite-v1", "llama-4-scout"]
_EXHAUSTED_MODELS: dict[str, float] = {}
SYSTEM_PROMPT = (Path(__file__).parent / "prompts" / "grounded_answer.txt").read_text(encoding="utf-8")


def get_llm_client() -> OpenAI:
    global _llm_client
    with _client_lock:
        if _llm_client is None:
            _llm_client = OpenAI(api_key=API_KEY, base_url="https://gen.ai.kku.ac.th/api/v1", timeout=8.0, max_retries=0)
    return _llm_client


def call_llm(messages: list[dict], client: OpenAI | None = None, preferred_model: str | None = None,
             temperature: float = 0.0, max_tokens: int | None = None, deadline: float | None = None,
             max_attempts: int = 2) -> str:
    ai_client = client or get_llm_client()
    preferred = preferred_model or os.getenv("RAG_MODEL", "gemini-3.5-flash-lite")
    candidates = list(dict.fromkeys([preferred] + FALLBACK_MODELS))
    candidates = [m for m in candidates if _EXHAUSTED_MODELS.get(m, 0) <= time.monotonic()]
    for model in candidates[:max_attempts]:
        remaining = (deadline - time.monotonic()) if deadline is not None else 8.0
        if remaining <= 0.2:
            break
        try:
            # Generous headroom for the structured JSON (claims + citation quotes): a
            # real production chat log showed truncated answers at a lower limit. Output
            # that still hits this limit is discarded below rather than used truncated.
            response = ai_client.chat.completions.create(model=model, messages=messages, temperature=temperature,
                max_tokens=max_tokens or 2200, stream=False, timeout=min(8.0, remaining))
            if not response or not response.choices:
                continue
            choice = response.choices[0]
            # Reasoning and truncated output are never treated as a final answer.
            if choice.finish_reason not in {"stop", None}:
                continue
            content = choice.message.content
            if isinstance(content, str) and content.strip():
                return content
        except Exception as exc:
            if getattr(exc, "status_code", None) in {401, 429}:
                _EXHAUSTED_MODELS[model] = time.monotonic() + 60
            logger.warning("LLM request failed for %s (%s)", model, type(exc).__name__)
    raise RuntimeError("No complete LLM response within request budget")


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
            return GroundedResult(reason=str(exc))
        result = parse_grounded_result(raw, evidence)
        if not result.reason.startswith("Evidence validation failed"):
            return result
        if deadline is not None and deadline - time.monotonic() <= 0.5:
            break
    return result
