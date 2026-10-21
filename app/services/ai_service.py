import os
import re
import threading
import time
from pathlib import Path
from concurrent.futures import Future, TimeoutError as FutureTimeout

from app.rag.crag_service import run_crag_pipeline
from app.service_status import ERROR_MESSAGES
from app.services.rich_menu_service import MENU_ANSWER, get_rich_menu_preanswer, is_menu_request

# Verified answers are cached in memory so a repeated question (a demo, a popular FAQ) is
# answered instantly and does not depend on the LLM provider being fast at that moment.
# Only fully grounded answers are cached; abstains, degraded replies and web answers
# (which may be stale) never are.
_CACHEABLE_SOURCES = {"knowledge_base"}
_FRESHNESS_TERMS = ("วันนี้", "ล่าสุด", "ปัจจุบัน", "ตอนนี้", "ราคา")
_MAX_ENTRIES = 256
_cache: dict[tuple, tuple[float, str]] = {}
_lock = threading.Lock()
_inflight: dict[tuple, Future] = {}


def _ttl_seconds() -> float:
    try:
        return float(os.getenv("ANSWER_CACHE_TTL_SECONDS", "3600"))
    except ValueError:
        return 0.0


def _kb_fingerprint() -> tuple:
    """Observe persisted index changes without opening Chroma or calling an API.

    SQLite commits can live in the WAL, so checking the main database alone is
    insufficient. Include a deployment-provided revision for versioned publishing.
    """
    root = Path(__file__).resolve().parents[2]
    database = Path(os.getenv("CHROMA_PATH", str(root / "chroma_db"))).resolve()
    files = []
    for name in ("chroma.sqlite3", "chroma.sqlite3-wal"):
        try:
            stat = (database / name).stat()
            files.append((name, stat.st_mtime_ns, stat.st_size))
        except FileNotFoundError:
            files.append((name, None, None))
    return str(database), os.getenv("KB_REVISION", ""), tuple(files)


def _key(message: str) -> tuple:
    return (re.sub(r"\s+", " ", message).strip().casefold(),
            os.getenv("PDF_RETRIEVAL_MODE", "text").strip().lower(),
            os.getenv("PDF_READER_MODEL", ""), os.getenv("RETRIEVER_RERANK", "diverse"),
            os.getenv("RETRIEVER_BM25", "global"),
            _kb_fingerprint())


def clear_answer_cache() -> None:
    with _lock:
        _cache.clear()


_topics: dict[str, tuple[float, str]] = {}
_MAX_TOPICS = 1000


def previous_question(user_id: str | None, message: str) -> str | None:
    """The user's last full question when ``message`` is a short follow-up ("สูงแค่ไหน"), else None.

    Each LINE message used to be answered alone, so "ข้อมูลการบิน" after a question on spraying sugarcane
    was answered about survey drones (LINE test, 2026-10-21). A full question becomes the topic; short
    messages within CONVERSATION_TTL_SECONDS are read with it and do not replace it."""
    try:
        ttl = float(os.getenv("CONVERSATION_TTL_SECONDS", "600"))
        short = int(os.getenv("FOLLOW_UP_MAX_CHARS", "30"))
    except ValueError:
        return None
    text = re.sub(r"\s+", " ", message or "").strip()
    if not user_id or ttl <= 0 or not text:
        return None
    now = time.monotonic()
    with _lock:
        if len(text) > short:
            _topics.pop(user_id, None)
            if len(_topics) >= _MAX_TOPICS:
                _topics.pop(next(iter(_topics)))
            _topics[user_id] = (now + ttl, text)
            return None
        last = _topics.get(user_id)
        return last[1] if last and last[0] > now else None


def ask_ai(user_message: str, user_id: str | None = None) -> str:
    """
    Answer user query using Corrective RAG (CRAG) pipeline:
    1. Local knowledge base retrieval & relevance grading
    2. Web fallback (Tavily & official sources) if insufficient
    3. Designated CAAT UAS portal routing for Air Law/Air Space
    4. Abstain path if unverified (zero hallucination)
    """
    # Rich menu buttons get their fixed guide at once, without the pipeline.
    pre_answer = get_rich_menu_preanswer(user_message)
    if pre_answer:
        return pre_answer
    if is_menu_request(user_message):
        return MENU_ANSWER

    previous = previous_question(user_id, user_message)
    if previous:
        # The answer depends on the earlier question, so it is neither cached nor shared.
        return run_crag_pipeline(user_message, previous_question=previous).answer

    ttl = _ttl_seconds()
    message = re.sub(r"\s+", " ", user_message).strip().casefold()
    key = _key(user_message) if ttl > 0 and message and not any(term in message for term in _FRESHNESS_TERMS) else ()
    now = time.monotonic()
    future, owner = None, False
    if ttl > 0 and key:
        with _lock:
            hit = _cache.get(key)
            if hit and hit[0] > now:
                return hit[1]
            future = _inflight.get(key)
            if future is None:
                future = Future()
                _inflight[key] = future
                owner = True
    if future is not None and not owner:
        try:
            return future.result(timeout=float(os.getenv("RAG_REQUEST_TIMEOUT_SECONDS", "22")) + 2)
        except FutureTimeout:
            return ERROR_MESSAGES["timeout"]

    try:
        response = run_crag_pipeline(user_message)
        if (ttl > 0 and key and response.source_type in _CACHEABLE_SOURCES and response.grade == "CORRECT"
                and key == _key(user_message)):
            with _lock:
                if len(_cache) >= _MAX_ENTRIES:
                    _cache.pop(next(iter(_cache)))
                _cache[key] = (time.monotonic() + ttl, response.answer)
        if future is not None:
            future.set_result(response.answer)
        return response.answer
    except BaseException as exc:
        if future is not None:
            future.set_exception(exc)
        raise
    finally:
        if future is not None:
            with _lock:
                if _inflight.get(key) is future:
                    del _inflight[key]
