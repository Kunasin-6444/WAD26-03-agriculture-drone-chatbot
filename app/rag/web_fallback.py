from __future__ import annotations

import logging
import os
import re
import threading
import time
from dataclasses import dataclass
from urllib.parse import urlparse

from tavily import TavilyClient

from app.config import TAVILY_API_KEY
from app.rag.evidence import Evidence
from app.rag.source_policy import CAAT_DESIGNATED_URLS, is_caat_url, valid_web_url
from app.service_status import classify_service_error

logger = logging.getLogger(__name__)
TRUSTED_DOMAINS = ["caat.or.th", "nstda.or.th", "thaipbs.or.th", "pttor.com", "bangchak.co.th", "dji.com"]
# Official/known domains are prioritized first; open web fallback is allowed for reliable
# informational sources while excluding social media, forums, and invalid/spoofed hosts.
PREFERRED_DOMAINS = ["doa.go.th", "doae.go.th", "moac.go.th", "eppo.go.th", "caat.or.th", "pttor.com", "bangchak.co.th"]
WEB_ALLOWED_DOMAINS = list(dict.fromkeys(TRUSTED_DOMAINS + PREFERRED_DOMAINS))
EXCLUDED_WEB_DOMAINS = (
    "facebook.com", "fb.com", "tiktok.com", "instagram.com", "twitter.com", "x.com",
    "youtube.com", "youtu.be", "threads.net", "pantip.com", "reddit.com", "pinterest.com",
    "postjung.com", "dek-d.com", "blockdit.com",
)
MAX_WEB_TIMEOUT_SECONDS = float(os.getenv("WEB_SEARCH_TIMEOUT_SECONDS", "6"))
_client_local = threading.local()

_META_SEARCH_PREFIX = re.compile(
    r"^\s*(?:ช่วย\s*)?(?:ค้น(?:หา)?(?:ข้อมูล)?(?:ใน|จาก)?(?:เว็บ(?:ไซต์)?(?:ทางการ)?|อินเทอร์เน็ต|อินเตอร์เน็ต|เน็ต|ออนไลน์)|"
    r"หา(?:ข้อมูล|คู่มือ)?(?:ใน|จาก)?(?:เว็บ(?:ไซต์)?(?:ทางการ)?|อินเทอร์เน็ต|อินเตอร์เน็ต|เน็ต|ออนไลน์)|"
    r"web\s*search|internet)\s*[:：]?\s*",
    re.IGNORECASE,
)


def _prepare_manufacturer_search(query: str) -> tuple[str, list[str] | None, bool]:
    """Clean meta-search prefixes and map international manufacturer queries to official domains/terms."""
    cleaned = _META_SEARCH_PREFIX.sub("", (query or "").strip())
    cleaned = re.sub(r"\bจากแหล่งทางการ\b", "", cleaned).strip(" :：-")
    cleaned = re.sub(r"^ไม(?!(?:่|้|ครอน|ล์))(?=[ก-๙]{2,})", "ทำไม", cleaned)
    cleaned = re.sub(r"เมื่อไม่กี่วันมานี้|ไม่กี่วันมานี้|เมื่อไม่นานมานี้|เมื่อกี้|เมื่อสักครู่", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    q_low = cleaned.casefold()
    if any(b in q_low for b in ("dji", "agras")):
        domains = ["ag.dji.com", "dji.com"]
        extra_latin = [
            tok for tok in re.findall(r"[A-Za-z0-9-]+", cleaned)
            if tok.casefold() not in {"dji", "agras", "drone"}
        ]
        en_terms = ["DJI Agras", *extra_latin]
        if any(t in q_low for t in ("ก่อนบิน", "ตรวจ", "เช็ค", "เตรียม")):
            en_terms.append("before flight check inspection maintenance")
        if "แบต" in q_low:
            en_terms.append("battery")
        if "ใบพัด" in q_low:
            en_terms.append("propeller")
        if "เรดาร์" in q_low or "กันชน" in q_low:
            en_terms.append("radar obstacle avoidance")
        if any(t in q_low for t in ("สเปก", "ความจุ", "ถัง", "อัตราการไหล", "น้ำหนัก", "บรรทุก")):
            en_terms.append("spray tank payload capacity specifications")
        if len(en_terms) > 1:
            return " ".join(en_terms), domains, True
        return f"{cleaned} DJI Agras".strip(), domains, True
    return (cleaned or query), None, False


def allowed_domains() -> list[str]:
    # Operator-approved official manufacturers/organizations can be added without
    # source-code edits. User questions and fetched content cannot change this policy.
    extras = [d.strip().lower().rstrip(".") for d in os.getenv("WEB_ALLOWED_DOMAINS_EXTRA", "").split(",") if d.strip()]
    extras = [d for d in extras if "." in d and valid_web_url("https://" + d) and get_domain("https://" + d) == d]
    return list(dict.fromkeys(WEB_ALLOWED_DOMAINS + extras))


def designated_caat_urls() -> list[str]:
    configured = [u.strip() for u in os.getenv("CAAT_DESIGNATED_URLS", "").split(",") if u.strip()]
    return [u for u in (configured or CAAT_DESIGNATED_URLS) if is_caat_url(u)]


def get_domain(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower().rstrip(".")
    except ValueError:
        return ""


def is_trusted_domain(url: str) -> bool:
    if not valid_web_url(url):
        return False
    hostname = get_domain(url)
    return hostname.endswith((".go.th", ".ac.th", ".gov", ".edu")) or any(
        hostname == domain or hostname.endswith("." + domain) for domain in allowed_domains()
    )


def is_reliable_web_url(url: str) -> bool:
    """Allow general reliable HTTPS web pages while blocking spoofed/test hosts and social/forum noise."""
    if not valid_web_url(url):
        return False
    hostname = get_domain(url)
    if (
        not hostname
        or hostname.endswith(".example")
        or hostname.startswith(("board.", "forum.", "forums."))
        or ("caat.or.th" in hostname and not is_caat_url(url))
    ):
        return False
    return not any(hostname == d or hostname.endswith("." + d) for d in EXCLUDED_WEB_DOMAINS)


@dataclass
class WebSearchResult:
    title: str
    url: str
    content: str
    score: float = 0.0
    is_trusted: bool = False


def get_tavily_client(api_key: str | None = None) -> TavilyClient | None:
    key = api_key or TAVILY_API_KEY
    if not key:
        return None
    cached = getattr(_client_local, "entry", None)
    if cached is None or cached[0] != key:
        if cached is not None:
            cached[1].close()
        # requests.Session is reused for keep-alive within a worker thread;
        # mutable sessions are never shared across concurrent worker threads.
        _client_local.entry = (key, TavilyClient(api_key=key))
    return _client_local.entry[1]


def _timeout(deadline: float | None) -> float:
    remaining = deadline - time.monotonic() if deadline else MAX_WEB_TIMEOUT_SECONDS
    if remaining <= 0.2:
        raise TimeoutError("Web search budget exhausted")
    return min(MAX_WEB_TIMEOUT_SECONDS, remaining)


def _results(items: list[dict], is_caat: bool) -> list[WebSearchResult]:
    results, seen = [], set()
    for item in items:
        url = item.get("url", "").strip()
        content = (item.get("content") or item.get("raw_content") or "").strip()
        if not (is_trusted_domain(url) if is_caat else is_reliable_web_url(url)) or not content or url.rstrip("/") in seen:
            continue
        host = get_domain(url)
        if is_caat and not (host == "caat.or.th" or host.endswith(".caat.or.th")):
            continue
        seen.add(url.rstrip("/"))
        # An extracted document has no title ("None" reached a reference list, 2026-10-20).
        title = str(item.get("title") or "").strip() or ("เอกสารทางการ CAAT" if is_caat_url(url) else "แหล่งข้อมูลเว็บไซต์")
        results.append(WebSearchResult(title, url, content,
            float(item.get("score") or 0), is_trusted_domain(url)))
    return sorted(results, key=lambda r: (r.is_trusted, r.score), reverse=True)


def search_web_fallback(query: str, is_caat_topic: bool = False, max_results: int = 4,
                        tavily_client: TavilyClient | None = None, deadline: float | None = None,
                        diagnostics: list[dict] | None = None, *, stop_on_timeout: bool = False) -> list[WebSearchResult]:
    def failed(stage: str, exc: Exception | None = None):
        if diagnostics is not None:
            kind = ("not_configured" if exc is None else "budget_exhausted" if str(exc) == "Web search budget exhausted"
                    else "provider_timeout" if "timeout" in type(exc).__name__.lower() else "provider_error")
            diagnostics.append({"stage": stage, "error": kind,
                                "error_code": "configuration" if exc is None else classify_service_error(exc)})
    if max_results < 1:
        return []
    client = tavily_client or get_tavily_client()
    if not client:
        failed("web_search")
        return []
    extracted = []
    if is_caat_topic:
        try:
            response = client.extract(urls=designated_caat_urls(), query=query,
                chunks_per_source=3, extract_depth="basic", format="text", timeout=_timeout(deadline))
            if stop_on_timeout and any(isinstance(f, dict) and any(term in str(f.get("error", "")).lower()
                    for term in ("timeout", "timed out")) for f in response.get("failed_results", [])):
                raise TimeoutError("A designated source extraction timed out")
            extracted = _results(response.get("results", []), True)
        except Exception as exc:
            failed("caat_extract", exc)
            logger.warning("CAAT extraction unavailable (%s)", type(exc).__name__)
            if stop_on_timeout and (classify_service_error(exc) == "timeout"
                                    or "timeout" in type(exc).__name__.lower()):
                return []
    try:
        search_q, custom_domains, needs_advanced = _prepare_manufacturer_search(query) if not is_caat_topic else (query, None, True)
        kwargs = dict(query=search_q, search_depth="basic", max_results=max_results, timeout=_timeout(deadline))
        if is_caat_topic:
            kwargs.update(include_domains=["uasportal.caat.or.th", "caat.or.th"], include_domains_mode="restrict")
        elif custom_domains:
            kwargs.update(include_domains=custom_domains, include_domains_mode="restrict")
        else:
            kwargs.update(exclude_domains=list(EXCLUDED_WEB_DOMAINS))
        if is_caat_topic or needs_advanced:
            # A basic result is a ~140-character page summary; the requirement itself sits deep in a
            # CAAT PDF or DJI Agras manual. Advanced search returns passages matching the question.
            kwargs.update(search_depth="advanced", chunks_per_source=3)
        response = client.search(**kwargs)
        found = _results(response.get("results", []), is_caat_topic)
        if not found and custom_domains and not is_caat_topic:
            fallback_kwargs = dict(query=search_q, search_depth="basic", max_results=max_results,
                                   timeout=_timeout(deadline), exclude_domains=list(EXCLUDED_WEB_DOMAINS))
            response = client.search(**fallback_kwargs)
            found = _results(response.get("results", []), False)
    except Exception as exc:
        failed("web_search", exc)
        logger.warning("Web search unavailable (%s)", type(exc).__name__)
        found = []
    # The designated official document first: a short question ("ประกันโดรน") ranks it below the cut.
    seen, combined = set(), []
    for result in extracted + found:
        if result.url not in seen:
            seen.add(result.url)
            combined.append(result)
    return combined[:max_results]


def web_evidence(results: list[WebSearchResult]) -> list[Evidence]:
    evidence = []
    for result in results:
        if not is_reliable_web_url(result.url) or not result.content.strip():
            continue
        # Retain complete paragraphs/lines rather than chopping words or table rows.
        chunks, lines, length = [], [], 0
        for line in result.content.splitlines():
            if length + len(line) + 1 > 4500 and lines:
                chunks.append("\n".join(lines))
                lines, length = [], 0
            # Long lines are whole evidence too. The caller applies the context
            # budget and records omissions; do not silently erase fetched facts.
            lines.append(line)
            length += len(line) + 1
        if lines:
            chunks.append("\n".join(lines))
        for chunk in chunks:
            if chunk.strip():
                evidence.append(Evidence(f"W{len(evidence) + 1}", chunk.strip(), url=result.url, title=result.title))
    return evidence


def format_web_context(results: list[WebSearchResult]) -> str:
    return "\n\n".join(f"[{e.id}]\nURL: {e.url}\nเนื้อหา:\n{e.content}" for e in web_evidence(results))
