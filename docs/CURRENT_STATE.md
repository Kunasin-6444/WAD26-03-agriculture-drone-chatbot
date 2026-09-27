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

## CRAG (Corrective RAG) & Fallback

Working and Production-Ready.

Files:
- `app/rag/crag_grader.py`: Evaluates retrieval context sufficiency (CORRECT / AMBIGUOUS / INCORRECT) and enforces R1 exception for Air Law / Air Space topics.
- `app/rag/web_fallback.py`: Tavily web search with official domain priority and designated CAAT UAS portal routing (`https://uasportal.caat.or.th/infographic`).
- `app/rag/crag_service.py`: Orchestrates full CRAG flow (KB -> Grade -> Grounded Answer OR Web Fallback OR Clear Abstain).
- `app/services/ai_service.py`: Integrated `ask_ai` through CRAG pipeline.

Features:
- R1 Rule Enforcement: Air Law and Air Space questions are redirected from PDF to CAAT UAS Portal.
- R4 Relevance Grading: Evaluates retrieved chunks before generation with calibrated criteria recognizing technical specs and flow rates as valid grounded evidence.
- R5 Web Fallback: Falls back to Tavily (basic search) and official government/university domains with URL citation and domain deduplication.
- R6 Clear Abstain: Explicitly abstains without guessing or hallucinating when evidence is absent.
- Latency & Resilience: Active KKU GenAI model pool (`gpt-5.6-luna`, `nova-2-lite-v1`, `llama-4-scout`) with 401 exhaustion caching and compact grader context (total query latency reduced from 30-50s down to 8-10s).

---

## LINE Webhook & Integration

Working and Production-Ready.

Files:
- `app/api/webhook.py`: FastAPI endpoint `/webhook` handling incoming LINE events.
- `app/services/line_service.py`: LINE Messaging API `reply_text` implementation.

Features:
- Webhook signature verification with `WebhookParser` (rejects invalid requests with HTTP 400).
- Automatic handling of LINE Developer Console webhook verification (empty events returning 200 OK).
- Dummy verification token filtering (`00000000000000000000000000000000` / `ffffffffffffffffffffffffffffffff`).
- Message length guard (truncates to 4950 characters to prevent LINE API 400 errors).
- Resilient error handling (returns friendly Thai message if internal processing fails without crashing the webhook).

---

## Final Evaluation Benchmark

Working and Verified.

Files:
- `scripts/evaluate_benchmark.py`: Comprehensive test harness running 28 real Thai user questions across 5 dimensions.
- `docs/FINAL_EVALUATION_REPORT.json`: Complete benchmark evaluation report with latency, source routing, and answer citations.
- `tests/test_benchmark_evaluation.py`: 6 regression tests covering all 5 behavioral dimensions.

Results Summary:
- **Total Questions Evaluated**: 28
- **Passed**: 26 / 28 (**92.9%**)
- **Average Latency**: **2.29 seconds**
- **In-Scope Grounding**: 100% accuracy on specific questions with multi-document cross-referencing (`UAV06`, `UAV07`).
- **Rule R1 CAAT Exception**: 100% routed to CAAT UAS Portal (`https://uasportal.caat.or.th/infographic`).
- **Out-of-Scope & Unsupported**: 100% clean abstain with zero hallucination.

---

## Automated Test Suite

Working and Verified.

Total tests: **55 automated unit/integration tests (100% PASS)**:
- `tests/test_chunking_unit.py` (4 tests)
- `tests/test_knowledge_builder_unit.py` (4 tests)
- `tests/test_rag_pipeline.py` (2 tests)
- `tests/test_retrieval_benchmark.py` (3 benchmark tests)
- `tests/test_grounded_answer_integration.py` (4 integration tests)
- `tests/test_vision_selective_unit.py` (8 edge case tests)
- `tests/test_crag_grader.py` (6 tests)
- `tests/test_web_fallback.py` (7 tests)
- `tests/test_crag_pipeline.py` (5 tests)
- `tests/test_line_webhook.py` (7 tests)
- `tests/test_chroma.py` (3 tests)
- `tests/test_benchmark_evaluation.py` (6 tests)

---

# Current Next Priority

1. Phase 3 (P3) — Deployment configuration, webhook live URL setup (e.g. ngrok / cloud server), and live end-to-end testing with real LINE app
2. Optional — Ingest remaining documents (`UAV08`, `UAV10` - `UAV12`) using selective vision & cache