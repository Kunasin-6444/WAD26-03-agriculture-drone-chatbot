> Historical snapshot before the 2026-10-17 MD overhaul. Not current instructions or status. Relative Markdown links rebased for this location.

# Project Plan: AI LINE Chatbot for Agricultural Drone Knowledge Base

## 1. Project Overview
A university final project building an AI-powered LINE Chatbot capable of answering questions about agricultural drones using an official university knowledge base.

- **Architecture:** Plain Python RAG (No LangChain, LangGraph, or LlamaIndex)
- **LLM Provider:** KKU GenAI OpenAI-compatible API (Primary: `gpt-5.6-luna`, Fallbacks: `nova-2-lite-v1`, `llama-4-scout`, `base_url="https://gen.ai.kku.ac.th/api/v1"`)
- **Embeddings:** Google Gemini Embedding 2 (`gemini-embedding-2`, 3072 dimensions)
- **Vector DB:** ChromaDB persistent local storage (`chroma_db/`, collection: `drone_knowledge`)
- **CRAG & Web Fallback:** Tavily Search API with direct URL citations
- **Bot Interface:** Official Python LINE Bot SDK v3 on FastAPI webhook with interactive 6-button Rich Menu

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
- [x] **Automated Test Suite:** Unit and integration tests passing.

---

### Phase 2: CRAG Pipeline & Web Fallback [COMPLETED]
- [x] **CRAG Relevance Grader (`app/rag/crag_grader.py`):**
  - LLM-as-a-judge relevance grading (`CORRECT` / `AMBIGUOUS` / `INCORRECT`).
  - Calibrated prompt recognizing technical specs (flow rates, droplet size) as valid grounded evidence.
  - Unit tests in `tests/test_crag_grader.py`.
- [x] **Rule R1 Aviation Law Routing:**
  - Two-tier CAAT Air Law & Air Space intent classifier (keyword filter + semantic LLM classifier).
  - Enforced official CAAT UAS Portal priority (`https://uasportal.caat.or.th/infographic`) bypassing local PDFs (`UAV01`, `UA03`).
- [x] **Web Fallback (`app/rag/web_fallback.py`):**
  - Integrated Tavily Search API with `search_depth="basic"`.
  - Domain filtering for official sources (`.go.th`, `.or.th`, `.ac.th`).
  - Grounded answer generation with clickable web URL citations.
  - Unit tests in `tests/test_web_fallback.py`.
- [x] **Strict Abstain Policy (Rule R6):**
  - When neither ChromaDB nor web search yields confident evidence, cleanly abstain in Thai without guessing.
  - Tests in `tests/test_crag_pipeline.py`.
- [x] **Latency & Resilience Optimization:**
  - In-memory caching for 401 quota-exhausted models (`_EXHAUSTED_MODELS`).
  - Compact grader context (max 2,500 chars) reducing total query latency from 30–50s down to ~8–10s.

---

### Phase 3: LINE Integration & Interactive UI [COMPLETED]
- [x] **FastAPI Webhook (`app/api/webhook.py`):**
  - Webhook signature verification via `WebhookParser(LINE_CHANNEL_SECRET)`.
  - Filtered dummy verification tokens (`00000000000000000000000000000000`).
  - Defensive error handling returning polite Thai message on server failure.
  - Tests in `tests/test_line_webhook.py`.
- [x] **LINE Messaging API (`app/services/line_service.py`):**
  - `reply_text()` with 4,950-character limit guard preventing API 400 errors.
- [x] **LINE Rich Menu (`app/services/rich_menu_service.py` & `scripts/setup_rich_menu.py`):**
  - 6-button interactive 3x2 grid layout (2500x1686 px).
  - Button 1 (URI Action): Direct link to CAAT Infographic URL (Rule R1).
  - Buttons 2–6 (Message Actions): Quick shortcuts for registration, nozzle specs, weed control, aerial mapping, and AI prompt guide.
  - Deployed, uploaded background image, and activated as default menu.
  - Tests in `tests/test_rich_menu.py`.

---

### Phase 4: Verification & Benchmarking [COMPLETED]
- [x] **Comprehensive Evaluation Benchmark:**
  - Executed 28 real-world Thai questions across 5 dimensions (`docs/FINAL_EVALUATION_REPORT.json`).
  - **Overall Accuracy: 92.9% (26 / 28 passed)**.
  - **Average Latency: ~2.29 seconds**.
  - In-Scope Grounding: 100% accuracy with multi-document cross-referencing.
  - Rule R1 CAAT Exception: 100% routed to CAAT UAS Portal.
  - Out-of-Scope & Unsupported: 100% clean abstain with zero hallucination.
- [x] **Automated Regression Suite:** 55+ automated tests passing with 100% pass rate.

---

### Phase 5: Production Roadmap & Remaining Tasks [IN PROGRESS]
- [ ] **Full Knowledge Base Ingestion (Deadline: Oct 5, 2026):**
  - Ingest remaining PDFs (`UAV08` Herbicides, `UAV09` pp. 6+, `UAV10-12` Mapping, and Self-Registration Guide) using `scripts/ingest_all_data.py`.
- [ ] **Multi-turn Conversation Context (Post-Core Stabilization):**
  - Deferred until Core RAG & Ingestion are 100% stable per user directive.
  - Implement SQLite session memory (sliding window 2-3 turns) so users can ask follow-up questions naturally.
- [ ] **Pilot User Acceptance Testing (UAT) (Deadline: Oct 12, 2026):**
  - Conduct live testing with 10–15 agricultural drone pilots and operators; collect satisfaction and response quality feedback.
- [ ] **Cloud Production Deployment (Deadline: Oct 19, 2026):**
  - Containerize application via Docker.
  - Deploy to Cloud VPS / Server with permanent HTTPS domain and SSL (replacing local ngrok).
- [ ] **Final Thesis & Oral Defense Preparation (Deadline: Oct 26, 2026):**
  - Complete thesis documentation.
  - Finalize presentation slide deck.
  - Practice defense oral Q&A using `docs/ORAL_QA.md`.
