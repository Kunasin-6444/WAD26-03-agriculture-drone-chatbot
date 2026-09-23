# Current State

## Completed

### PDF Vision & Selective Ingestion

Working and Production-Ready.

File:

`app/ingestion/vision_extractor.py`

Features:
- Selective vision heuristic: detects content images (>150x150), complex vector drawings (>10), sparse text with graphics, and corrupted fonts.
- Pure text pages bypass Gemini Vision and use native PyMuPDF extraction (0 quota, 100x faster).
- Local disk caching at `cache/vision/<doc_name>/page_<n>.json` prevents redundant API calls.
- HTTP 429 (`RESOURCE_EXHAUSTED`) backoff retry handling.
- Structured output uses Pydantic (`VisionPageResult`, `VisualElement`).
- CLI support for `--force-vision` in `scripts/ingest_pdf.py`.

---

## Knowledge Unit

Working.

File:

`app/ingestion/models.py`

`KnowledgeUnit` contains:

- id
- document_id
- source_file
- page_number
- source_type
- content
- extracted_text
- visual_description
- title
- metadata

---

## Knowledge Builder

Working.

File:

`app/ingestion/knowledge_builder.py`

Currently combines:

- PDF text
- native PDF tables
- Vision output

---

## Chunking

Working.

File:

`app/rag/chunking.py`

Current baseline:

- chunk size: 800 characters
- overlap: 120 characters

This is an MVP baseline and has not yet been optimized.

---

## Embedding

Working.

File:

`app/rag/embedding.py`

Model:

`gemini-embedding-2`

Dimension:

3072

Retry behavior exists for temporary server errors.

---

## Chroma

Working.

File:

`app/rag/vector_store.py`

Persistent collection:

`drone_knowledge`

---

## Vector Store & Ingestion Status

Working and Multi-document.

File:

`app/rag/vector_store.py`

Persistent collection:

`drone_knowledge`

Current Knowledge Base Ingestion:
- Cleaned and re-ingested from scratch.
- `UAV06 โดรนฉีดพ่นเพื่อการเกษตร.pdf` (23 pages): 118 KUs, 126 Chunks
- `UAV07 หัวฉีดและการเลือกใช้หัวฉีด.pdf` (27 pages): 106 KUs, 107 Chunks (Pages 20–27 fully repaired and multimodal)
- **Total active chunks in ChromaDB: 233 chunks**
- ID deduplication safeguard in `add_chunks()` and `make_unit_id(..., source_origin=...)` prevents `DuplicateIDError`.
- Disk cache: `cache/vision/` stores all 50 analyzed pages for instant re-runs without API quota.

---

## Retrieval & Grounding

Working across multiple documents.

Files:

`app/rag/rag_service.py` & `app/services/ai_service.py`

Features:
- `retrieve_context(query, n_results=15)` with format `[แหล่งข้อมูล x] ไฟล์: ... หน้า: ... ประเภท: ... เนื้อหา: ...`
- Grounded LLM answering using KKU GenAI OpenAI-compatible API (`gemini-3.5-flash-lite`, base_url="https://gen.ai.kku.ac.th/api/v1")
- Strict grounding with zero hallucination enforcement (abstains when query is out of context or absent)
- Source and page citations in answers: `(แหล่งอ้างอิง: [ชื่อไฟล์], หน้า [เลขหน้า])`
- Multi-document cross-referencing verified (can cite UAV06 and UAV07 simultaneously)
- Connected end-to-end through `ask_ai` to LINE Webhook

---

## Automated Test Suite

Working and Verified.

Total tests: **22 automated unit/integration tests (100% PASS)**:
- `tests/test_chunking_unit.py` (4 tests)
- `tests/test_knowledge_builder_unit.py` (4 tests)
- `tests/test_rag_pipeline.py` (2 tests)
- `tests/test_retrieval_benchmark.py` (3 benchmark tests)
- `tests/test_grounded_answer_integration.py` (1 integration test)
- `tests/test_vision_selective_unit.py` (8 edge case tests)

---

# Current Next Priority

1. Phase 2 — CRAG relevance grader (`app/rag/crag_grader.py`)
2. Phase 2 — Tavily web fallback (`app/rag/web_fallback.py`)
3. Phase 2 — Fallback abstain path & source citations (URLs)
4. Phase 3 — Ingest remaining documents (`UAV08` - `UAV12`, CAAT PDF) using selective vision & cache
5. Phase 3 — LINE timeout & error handling
6. Phase 4 — Final verification with 20-30 real Thai questions