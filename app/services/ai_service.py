import os
import re
import threading
import time

from app.rag.crag_service import run_crag_pipeline
from app.services.rich_menu_service import get_rich_menu_preanswer

# Verified answers are cached in memory so a repeated question (a demo, a popular FAQ) is
# answered instantly and does not depend on the LLM provider being fast at that moment.
# Only fully grounded answers are cached; abstains, degraded replies and web answers
# (which may be stale) never are.
_CACHEABLE_SOURCES = {"knowledge_base", "caat_portal"}
_FRESHNESS_TERMS = ("วันนี้", "ล่าสุด", "ปัจจุบัน", "ตอนนี้", "ราคา")
_MAX_ENTRIES = 256
_cache: dict[str, tuple[float, str]] = {}
_lock = threading.Lock()


def _ttl_seconds() -> float:
    try:
        return float(os.getenv("ANSWER_CACHE_TTL_SECONDS", "3600"))
    except ValueError:
        return 0.0


def _key(message: str) -> str:
    return re.sub(r"\s+", " ", message).strip().casefold()


def clear_answer_cache() -> None:
    with _lock:
        _cache.clear()


def ask_ai(user_message: str) -> str:
    """
    Answer user query using Corrective RAG (CRAG) pipeline:
    1. Instant pre-answer check for Rich Menu queries
    2. Local knowledge base retrieval & relevance grading
    3. Web fallback (Tavily & official sources) if insufficient
    4. Designated CAAT UAS portal routing for Air Law/Air Space
    5. Abstain path if unverified (zero hallucination)
    """
    # 1. Rich Menu pre-answer fast-path
    pre_answer = get_rich_menu_preanswer(user_message)
    if pre_answer:
        return pre_answer

    # 2. In-memory cache check
    ttl = _ttl_seconds()
    key = _key(user_message)
    now = time.monotonic()
    if ttl > 0 and key:
        with _lock:
            hit = _cache.get(key)
            if hit and hit[0] > now:
                return hit[1]

    # 3. CRAG Pipeline execution
    response = run_crag_pipeline(user_message)

    if (ttl > 0 and key and response.source_type in _CACHEABLE_SOURCES and response.grade == "CORRECT"
            and not any(term in key for term in _FRESHNESS_TERMS)):
        with _lock:
            if len(_cache) >= _MAX_ENTRIES:
                _cache.pop(next(iter(_cache)))
            _cache[key] = (now + ttl, response.answer)
    return response.answer
