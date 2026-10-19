> Historical snapshot before the 2026-10-17 MD overhaul. Not current instructions or status. Relative Markdown links rebased for this location.

# Current State

> สถานะล่าสุด 2026-10-17: ดู [ผลเตรียมส่งมอบ](../../../RELEASE_READINESS_2026-10-17.md)
> KB มีเอกสารใหม่เพิ่มเป็น 11 PDF; ค่าเริ่มต้นเป็น text + global/diverse มี partial KB+web,
> exact-page web citations, health checks และ Docker/Compose แล้ว ผลด้านล่างเป็นประวัติ
> ไม่ใช่ผลตรวจรุ่นปัจจุบัน ยังไม่มี host/LINE end-to-end จริง และภาพ investment หน้า 38 ยัง incomplete

> Updated 2026-10-17: [Claude/Codex fixes](../../../COLLAB_FIXES_2026-10-17.md) add table row/cell
> checks, a durable asynchronous LINE inbox with deduplication, safe send handling and
> revision/mode-aware answer caching. **236 tests + 55 subtests pass**. The original R3/R7
> probes now pass; the 2026-10-16 findings below are historical. Live 3-question smoke:
> 3/3 answer contracts, 2/3 latency targets (8.641s / 2.734s / 5.062s). R2 configuration,
> full semantic evaluation and deployment readiness remain open.

> Verified 2026-10-16: see [the requirements audit](../../../PROJECT_AUDIT_2026-10-16.md).
> The default KB has **774 chunks from 7 PDFs / 219 pages**. Ingestion reliability and
> typed citation boundaries were improved; R3 table-row consistency and R7 duplicate-event
> handling still have reproducible high-severity gaps. Earlier feature descriptions and
> historical measurements below are not a release-readiness guarantee.

> Updated 2026-10-15: the RAG/CRAG pipeline described below was rewritten after the
> 2026-10-14 audit ([RAG_SYSTEM_REVIEW.md](../../../RAG_SYSTEM_REVIEW.md), now historical — see its
> banner for which findings are fixed). This revision reflects the current code, not the
> audited version. 74 contract-style tests pass (`python -m pytest tests/`), and a live
> acceptance smoke test (3 real queries, `docs/LIVE_ACCEPTANCE_SMOKE.json`) surfaced a real
> latency/timeout bug that has since been fixed (see "CRAG (Corrective RAG) & Fallback"
> below). **The smoke test has not yet been re-run against the fix** — until it is, treat
> live quality/latency as unverified rather than "production-ready."

## Completed

### PDF Vision & Selective Ingestion

Implemented; production readiness is not established (see the current audit).

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
- UAV06 (23 pages): 102 chunks
- UAV07 (27 pages): 92 chunks
- UAV08 (48 pages): 150 chunks
- UAV09 (26 pages): 84 chunks
- UAV10 (48 pages): 187 chunks
- UAV11 (18 pages): 61 chunks
- UAV12 (29 pages): 98 chunks
- **Total active chunks: 774**. Historical Knowledge Unit counts are not re-certified by the current stored-chunk check.
- Current source policy excludes UAV01, UA03 and the flight-permission procedure PDF and routes their legal topics to CAAT. R1 explicitly names only the first two files; see the audit's source-policy clarification.
- ID deduplication safeguard in `add_chunks()` and `make_unit_id(..., source_origin=...)` prevents `DuplicateIDError`.
- Vision cache now uses source hash/model/version under `cache/vision/v2/`; older unversioned cache entries are not reused. Ingestion embeddings are cached separately.

---

## Retrieval & Grounding

Working across multiple documents.

Files:

`app/rag/slide_retriever.py`, `app/rag/evidence.py`, `app/rag/rag_service.py`

Features:
- `search_slides_pipeline()`: normalization, dense + corpus BM25, page-level RRF and sibling evidence merge. Default `global/none` disables the custom domain/topic reranker and topic quotas; legacy reranking remains optional.
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

Implemented; production readiness is not established (see the current audit).

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

**180 tests and 41 subtests pass** (`python -m pytest -q tests -p no:cacheprovider`, 2026-10-16). The separate gap audit still reports two high-severity failures. Historical test categories include:
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
