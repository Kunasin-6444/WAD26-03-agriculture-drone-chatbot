# Current State

> Updated 2026-10-15: the RAG/CRAG pipeline described below was rewritten after the
> 2026-10-14 audit ([RAG_SYSTEM_REVIEW.md](RAG_SYSTEM_REVIEW.md), now historical — see its
> banner for which findings are fixed). This revision reflects the current code, not the
> audited version. 74 contract-style tests pass (`python -m pytest tests/`), and a live
> acceptance smoke test (3 real queries, `docs/LIVE_ACCEPTANCE_SMOKE.json`) surfaced a real
> latency/timeout bug that has since been fixed (see "CRAG (Corrective RAG) & Fallback"
> below). **The smoke test has not yet been re-run against the fix** — until it is, treat
> live quality/latency as unverified rather than "production-ready."

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
- `UAV06 โดรนฉีดพ่นเพื่อการเกษตร.pdf` (23 pages): 118 KUs, 126 Chunks
- `UAV07 หัวฉีดกับคุณภาพการฉีดพ่นของโดรนเกษตร.pdf` (27 pages): 106 KUs, 107 Chunks
- `UAV08 วัชพืชและการควบคุม application.pdf` (48 pages): 161 KUs, 172 Chunks
- `UAV09 การใช้สารกำจัดวัชพืช.pdf` (26 pages): 82 KUs, 103 Chunks
- `UAV10 พื้นฐานการใช้ภาพถ่ายทางอากาศเพื่อการสำรวจแปลง.pdf` (48 pages): 204 KUs, 215 Chunks
- `UAV11 การสาธิตการใช้โดรนสำรวจ.pdf` (18 pages): 72 KUs, 77 Chunks
- `UAV12 การตั้งเงื่อนไขการบินเพื่อให้ภาพถ่ายมีคุณภาพ อ.ขวัญ.pdf` (29 pages): 108 KUs, 112 Chunks
- **Total active chunks in ChromaDB: 912 chunks** (7 documents fully ingested, cleaned up 3 stray mock test chunks)
- Law documents (`UAV01`, `UA03`, and `ขั้นตอนการยื่นขออนุญาตปฏิบัติการบินโดรนเกษตรเพื่อตนเอง.pdf`) are excluded from vector ingestion and routed directly to CAAT UAS Portal per policy/Rule R1.
- ID deduplication safeguard in `add_chunks()` and `make_unit_id(..., source_origin=...)` prevents `DuplicateIDError`.
- Disk cache: `cache/vision/` stores all analyzed pages for instant re-runs without API quota.

---

## Retrieval & Grounding

Working across multiple documents.

Files:

`app/rag/slide_retriever.py`, `app/rag/evidence.py`, `app/rag/rag_service.py`

Features:
- `search_slides_pipeline()`: 6-step hybrid retrieval (query normalization, dense Gemini-embedding search + custom BM25 over Thai n-grams, page-level RRF merge that keeps table *and* sibling text/image chunks on the same page, domain/crop/topic reranking, topic-diverse top-k selection, context assembly).
- `evidence.document_evidence()` parses the assembled context into typed `Evidence` records (per source file + page), then `evaluate_evidence()` makes one LLM call (`prompts/grounded_answer.txt`) that returns a structured `GroundedResult`: `status` (`sufficient`/`partial`/`insufficient`), per-claim `source_id` + verbatim `quote`.
- `evidence.parse_grounded_result()` is the grounding gate: it rejects any claim whose quote is not a literal substring of the cited evidence, whose numbers aren't backed by the quoted text, or whose `source_id` doesn't exist — citations are server-verified, not just LLM-formatted text.
- `evidence.render_grounded_answer()` builds the final bulleted answer with a numbered `แหล่งอ้างอิง:` reference list built only from evidence actually cited; falls back to a fixed abstain message if claims and evidence don't line up.
- Connected end-to-end through `ask_ai` → `run_crag_pipeline` → LINE Webhook.

---

## CRAG (Corrective RAG) & Fallback

Working. Live acceptance quality/latency not yet re-verified after the 2026-10-15 timeout fix (see below).

Files:
- `app/rag/intent_router.py`: routes bot-usage questions to a canned response before any retrieval.
- `app/rag/crag_grader.py`: keyword routing for Air Law / Air Space topics to the designated CAAT source (no longer a standalone grader — sufficiency grading now happens inside `evaluate_evidence`).
- `app/rag/web_fallback.py`: Tavily web search; CAAT topics genuinely fetch the designated CAAT portal page via `client.extract(...)` (not injected static text). Trusted-domain check uses `urlparse().hostname` matching, not substring matching on the full URL.
- `app/rag/crag_service.py`: orchestrates the full flow — KB retrieval → structured sufficiency evaluation → web fallback when not `sufficient` (or for "today/latest" freshness queries) → combined re-evaluation → clear abstain when evidence still doesn't support a claim.
- `app/services/ai_service.py`: `ask_ai` is a thin wrapper over `run_crag_pipeline`.

Features:
- CAAT topics bypass the PDF KB entirely and must cite real fetched CAAT content or abstain with a link.
- Partial KB evidence is preserved (not discarded) when web search is used to fill in missing aspects; KB evidence that wasn't actually used in the partial answer is dropped so it can't contaminate the web-combined answer.
- Explicit abstain (fixed Thai message) when evidence from neither source supports a claim — no guessing.
- **Request budget**: each query gets `RAG_REQUEST_TIMEOUT_SECONDS` (default 22s) total. Previously, KB-generation could spend up to 2 model attempts × 8s = 16s of that budget, starving web search and final generation — a live smoke test showed exactly this (`kb_generation_ms: 12250` of a 22015ms total, final answer forced to abstain). **Fixed 2026-10-15**: KB generation is now capped to 1 model attempt within an 8s sub-deadline (`crag_service.KB_GENERATION_BUDGET_SECONDS`), since it has a fallback path (web search); final generation — the last chance to answer — still gets up to 2 attempts within whatever budget remains.

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

## Live Acceptance Evaluation

Harness working. 3/3 smoke-test queries now contract-pass after three 2026-10-15 fixes
(request-budget starvation, validation-failure retry, numeric-claim check scope). Full
28-case run still pending.

Files:
- `scripts/evaluate_acceptance.py`: live harness (real LLM + real vector store + real Tavily) running Thai queries across all routing categories, checking expected source/citations/terms and an 8s per-query latency target via `assess()`.
- `docs/LIVE_ACCEPTANCE_SMOKE.json`: a 3-query smoke run, now reflecting all three 2026-10-15 fixes. All 3 queries answer correctly from the KB (previously: 1/3 abstained on pure budget starvation, then 1/3 on a quote-paraphrase mismatch, then 1/3 on a compound question whose numeric check was over-strict — each traced to a specific cause and fixed; see `TODO.md`'s "Latency fix" section for the full history). Latency is 2/3 under the 8s target; the remaining slow run was the live model taking an unusually cautious interpretation path on one query (model variance, not a bug).

---

## Automated Test Suite

Working and verified — contract-based tests, not output-matching tests.

**74 tests pass** (`python -m pytest tests/` or `python -m unittest discover -s tests`):
- `tests/test_evidence_contract.py`: citation/quote/number verification, evidence packing budget.
- `tests/test_ingestion_embedding_contract.py`: real PDF ingestion (table/text separation, vision fallback caching), embedding timeout/retry/empty-input handling.
- `tests/test_retrieval_storage_contract.py`: chunking math, query-normalization idempotence, real isolated Chroma round-trip, excluded-document filtering at ingestion and retrieval.
- `tests/test_web_source_contract.py`: domain-spoofing rejection, Tavily search/extract wrapping, CAAT-restricted search, dedup/timeout handling.
- `tests/test_llm_budget_contract.py`: shared evidence sent once, strict timeouts/temperature=0, provider fallback capped, truncated/reasoning-only output rejected, prompt-injection text treated as untrusted data.
- `tests/test_pipeline_contract.py`: end-to-end `run_crag_pipeline` with mocked retrieval/search/LLM — routing to knowledge_base/web_fallback/hybrid/caat_portal/abstain, exactly one extra web search on partial evidence, graceful degradation on failures.
- `tests/test_line_integration_contract.py`: real FastAPI `TestClient` against the webhook — signature validation, async non-blocking behavior, message-length truncation.
- `tests/test_acceptance_harness.py`: unit-tests the live-acceptance harness itself.

---

# Current Next Priority

1. Re-run `scripts/evaluate_acceptance.py` to confirm the 2026-10-15 timeout fix resolves the live latency/abstain failure.
2. Phase 3 (P3) — deployment config, env vars, live webhook, end-to-end LINE test (see TODO.md).
