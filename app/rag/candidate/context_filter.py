from __future__ import annotations

import re
from dataclasses import asdict
from typing import Sequence

from app.rag.evidence import Evidence


# Question words, particles, and grammatical glue in Thai
_QUESTION_FILLERS = re.compile(
    r"อะไร|เท่าไร|เท่าไหร่|อย่างไร|ยังไง|ได้ไหม|ไหม|มั้ย|หรือไม่|บ้าง|ควร|ต้อง|ใช้|กี่|"
    r"เมื่อไร|เมื่อไหร่|ที่ไหน|ทำไม|คือ|ช่วย|หน่อย|ครับ|ค่ะ|คะ|ใน|ของ|ที่|กับ|และ|หรือ|มี|เป็น|การ|\s+"
)

# Irrelevant table / topic markers that pollute retrieval when unrequested
DISINTEREST_PATTERNS = [
    (re.compile(r"Bonsucro|น้ำตาล.*บราซิล|tangible benefits", re.IGNORECASE), "bonsucro_certification"),
    (re.compile(r"ราคา RTF โดยประมาณ|แพ็กเกจพร้อมบิน|ตัวลำ, รีโมท, แบตเตอรี่ x1ชุด", re.IGNORECASE), "rtf_pricing_table"),
]


def extract_keywords(query: str) -> list[str]:
    """Extract substantive terms and search spans from Thai and alphanumeric queries.

    Handles continuous Thai text without space boundaries by removing common question
    particles and extracting substantive clause spans and n-grams.
    """
    clean_query = query.strip().lower()
    terms: list[str] = []

    # 1. Alphanumerics (e.g. gsd, rgb, taro, t10, 250, ml)
    alpha = [w.lower() for w in re.findall(r"[a-zA-Z0-9_\.]+", clean_query) if len(w) >= 2]
    terms.extend(alpha)

    # 2. Split Thai segments by question particles and punctuation
    raw_clauses = [c.strip() for c in _QUESTION_FILLERS.split(clean_query) if c.strip()]
    for clause in raw_clauses:
        # Strip non-alphanumeric and non-Thai
        sub = re.sub(r"[^\w\u0e00-\u0e7f]", "", clause)
        if len(sub) >= 2:
            terms.append(sub)
            # If clause is long, add 3-4 character sub-spans to catch compound terms
            if len(sub) >= 5:
                for length in (3, 4):
                    for i in range(len(sub) - length + 1):
                        span = sub[i : i + length]
                        if span not in terms:
                            terms.append(span)

    # Add domain loanword equivalents for standard drone components
    common_loanwords = {
        "แบต": ["battery", "แบตเตอรี่"],
        "แบตเตอรี่": ["battery", "แบต"],
        "ปั๊ม": ["pump"],
        "โดรน": ["uav", "drone"],
        "มอเตอร์": ["motor"],
        "ใบพัด": ["propeller"],
    }
    for k, eq_list in common_loanwords.items():
        if k in clean_query:
            terms.extend(eq_list)

    # Deduplicate preserving order
    return list(dict.fromkeys(terms))


def detect_operational_scope(content: str, source_file: str) -> str:
    """Identify if the evidence is specific to a phase or drone category."""
    scopes: list[str] = []
    lower_content = content.lower()
    lower_file = source_file.lower()

    if "โดรนสำรวจ" in lower_file or "โดรนสำรวจ" in lower_content or "taro" in lower_content:
        scopes.append("โดรนสำรวจ")
    elif "โดรนฉีดพ่น" in lower_file or "โดรนเกษตร" in lower_content or "ฉีดพ่น" in lower_content:
        scopes.append("โดรนเกษตร/ฉีดพ่น")

    if "ก่อนลงพื้นที่" in lower_content or "เตรียมอุปกรณ์" in lower_content or "ก่อนขึ้นบิน" in lower_content:
        scopes.append("ก่อนขึ้นบิน/ก่อนลงพื้นที่")
    if "ขณะบิน" in lower_content or "ระหว่างบิน" in lower_content:
        scopes.append("ขณะบิน")
    if "ซ่อมบำรุง" in lower_content or "รอบชาร์จ" in lower_content or "เก็บในที่" in lower_content:
        scopes.append("การบำรุงรักษา/จัดเก็บ")

    return " | ".join(scopes) if scopes else "ทั่วไป"


def score_evidence(query: str, evidence: Evidence) -> tuple[float, list[str]]:
    """Score evidence chunk relevance to query and track reason."""
    notes: list[str] = []
    keywords = extract_keywords(query)
    content = evidence.content.lower()
    title = (evidence.title or "").lower()
    filename = (evidence.source_file or "").lower()
    full_text = f"{title} {filename} {content}"

    score = 0.0

    # 1. Keyword and substantive span matching
    matched_terms = []
    for kw in keywords:
        if kw in full_text:
            matched_terms.append(kw)
            if len(kw) >= 5:
                score += 3.0
            elif len(kw) >= 3:
                score += 1.5
            else:
                score += 0.5

            # Extra weight if keyword is in the title or filename
            if kw in title or kw in filename:
                score += 2.0

    notes.append(f"matched={len(matched_terms)}/{len(keywords)}")

    # 2. Specific intent checks
    flight_terms = ["ห้ามบิน", "บิน", "ความสูง", "ความเร็ว", "ระยะ", "ลม", "ฝน"]
    query_asks_flight = any(term in query for term in flight_terms)
    if query_asks_flight:
        if any(term in content for term in ["ห้ามบิน", "ขณะบิน", "ก่อนขึ้นบิน", "ไม่ควรบิน"]):
            score += 3.0
            notes.append("matches_flight_condition")

    # 3. Penalize unrequested bulk tables (pricing, Bonsucro, etc.)
    query_asks_price = any(term in query for term in ["ราคา", "ซื้อ", "งบ", "บาท", "ลงทุน", "rtf", "แพ็กเกจ"])
    query_asks_bonsucro = "bonsucro" in query.lower() or "บอนซูโคร" in query

    for pattern, name in DISINTEREST_PATTERNS:
        if pattern.search(content):
            if name == "rtf_pricing_table" and not query_asks_price:
                score -= 6.0
                notes.append(f"penalized_{name}")
            elif name == "bonsucro_certification" and not query_asks_bonsucro:
                score -= 6.0
                notes.append(f"penalized_{name}")

    # 4. Table comparison vs UI mockup scoring
    from app.rag.candidate.table_continuation import (
        is_comparative_or_table_query,
        parse_table_metadata,
    )
    if is_comparative_or_table_query(query):
        t_meta = parse_table_metadata(evidence)
        if t_meta.is_structured_table:
            score += 6.0
            notes.append("matches_table_comparison_scope")
        elif t_meta.is_ui_template:
            score -= 8.0
            notes.append("penalized_ui_mockup_in_table_comparison")

    return score, notes


def scope_and_filter_context(
    query: str,
    evidence_list: Sequence[Evidence],
    max_chunks: int = 8,
    min_score: float = -2.0,
) -> tuple[list[Evidence], list[dict], list[dict], list[str]]:
    """Select top relevant chunks, renumber IDs cleanly, and record pre/post selection.

    Returns:
        selected_evidence: Clean list of Evidence with IDs D1..Dn or W1..Wn
        pre_selection: Full dicts of original evidence
        post_selection: Full dicts of selected evidence with attached scope notes
        dropped_summaries: Explanations for chunks that were filtered out
    """
    pre_selection: list[dict] = [asdict(e) for e in evidence_list]
    if not evidence_list:
        return [], pre_selection, [], ["no_evidence_provided"]

    scored_items: list[tuple[float, Evidence, list[str]]] = []
    dropped_summaries: list[str] = []

    for idx, e in enumerate(evidence_list):
        score, notes = score_evidence(query, e)
        if e.url:
            score += 1.0
            notes.append("web_evidence_bonus")

        scored_items.append((score, e, notes))

    # Sort descending by score
    scored_items.sort(key=lambda item: item[0], reverse=True)

    selected: list[Evidence] = []
    post_selection: list[dict] = []
    doc_counter = 1
    web_counter = 1

    from app.rag.candidate.table_continuation import is_comparative_or_table_query

    is_table_query = is_comparative_or_table_query(query)
    seen_pages: set[tuple[str, str]] = set()
    seen_chunks: set[tuple[str, str, str]] = set()

    for score, item, notes in scored_items:
        # Drop explicitly penalized irrelevant chunks (e.g. unrequested pricing/bonsucro)
        if score < min_score:
            dropped_summaries.append(f"Dropped {item.source_file or item.url} (penalized score {score:.1f} < {min_score}): {'; '.join(notes)}")
            continue

        # Deduplicate: in table queries, preserve distinct row chunks on the same page;
        # in general prose/slide queries, deduplicate duplicate pages
        if is_table_query:
            chunk_key = (item.source_file or "", item.page_number or "", item.content.strip())
            if chunk_key in seen_chunks:
                dropped_summaries.append(f"Deduplicated duplicate chunk {item.source_file or item.url} p.{item.page_number}")
                continue
            seen_chunks.add(chunk_key)
        else:
            if item.source_file and item.page_number:
                page_key = (item.source_file, item.page_number)
                if page_key in seen_pages:
                    dropped_summaries.append(f"Deduplicated duplicate page {page_key[0]} p.{page_key[1]}")
                    continue
                seen_pages.add(page_key)

        if len(selected) >= max_chunks:
            dropped_summaries.append(f"Capped out after {max_chunks} chunks: dropped {item.source_file or item.url}")
            continue

        scope = detect_operational_scope(item.content, item.source_file)
        new_id = f"W{web_counter}" if item.url else f"D{doc_counter}"
        if item.url:
            web_counter += 1
        else:
            doc_counter += 1

        scoped_evidence = Evidence(
            id=new_id,
            content=item.content,
            source_file=item.source_file,
            page_number=item.page_number,
            url=item.url,
            title=item.title,
            page_from=item.page_from,
            page_end=item.page_end,
        )
        selected.append(scoped_evidence)

        entry = asdict(scoped_evidence)
        entry["operational_scope"] = scope
        entry["relevance_score"] = round(score, 2)
        entry["scoring_notes"] = notes
        post_selection.append(entry)

    # Fallback: if everything got penalized or filtered but evidence existed, keep top 1
    if not selected and evidence_list:
        top_score, top_item, top_notes = scored_items[0]
        new_id = "W1" if top_item.url else "D1"
        fallback_ev = Evidence(
            id=new_id,
            content=top_item.content,
            source_file=top_item.source_file,
            page_number=top_item.page_number,
            url=top_item.url,
            title=top_item.title,
            page_from=top_item.page_from,
            page_end=top_item.page_end,
        )
        selected.append(fallback_ev)
        entry = asdict(fallback_ev)
        entry["operational_scope"] = detect_operational_scope(top_item.content, top_item.source_file)
        entry["relevance_score"] = round(top_score, 2)
        post_selection.append(entry)

    return selected, pre_selection, post_selection, dropped_summaries
