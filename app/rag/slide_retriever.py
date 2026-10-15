"""
6-Step Slide Retrieval Pipeline
================================
Professional Multimodal RAG Retrieval Architecture for Agriculture Drone Slides:

1. Query Normalization: Normalizes query terms, removes keyboard typos, identifies domain entities (e.g. crop, stage).
2. Hybrid Retrieval: Combines dense vector semantic search (Gemini Embedding) and BM25 exact-term scoring.
3. Visual & Structured Expansion: Prioritizes visual table and diagram transcriptions over high-level summaries.
4. Merge & Deduplicate: Page-level consolidation to prevent context bloat and redundant chunk concatenation.
5. Reranking (Domain & Crop Precision Filter + MMR Diversity): Downranks irrelevant crops (e.g. corn/peanut when asking sugarcane)
   and ensures multi-aspect balance (timeline + chemical + equipment).
6. Context Assembly: Formats evidence blocks cleanly with source file and page metadata.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from app.rag.embedding import embed_text
from app.rag.query_normalizer import normalize_query
from app.rag.vector_store import collection
from app.rag.source_policy import is_excluded_document

logger = logging.getLogger(__name__)

# Crops known in the knowledge base
SUPPORTED_CROPS = ["อ้อย", "ข้าว", "ข้าวโพด", "ถั่วเหลือง", "ถั่วลิสง", "มันสำปะหลัง"]


def tokenize_thai_terms(text: str) -> list[str]:
    """Tokenize Thai and alphanumeric text into searchable terms for BM25 using hybrid n-grams."""
    tokens = []
    # Alphanumerics (e.g. gsd, rgb, overlap, dsm, gcp, fine, ultra-coarse, 1600, 500)
    tokens.extend(re.findall(r"[a-zA-Z0-9_\.]+", text.lower()))

    # Domain keywords
    domain_terms = [
        "โดรน", "สำรวจ", "ฉีดพ่น", "หัวฉีด", "พัดส้ม", "พัดฟ้า", "พัดน้ำเงิน", "พัดแดง", "พัดเหลือง",
        "คุณภาพ", "ภาพถ่าย", "การบิน", "ตั้งค่า", "วัชพืช", "อ้อย", "แผนการบิน", "เงื่อนไขการบิน",
        "ความละเอียด", "สเปก", "อัตราการไหล", "ขนาดละออง", "กล้อง", "ความสูง", "ความเร็ว",
        "แปลงเกษตร", "overlap", "gsd", "rgb", "dsm", "gcp", "ส้ม", "น้ำเงิน", "ฟ้า",
        "สารเคมี", "เพนดิเมทาลิน", "อาลาคลอร์", "แอตทราซีน", "ไกลโฟเซต", "แตกกอ",
    ]
    t_lower = text.lower()
    for dt in domain_terms:
        if dt in t_lower:
            tokens.append(dt)

    # Thai character 3-grams & 2-grams for continuous Thai sub-sequences
    thai_chunks = re.findall(r"[\u0E00-\u0E7F]+", t_lower)
    for chunk in thai_chunks:
        if len(chunk) <= 3:
            tokens.append(chunk)
        else:
            for i in range(len(chunk) - 2):
                tokens.append(chunk[i : i + 3])
            for i in range(len(chunk) - 1):
                tokens.append(chunk[i : i + 2])
    return [t for t in tokens if len(t) > 1]


def compute_bm25_score(
    query_tokens: list[str],
    doc_tokens: list[str],
    avg_dl: float,
    k1: float = 1.5,
    b: float = 0.75,
) -> float:
    """Compute standard BM25 score for a document given query tokens."""
    if not doc_tokens or not query_tokens:
        return 0.0
    doc_len = len(doc_tokens)
    tf_map: dict[str, int] = {}
    for t in doc_tokens:
        tf_map[t] = tf_map.get(t, 0) + 1

    score = 0.0
    for qt in query_tokens:
        if qt in tf_map:
            tf = tf_map[qt]
            numerator = tf * (k1 + 1.0)
            denominator = tf + k1 * (1.0 - b + b * (doc_len / (avg_dl or 1.0)))
            score += numerator / denominator
    return score


def classify_slide_topic(content: str) -> str:
    """Classify slide content into sub-domain topic to ensure MMR diversity."""
    c_lower = content.lower()
    if any(
        k in c_lower
        for k in [
            "gsd",
            "overlap",
            "ความละเอียด",
            "แผนการบิน",
            "เงื่อนไขการบิน",
            "สำรวจ",
            "ภาพถ่ายทางอากาศ",
            "stitching",
            "gcp",
            "ground sampling",
            "rgb camera",
        ]
    ):
        return "survey"
    if any(
        k in c_lower
        for k in [
            "สารเคมี",
            "สารก าจัดวัชพืช",
            "สารกำจัดวัชพืช",
            "alachlor",
            "pendimethalin",
            "atrazine",
            "ametryn",
            "2,4-d",
            "ยาคุม",
            "ยาฆ่า",
        ]
    ):
        return "herbicides"
    if any(
        k in c_lower
        for k in [
            "timeline",
            "ไทม์ไลน์",
            "ระยะเวลา",
            "วันหลังปลูก",
            "ระยะแตกกอ",
            "ระยะย่างปล้อง",
            "สูญเสียผลผลิต",
            "ฤดูกาล",
            "ช่วงเวลา",
        ]
    ):
        return "timeline"
    if any(
        k in c_lower
        for k in [
            "หัวฉีด",
            "พัดส้ม",
            "พัดฟ้า",
            "พัดน้ำเงิน",
            "พัดเหลือง",
            "พัดแดง",
            "อัตราการไหล",
            "ขนาดละออง",
            "ไมครอน",
        ]
    ):
        return "nozzles"
    return "general"


def search_slides_pipeline(
    query: str,
    top_k: int = 5,
) -> dict[str, Any]:
    """
    Execute the 6-step slide retrieval pipeline and return assembled context and metadata.
    """
    # -----------------------------------------------------------------
    # Step 1: Query Normalization
    # -----------------------------------------------------------------
    norm_query = normalize_query(query)
    q_tokens = tokenize_thai_terms(norm_query)

    # Detect crop focus if mentioned in query
    crop_matches = [c for c in sorted(SUPPORTED_CROPS, key=len, reverse=True) if c in norm_query]
    target_crop = crop_matches[0] if crop_matches else None

    # -----------------------------------------------------------------
    # Step 2: Hybrid Retrieval (Dense Embeddings + BM25 Scoring)
    # -----------------------------------------------------------------
    if not norm_query or top_k < 1:
        return {"context": "", "top_pages": [], "total_chars": 0}
    q_emb = embed_text(norm_query, max_retries=1, timeout_seconds=3.0)
    chroma_res = collection.query(
        query_embeddings=[q_emb],
        n_results=50,
        include=["metadatas", "documents", "distances"],
    )

    raw_docs = chroma_res.get("documents", [[]])[0]
    raw_metas = chroma_res.get("metadatas", [[]])[0]
    raw_dists = chroma_res.get("distances", [[]])[0]

    if not raw_docs:
        return {"context": "", "top_pages": [], "total_chars": 0}

    avg_dl = sum(len(tokenize_thai_terms(d)) for d in raw_docs) / (len(raw_docs) or 1)

    candidates = []
    for idx, (doc, meta, dist) in enumerate(zip(raw_docs, raw_metas, raw_dists)):
        meta = meta or {}
        if not doc or is_excluded_document(meta.get("source_file", "")):
            continue
        doc_tokens = tokenize_thai_terms(doc)
        bm25 = compute_bm25_score(q_tokens, doc_tokens, avg_dl)
        dense_sim = 1.0 / (1.0 + dist)

        candidates.append(
            {
                "doc": doc,
                "meta": meta,
                "dense_rank": idx + 1,
                "dense_sim": dense_sim,
                "bm25_score": bm25,
                "source_file": meta.get("source_file", "unknown"),
                "page_number": str(meta.get("page_number", "unknown")),
                "source_type": meta.get("source_type", "text"),
            }
        )

    # Calculate BM25 ranks
    candidates_by_bm25 = sorted(candidates, key=lambda x: x["bm25_score"], reverse=True)
    for b_rank, cand in enumerate(candidates_by_bm25):
        cand["bm25_rank"] = b_rank + 1

    # -----------------------------------------------------------------
    # Step 3: Visual & Structured Expansion + Step 4: Merge and Deduplicate
    # -----------------------------------------------------------------
    pages_map: dict[tuple[str, str], dict[str, Any]] = {}

    # One metadata query expands all candidate pages, replacing up to 50 round trips.
    page_keys = list(dict.fromkeys((c["source_file"], c["page_number"]) for c in candidates
        if c["source_file"] != "unknown" and c["page_number"].isdigit()))
    expanded: dict[tuple[str, str], dict] = {}
    if page_keys:
        filters = [{"$and": [{"source_file": file}, {"page_number": page}]} for file, page in page_keys]
        try:
            all_pages = collection.get(where=filters[0] if len(filters) == 1 else {"$or": filters},
                include=["metadatas", "documents"])
            for metadata, document in zip(all_pages.get("metadatas") or [], all_pages.get("documents") or []):
                metadata = metadata or {}
                key = (metadata.get("source_file", ""), str(metadata.get("page_number", "")))
                group = expanded.setdefault(key, {"metadatas": [], "documents": []})
                group["metadatas"].append(metadata)
                group["documents"].append(document)
        except Exception as exc:
            logger.warning("Page expansion unavailable (%s)", type(exc).__name__)

    for cand in candidates:
        if cand["source_file"] == "unknown" or not cand["page_number"]:
            continue
        page_key = (cand["source_file"], cand["page_number"])
        # Reciprocal Rank Fusion (RRF)
        rrf_score = (0.6 / (60.0 + cand["dense_rank"])) + (0.4 / (60.0 + cand["bm25_rank"]))

        if page_key not in pages_map:
            page_chunks = expanded.get(page_key, {"metadatas": [cand["meta"]], "documents": [cand["doc"]]})

            # Collect all distinct structured tables and diagrams for this page
            page_structured_docs: list[str] = []
            seen_texts: set[str] = set()

            # First add all tables and diagrams (the highest fidelity facts)
            for p_meta, p_doc in zip(
                page_chunks.get("metadatas") or [], page_chunks.get("documents") or []
            ):
                p_meta = p_meta or {}
                p_type = p_meta.get("source_type", "")
                norm_doc = (p_doc or "").strip()
                if p_type in ("table", "diagram", "chart") and norm_doc and norm_doc not in seen_texts:
                    seen_texts.add(norm_doc)
                    page_structured_docs.append(norm_doc)

            # Text carries units, operating conditions and caveats even on table pages.
            for p_meta, p_doc in zip(page_chunks.get("metadatas") or [], page_chunks.get("documents") or []):
                p_type = (p_meta or {}).get("source_type", "")
                norm_doc = (p_doc or "").strip()
                if p_type in ("text", "image", "mixed") and norm_doc and norm_doc not in seen_texts:
                    seen_texts.add(norm_doc)
                    page_structured_docs.append(norm_doc)

            if not page_structured_docs:
                page_structured_docs.append(cand["doc"])

            combined_content = "\n\n---\n\n".join(page_structured_docs)

            pages_map[page_key] = {
                "source_file": cand["source_file"],
                "page_number": cand["page_number"],
                "source_type": "table" if any((p or {}).get("source_type") == "table" for p in (page_chunks.get("metadatas") or [])) else cand["source_type"],
                "content": combined_content,
                "rrf_score": rrf_score,
                "topic": classify_slide_topic(combined_content),
                "best_meta": cand["meta"],
            }
        else:
            pages_map[page_key]["rrf_score"] += rrf_score * 0.5

    deduped_pages = list(pages_map.values())

    # -----------------------------------------------------------------
    # Step 5: Domain & Crop Reranking (Precision Filter + MMR Diversity)
    # -----------------------------------------------------------------
    for page in deduped_pages:
        score = page["rrf_score"]
        content = page["content"]

        # Crop alignment: boost matching crop, heavily penalize conflicting crops
        if target_crop:
            if target_crop in content:
                score *= 2.0
            other_crops = [
                c
                for c in SUPPORTED_CROPS
                if c != target_crop and c in content and target_crop not in content
            ]
            if other_crops:
                score *= 0.05

        # Timeline alignment: for queries specifying crop age (e.g. 2 เดือน)
        if any(term in norm_query for term in ["2 เดือน", "60 วัน", "แตกกอ"]):
            if any(term in content for term in ["1-4 เดือน", "แตกกอ", "30-120 วัน", "2 เดือน", "60 วัน"]):
                score *= 2.5

        # Herbicide & weed spraying alignment:
        is_spraying_or_weed_query = any(
            term in norm_query
            for term in ["ฉีด", "พ่น", "วัชพืช", "กำจัดวัชพืช", "ยาคุม", "ยาฆ่า", "สารเคมี", "หญ้า"]
        )
        if is_spraying_or_weed_query:
            # Boost official chemical recommendation tables (e.g. UAV06 p.18)
            has_chemical_table = any(
                k in content
                for k in ["พ่นหลังวัชพืชงอก", "พ่นก่อนวัชพืชงอก", "สารกำจัดวัชพืช", "ใบแคบและกว้าง", "วัชพืชที่ควบคุมได้", "อัตราการใช้"]
            )
            if has_chemical_table:
                score *= 3.5
                # If query asks about standing crop (e.g. 2 เดือน / 60 วัน / แตกกอ), boost post-emergence specifically
                if any(k in norm_query for k in ["2 เดือน", "60 วัน", "หลังงอก", "แตกกอ"]) and "พ่นหลังวัชพืชงอก" in content:
                    score *= 2.0

            # Also boost operational flight parameters for drone spraying (e.g. altitude, speed, droplet density)
            has_flight_specs = any(
                k in content
                for k in ["ความสูง", "ความเร็ว", "m/s", "1.5", "2.0", "รอบการทำงาน", "1600", "การพ่นละอองของโดรน"]
            ) and any(k in content for k in ["โดรน", "พ่น", "ฉีด"])
            if has_flight_specs:
                score *= 1.8

        # Nozzle alignment: for queries about nozzles / droplet size / flow rate
        is_nozzle_query = any(
            term in norm_query
            for term in ["หัวฉีด", "อัตราการไหล", "ละออง", "พัดส้ม", "พัดฟ้า", "พัดน้ำเงิน"]
        )
        if is_nozzle_query and page["topic"] == "nozzles":
            score *= 2.5

        # Survey alignment: for queries about aerial survey, GSD, overlap, altitude, flight conditions
        is_survey_query = any(
            term in norm_query
            for term in [
                "สำรวจ", "ภาพถ่าย", "gsd", "overlap", "ความละเอียด",
                "แผนการบิน", "เงื่อนไขการบิน", "ตั้งค่าการบิน", "คุณภาพของภาพถ่าย"
            ]
        )
        if is_survey_query:
            if page["topic"] == "survey":
                score *= 2.5
            if any(term in content.lower() for term in ["gsd", "overlap", "คุณภาพของภาพถ่าย", "speed", "ความสูง"]):
                score *= 2.0

        page["rerank_score"] = score

    reranked = sorted(deduped_pages, key=lambda x: x["rerank_score"], reverse=True)

    # Topic-diverse selection (MMR): preserve breadth while honoring query focus
    selected = []
    seen_topics: dict[str, int] = {}
    is_nozzle_query = any(
        term in norm_query
        for term in ["หัวฉีด", "อัตราการไหล", "ละออง", "พัดส้ม", "พัดฟ้า", "พัดน้ำเงิน"]
    )
    is_survey_query = any(
        term in norm_query
        for term in [
            "สำรวจ", "ภาพถ่าย", "gsd", "overlap", "ความละเอียด",
            "แผนการบิน", "เงื่อนไขการบิน", "ตั้งค่าการบิน", "คุณภาพของภาพถ่าย"
        ]
    )
    is_spraying_query = any(
        term in norm_query
        for term in ["ฉีด", "พ่น", "วัชพืช", "กำจัดวัชพืช", "ยาคุม", "ยาฆ่า", "สารเคมี", "หญ้า"]
    )

    for p in reranked:
        topic = p["topic"]
        max_per_topic = (
            top_k
            if (is_nozzle_query and topic == "nozzles")
            or (is_survey_query and topic == "survey")
            else (4 if (is_spraying_query and topic == "herbicides") else 2)
        )
        if seen_topics.get(topic, 0) < max_per_topic:
            selected.append(p)
            seen_topics[topic] = seen_topics.get(topic, 0) + 1
        if len(selected) >= top_k:
            break

    if len(selected) < top_k:
        for p in reranked:
            if p not in selected:
                selected.append(p)
            if len(selected) >= top_k:
                break

    # -----------------------------------------------------------------
    # Step 6: Context Assembly
    # -----------------------------------------------------------------
    context_blocks = []
    for idx, page in enumerate(selected):
        context_blocks.append(
            f"[แหล่งข้อมูล {idx + 1}]\n"
            f"ไฟล์: {page['source_file']}\n"
            f"หน้า: {page['page_number']}\n"
            f"ประเภท: {page['source_type']}\n"
            f"เนื้อหา:\n"
            f"{page['content']}"
        )

    final_context = "\n\n".join(context_blocks)
    return {
        "context": final_context,
        "top_pages": selected,
        "total_chars": len(final_context),
    }
