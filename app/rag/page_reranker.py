"""Bounded domain/crop alignment and MMR without page-specific score rules."""
from __future__ import annotations

from collections.abc import Callable
import re

from app.rag.source_policy import SUPPORTED_CROPS


def split_query_aspects(query: str) -> list[str]:
    """Split substantive clauses only; 'เกิดจากอะไรและแก้อย่างไร' stays intact."""
    parts = [p.strip() for p in re.split(r"และ|พร้อมทั้ง|[;；]", query) if p.strip()]
    if not 2 <= len(parts) <= 3:
        return []
    filler = r"เท่าไร|อย่างไร|อะไร|แค่ไหน|หรือไม่|ควร|ต้อง|ช่วย|บ้าง|ได้|เป็น|มี|\s"
    return parts if all(len(re.sub(filler, "", p)) >= 8 for p in parts) else []


def select_diverse_pages(query: str, pages: list[dict], top_k: int,
                         tokenize: Callable[[str], list[str]], query_topic: str) -> list[dict]:
    if not pages or top_k < 1:
        return []
    crops = [c for c in SUPPORTED_CROPS if c in query and not any(c in other and other in query for other in SUPPORTED_CROPS if c != other)]
    maximum = max(p["rrf_score"] for p in pages) or 1
    tokens = {id(p): set(tokenize(p["content"])) for p in pages}
    for page in pages:
        content = page["content"]
        crop_match = sum(c in content for c in crops) / len(crops) if crops else 0
        topic_match = int(query_topic != "general" and page["topic"] == query_topic)
        # Preserve the measured RRF ranking as the dominant relevance signal.
        page["rerank_score"] = page["rrf_score"] / maximum + .05 * (crop_match + topic_match)
    selected, remaining = [], list(pages)
    # Preserve one strong lexical page for each substantive subquestion before
    # filling by MMR. This adds no embedding/model request and prevents a long
    # clause from overwhelming another clause in the combined query vector.
    aspects = sorted({a for p in pages for a in p.get("aspect_ranks", {})})
    for aspect in aspects:
        if len(selected) >= top_k:
            break
        eligible = [p for p in pages if aspect in p.get("aspect_ranks", {})]
        best = min(eligible, key=lambda p: (p["aspect_ranks"][aspect], -p["rerank_score"]))
        if best not in selected:
            selected.append(best)
            remaining.remove(best)
    while remaining and len(selected) < top_k:
        def utility(page):
            current = tokens[id(page)]
            redundancy = max((len(current & tokens[id(other)]) / max(1, len(current | tokens[id(other)]))
                              for other in selected), default=0)
            return page["rerank_score"] - .1 * redundancy
        best = max(remaining, key=utility)
        selected.append(best)
        remaining.remove(best)
    return selected
