"""Bounded domain/crop alignment and MMR without page-specific score rules."""
from __future__ import annotations

from collections.abc import Callable
import os
import re

from app.rag.source_policy import SUPPORTED_CROPS


def split_query_aspects(query: str) -> list[str]:
    """Split substantive clauses only; 'เกิดจากอะไรและแก้อย่างไร' stays intact."""
    parts = [p.strip() for p in re.split(r"และ|พร้อมทั้ง|[;；]", query) if p.strip()]
    if not 2 <= len(parts) <= 3:
        return []
    filler = r"เท่าไร|อย่างไร|อะไร|แค่ไหน|หรือไม่|ควร|ต้อง|ช่วย|บ้าง|ได้|เป็น|มี|\s"
    return parts if all(len(re.sub(filler, "", p)) >= 8 for p in parts) else []


# Question words and fillers; what is left of the question is its subject ("เพลี้ยแป้งมันสำปะหลัง", "AR-30L/6").
_QUESTION_WORDS = re.compile(r"อะไร|เท่าไร|เท่าไหร่|อย่างไร|ยังไง|ได้ไหม|ไหม|มั้ย|หรือไม่|บ้าง|ควร|ต้อง|ใช้|กี่"
                             r"|เมื่อไร|เมื่อไหร่|ที่ไหน|ทำไม|คือ|ช่วย|หน่อย|ครับ|ค่ะ|คะ|ในตาราง|ตาราง")
# Added to the rerank score of a page holding a rare verbatim piece of the question (0 disables).
# Dev 2026-10-20: pages complete 40 -> 43 of 45 at 0.2 and 0.35, no case worse.
PHRASE_WEIGHT = float(os.getenv("RETRIEVER_PHRASE_WEIGHT", "0.2"))


def _flat(text: str) -> str:
    return re.sub(r"\s+", "", (text or "").replace("ํา", "ำ")).casefold()


def rare_phrase_scores(query: str, pages: list[dict], min_length: int = 5, max_pages: int = 3) -> list[float]:
    """Per page, 0..1: the longest verbatim piece of the question it holds that at most `max_pages`
    candidates hold (12+ characters = 1). A pest, disease or model name is rare among the candidates;
    "สาร" or "อัตรา" is not. The 2026-10-20 misses: the only page naming "เพลี้ยแป้งมันสำปะหลัง" ranked 10th
    behind pages about "สาร" that never named it."""
    parts = [part for part in _QUESTION_WORDS.split(_flat(query)) if len(part) >= min_length]
    spans = {part[i:j] for part in parts for i in range(len(part)) for j in range(i + min_length, len(part) + 1)}
    contents = [_flat(page.get("content", "")) for page in pages]
    rare = [span for span in spans if sum(span in content for content in contents) <= max_pages]
    return [min(1.0, max((len(span) for span in rare if span in content), default=0) / 12) for content in contents]


def select_diverse_pages(query: str, pages: list[dict], top_k: int,
                         tokenize: Callable[[str], list[str]], query_topic: str) -> list[dict]:
    if not pages or top_k < 1:
        return []
    crops = [c for c in SUPPORTED_CROPS if c in query and not any(c in other and other in query for other in SUPPORTED_CROPS if c != other)]
    maximum = max(p["rrf_score"] for p in pages) or 1
    tokens = {id(p): set(tokenize(p["content"])) for p in pages}
    phrases = rare_phrase_scores(query, pages) if PHRASE_WEIGHT else [0.0] * len(pages)
    for page, phrase in zip(pages, phrases):
        content = page["content"]
        crop_match = sum(c in content for c in crops) / len(crops) if crops else 0
        topic_match = int(query_topic != "general" and page["topic"] == query_topic)
        # Preserve the measured RRF ranking as the dominant relevance signal.
        page["rerank_score"] = page["rrf_score"] / maximum + .05 * (crop_match + topic_match) + PHRASE_WEIGHT * phrase
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


def table_rows(metadatas: list[dict] | None) -> set[tuple[str, int, int]]:
    """(table_id, first row, last row) of each table chunk on a page."""
    rows = set()
    for metadata in metadatas or []:
        metadata = metadata or {}
        table, first, last = metadata.get("table_id"), str(metadata.get("row_start") or ""), str(metadata.get("row_end") or "")
        if table and first.isdigit() and last.isdigit():
            rows.add((str(table), int(first), int(last)))
    return rows


def add_table_continuations(selected: list[dict], pages: list[dict], limit: int) -> list[dict]:
    """Append retrieved-but-unselected pages that continue a table already selected.

    A table split over pages is ranked page by page, so a question that filters its rows ("อากาศร้อน
    แห้งแล้งเสี่ยงโรคอะไร") got the first row's page but not the next row on the following page
    (2026-10-20: rank 14 of the 50 candidates). Only adjacent row ranges of the same table count, the
    page must already be a retrieval candidate, and at most `limit` pages are added after the top-k.
    """
    if limit < 1:
        return selected
    chosen = {id(page) for page in selected}
    own = {(table, first, last) for page in selected for table, first, last in page.get("table_rows", ())}
    continuing = [page for page in pages if id(page) not in chosen and any(
        table == other and (first == other_last + 1 or last == other_first - 1)
        for table, first, last in page.get("table_rows", ()) for other, other_first, other_last in own)]
    continuing.sort(key=lambda page: page.get("rerank_score", page.get("rrf_score", 0)), reverse=True)
    return selected + continuing[:limit]
