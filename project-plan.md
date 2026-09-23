# Project Plan: AI LINE Chatbot for Agricultural Drone Knowledge Base

## 1. Project Overview
A university final project building an AI-powered LINE Chatbot capable of answering questions about agricultural drones using an official university knowledge base.

- **Architecture:** Plain Python RAG (No LangChain, LangGraph, or LlamaIndex)
- **LLM Provider:** KKU GenAI OpenAI-compatible API (`gemini-3.5-flash-lite`, `base_url="https://gen.ai.kku.ac.th/api/v1"`)
- **Embeddings:** Google Gemini Embedding 2 (`gemini-embedding-2`, 3072 dimensions)
- **Vector DB:** ChromaDB persistent local storage (`chroma_db/`, collection: `drone_knowledge`)
- **CRAG & Web Fallback:** Tavily Search API with direct URL citations
- **Bot Interface:** Official Python LINE Bot SDK on FastAPI webhook

---

## 2. Implementation Phases & Status

### Phase 1: Core Knowledge Ingestion & Baseline RAG [COMPLETED]
- [x] **Mojibake Resolution:** Fixed all PDF filenames to standard UTF-8 Thai.
- [x] **Selective Vision & Caching:**
  - `should_use_vision()` heuristic to intelligently route complex/graphic pages to Vision while processing pure text natively (saving quota and 100x speedup).
  - Disk caching at `cache/vision/<doc>/page_<n>.json` (50 pages cached).
  - HTTP 429 retry backoff for Gemini API quota protection.
- [x] **Knowledge Unit & Deduplication:** Native table text exclusion from raw text blocks; table preservation under 1,200 chars in chunking.
- [x] **Clean ChromaDB Re-ingestion:**
  - Cleared old collection.
  - Ingested `UAV06` (23 pages, 118 KUs, 126 Chunks).
  - Ingested `UAV07` (27 pages, 106 KUs, 107 Chunks; pages 20–27 fully repaired and multimodal).
  - Total active: **233 chunks**.
- [x] **Context Expansion & Grounding:**
  - Expanded `retrieve_context()` to `n_results=15` for multi-document coverage.
  - Strict grounding with zero-hallucination prompt and mandatory Thai citations `(แหล่งอ้างอิง: [ชื่อไฟล์], หน้า [เลขหน้า])`.
- [x] **Automated Test Suite:** 22/22 unit and integration tests passing.

---

### Phase 2: CRAG Pipeline & Web Fallback [NEXT UP]
- [ ] **CRAG Relevance Grader (`app/rag/crag_grader.py`):**
  - Use KKU GenAI (`gemini-3.5-flash-lite`) to grade retrieved Chroma chunks against the user question (`YES` / `NO`).
  - Unit tests in `tests/test_crag_grader.py`.
- [ ] **Web Fallback (`app/rag/web_fallback.py`):**
  - Integrate Tavily Search API for out-of-KB or ungrounded questions.
  - Enforce official CAAT UAS Portal priority for aviation law topics (`UAV01`, `UAV03`).
  - Grounded answer generation with clickable web URL citations.
- [ ] **Abstain Policy:**
  - When neither ChromaDB nor web search yields confident evidence, cleanly abstain in Thai without guessing.
  - Integration tests in `tests/test_web_fallback.py` and `tests/test_abstain.py`.

---

### Phase 3: Complete Document Ingestion & LINE Integration [PENDING]
- [ ] Ingest remaining documents (`UAV08` - `UAV12`, CAAT PDF) using `scripts/ingest_pdf.py` with selective vision and caching.
- [ ] Wire complete RAG -> CRAG -> Web Fallback -> LINE Reply into `app/api/webhook.py`.
- [ ] Handle LINE Webhook 1-second timeout and background error handling.

---

### Phase 4: Verification & Benchmarking [PENDING]
- [ ] Run 20–30 real Thai evaluation queries (in-scope, out-of-scope, cross-document, ambiguous, legal).
- [ ] Measure latency and verify source citation accuracy.
