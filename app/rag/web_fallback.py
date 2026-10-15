from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from urllib.parse import urlparse

from tavily import TavilyClient

from app.config import TAVILY_API_KEY
from app.rag.evidence import Evidence
from app.rag.source_policy import CAAT_PORTAL_INFOGRAPHIC_URL, valid_web_url

logger = logging.getLogger(__name__)
TRUSTED_DOMAINS = ["caat.or.th", "nstda.or.th", "thaipbs.or.th", "pttor.com", "bangchak.co.th"]
PREFERRED_DOMAINS = ["doa.go.th", "doae.go.th", "moac.go.th", "eppo.go.th", "caat.or.th", "pttor.com", "bangchak.co.th"]


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
        hostname == domain or hostname.endswith("." + domain) for domain in TRUSTED_DOMAINS
    )


@dataclass
class WebSearchResult:
    title: str
    url: str
    content: str
    score: float = 0.0
    is_trusted: bool = False


def get_tavily_client(api_key: str | None = None) -> TavilyClient | None:
    key = api_key or TAVILY_API_KEY
    return TavilyClient(api_key=key) if key else None


def _timeout(deadline: float | None) -> float:
    remaining = deadline - time.monotonic() if deadline else 4.0
    if remaining <= 0.2:
        raise TimeoutError("Web search budget exhausted")
    return min(4.0, remaining)


def _results(items: list[dict], is_caat: bool) -> list[WebSearchResult]:
    results, seen = [], set()
    for item in items:
        url = item.get("url", "").strip()
        content = (item.get("content") or item.get("raw_content") or "").strip()
        if not valid_web_url(url) or not content or url.rstrip("/") in seen:
            continue
        host = get_domain(url)
        if is_caat and not (host == "caat.or.th" or host.endswith(".caat.or.th")):
            continue
        seen.add(url.rstrip("/"))
        results.append(WebSearchResult(str(item.get("title", "แหล่งข้อมูลเว็บไซต์")), url, content,
            float(item.get("score") or 0), is_trusted_domain(url)))
    return sorted(results, key=lambda r: (r.is_trusted, r.score), reverse=True)


def search_web_fallback(query: str, is_caat_topic: bool = False, max_results: int = 4,
                        tavily_client: TavilyClient | None = None, deadline: float | None = None) -> list[WebSearchResult]:
    if max_results < 1:
        return []
    client = tavily_client or get_tavily_client()
    if not client:
        return []
    extracted = []
    if is_caat_topic:
        try:
            response = client.extract(urls=[CAAT_PORTAL_INFOGRAPHIC_URL], query=query,
                chunks_per_source=3, extract_depth="basic", format="text", timeout=_timeout(deadline))
            extracted = _results(response.get("results", []), True)
        except Exception as exc:
            logger.warning("CAAT extraction unavailable (%s)", type(exc).__name__)
    try:
        kwargs = dict(query=query, search_depth="basic", max_results=max_results, timeout=_timeout(deadline),
                      include_domains=["uasportal.caat.or.th", "caat.or.th"] if is_caat_topic else PREFERRED_DOMAINS,
                      include_domains_mode="restrict" if is_caat_topic else "prefer")
        response = client.search(**kwargs)
        found = _results(response.get("results", []), is_caat_topic)
    except Exception as exc:
        logger.warning("Web search unavailable (%s)", type(exc).__name__)
        found = []
    # Query-specific pages first; the infographic is still a real fetched source.
    seen, combined = set(), []
    for result in found + extracted:
        if result.url not in seen:
            seen.add(result.url)
            combined.append(result)
    return combined[:max_results]


def web_evidence(results: list[WebSearchResult]) -> list[Evidence]:
    evidence = []
    for result in results:
        if not valid_web_url(result.url) or not result.content.strip():
            continue
        # Retain complete paragraphs/lines rather than chopping words or table rows.
        chunks, lines, length = [], [], 0
        for line in result.content.splitlines():
            if length + len(line) + 1 > 4500 and lines:
                chunks.append("\n".join(lines))
                lines, length = [], 0
            if len(line) > 4500:
                # Huge unstructured blocks cannot be safely clipped into evidence.
                continue
            lines.append(line)
            length += len(line) + 1
        if lines:
            chunks.append("\n".join(lines))
        for chunk in chunks[:3]:
            if chunk.strip():
                evidence.append(Evidence(f"W{len(evidence) + 1}", chunk.strip(), url=result.url, title=result.title))
    return evidence


def format_web_context(results: list[WebSearchResult]) -> str:
    return "\n\n".join(f"[{e.id}]\nURL: {e.url}\nเนื้อหา:\n{e.content}" for e in web_evidence(results))
