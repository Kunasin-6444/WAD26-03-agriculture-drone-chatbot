# Agriculture Drone LINE Chatbot — AI Engineering Context

## Role

You are the primary coding agent responsible for completing this project.

The project is a university final project:
"AI LINE Chatbot for Agricultural Drone Knowledge Base"

Your job is to continue the existing codebase, not redesign it from scratch.

You must:
1. inspect the existing code before changing it
2. preserve working functionality
3. implement the remaining requirements
4. write tests for every important feature
5. run tests after changes
6. never claim a feature is complete without verification
7. update project documentation when architecture or behavior changes

---

# 1. Current Source of Truth

Use these documents in this priority order:

1. `docs/PROJECT_REQUIREMENTS.md`
2. `docs/CURRENT_STATE.md`
3. `docs/ARCHITECTURE.md`
4. `docs/TEST_PLAN.md`
5. `docs/TODO.md`
6. `project-plan.md`

If an older document conflicts with the current documents above,
the current documents are authoritative.

Do NOT silently restore an older architecture.

---

# 2. Project Goal

Build a LINE chatbot that answers agricultural-drone questions using
our own official knowledge base.

Core behavior:

User question
    ->
Knowledge Base retrieval
    ->
LLM answer grounded in retrieved content

If retrieved knowledge is insufficient:

    ->
CRAG relevance grading
    ->
official web fallback
    ->
answer with citation

If neither knowledge base nor web source can provide a reliable answer:

    ->
abstain clearly
    ->
do not hallucinate

Answer quality (minimum bar of the project):

- Answer exactly what was asked: direct, concise and precise according to
  the documents. Keep numbers, units and conditions; do not pad.
- Every factual claim carries a verified citation (file + page, or URL).
- The web may supplement a partial knowledge-base answer, or answer alone
  when the documents do not cover the question, but only from trusted /
  official domains and always with the URL.
- When nothing reliable exists, say so explicitly instead of guessing.

---

# 3. Current Technology Stack

## LLM

Google AI Studio (Gemini) through its OpenAI-compatible endpoint
(`https://generativelanguage.googleapis.com/v1beta/openai`), default model
`gemini-3.5-flash-lite`.

The provider is configured only through environment variables so it can be
switched without code changes:

- `LLM_API_KEY`, `LLM_BASE_URL`, `RAG_MODEL`
- `LLM_FALLBACK_MODELS` (comma-separated; empty = none; the names must exist
  on the configured provider)
- optional tuning: `LLM_REASONING_EFFORT`, `LLM_STRUCTURED_OUTPUT`,
  `LLM_ATTEMPT_TIMEOUT_SECONDS`, `KB_GENERATION_BUDGET_SECONDS`

The KKU GenAI gateway (`https://gen.ai.kku.ac.th/api/v1`, `API_KEY`) is kept
as an alternative provider through the same variables (it is also the default
when `LLM_BASE_URL` is unset). Never hardcode a provider, base URL or model
name in Python code.

## Embedding and Vision

Google Gemini Embedding 2 (AI Studio, `GOOGLE_API_KEY`).
Vision extraction also uses Gemini through AI Studio.

Current vector dimension:
3072 (changing the embedding model requires re-ingesting everything)

## Vector database

Chroma persistent local database.

## RAG implementation

Plain Python.

Do NOT introduce LangChain, LangGraph, LlamaIndex,
or another orchestration framework unless explicitly requested.

## Backend

FastAPI.

## LINE

Official Python LINE Bot SDK.

## Web fallback

Tavily.

## Optional storage

SQLite only if conversation memory is implemented later.

---

# 4. Current MVP Scope

Must have:

- document ingestion
- text extraction
- native table extraction
- visual extraction where necessary
- Knowledge Units
- chunking
- embeddings
- Chroma retrieval
- hybrid retrieval (dense + BM25 over the whole collection, fused by RRF)
  and reranking, both measured with `scripts/eval_retrieval.py`
- grounded LLM answering
- source/page citation (verified server-side against the evidence)
- CRAG relevance grading
- web fallback
- abstain behavior
- FastAPI webhook
- LINE reply
- tests

Not required for current MVP:

- storing/rendering images for the user
- image URLs
- image hosting
- PostgreSQL
- Redis
- LangChain
- LangGraph
- conversation memory
- weather API

Do not add these features unless explicitly requested.

---

# 5. PDF Knowledge Base Rules

Uploaded project documents are the primary source of knowledge.

Important source policy:

- Use uploaded agricultural-drone documents as the knowledge source.
- `UAV01 Air Law.pdf` and `UA03 AIR SPACE.pdf` are exceptions.
- For those documents, use the CAAT UAS Portal infographic source specified
  by the project requirements.

Never invent document facts.

Preserve:
- document filename
- page number
- source type

Knowledge should remain traceable to its source.

---

# 6. Current Ingestion Architecture

PDF
 ->
text extraction
 ->
native table extraction
 ->
Vision when needed
 ->
KnowledgeUnit
 ->
Chunk
 ->
Embedding
 ->
Chroma

Vision output contains:
- extracted_text
- description
- visual_description
- summary

Vision interpretation may be used as semantic information,
but extracted source evidence must not be discarded.

Clean data must be produced at ingest time (not repaired afterwards):

- the PDFs' own text layer has damaged Thai (lost SARA AM, SARA AA mapped to
  SARA AM); `app/ingestion/thai_text.py` repairs it before chunking
- native text/table units that the page's vision units already cover (>= 85%
  and all numbers present) are dropped by `app/ingestion/dedupe.py`; native
  content that vision lacks is kept
- `scripts/repair_kb.py` is a one-time migration for a database ingested
  before these steps; `scripts/verify_ingestion.py` checks integrity

---

# 7. Current Code Structure

Important modules currently include:

app/
  api/            webhook.py (LINE)
  services/       ai_service.py (answer cache), line_service.py
  ingestion/      models.py, vision_extractor.py, knowledge_builder.py,
                  thai_text.py, dedupe.py
  rag/            crag_service.py (pipeline + request budget),
                  slide_retriever.py (hybrid retrieval),
                  rag_service.py (LLM call, provider config),
                  evidence.py (grounding gate + answer rendering),
                  web_fallback.py, source_policy.py, query_normalizer.py,
                  intent_router.py, chunking.py, embedding.py, vector_store.py

scripts/
  ingest_pdf.py, ingest_all_data.py      ingestion
  repair_kb.py, verify_ingestion.py      KB migration / integrity
  eval_retrieval.py                      retrieval metrics (dev + holdout)
  evaluate_acceptance.py                 live end-to-end harness

tests/            contract tests; tests/data/retrieval_gold.json is the
                  retrieval gold set

Do not duplicate modules unnecessarily.

---

# 8. Engineering Rules

Before modifying a file:

1. inspect the existing implementation
2. understand the data flow
3. make the smallest change that solves the problem

Do not rewrite a working module simply for style.

Avoid:
- speculative abstractions
- unnecessary dependencies
- premature optimization
- large architectural rewrites
- features outside MVP

---

# 9. Testing Rules

Every important component must have a test.

At minimum:

- chunking test
- embedding test
- vector store test
- retrieval test
- RAG generation test
- CRAG grader test
- web fallback test
- abstain test
- LINE webhook test

Tests should verify behavior, not merely that a function runs.

When a bug is fixed:

1. reproduce the bug
2. fix it
3. add a regression test
4. rerun the relevant tests

Never remove a failing test just to make the suite pass.

---

# 10. Definition of Done

A feature is NOT complete because code was written.

A feature is complete only when:

- implementation exists
- relevant tests exist
- tests pass
- integration behavior is verified
- documentation is updated when needed

A change to retrieval (query handling, fusion, reranking, top-k) is not
complete until `python -m scripts.eval_retrieval` shows it does not lower
the dev or holdout result. A change to ingestion is not complete until
`python -m scripts.verify_ingestion` passes.

Before reporting the project as complete,
run the project's test suite and report:

- tests passed
- tests failed
- known limitations
- remaining TODOs

Never claim tests passed if they were not actually run.

---

# 11. Working Style

Work incrementally.

For each task:

1. inspect
2. plan
3. implement
4. test
5. review result
6. update TODO/status

Do not jump to unrelated improvements.

When a current limitation is encountered,
prefer a simple MVP-compatible solution.

---

# 12. Important Current Known Issue

Google Gemini Vision free-tier quota can be exhausted during full-PDF ingestion.

Do not repeatedly re-run the entire Vision ingestion unnecessarily.

When debugging ingestion, prefer:
- a single page
- a small page range
- cached/intermediate results if available

Do not redesign the entire ingestion pipeline solely because
Vision quota was exhausted.

Provider latency is the other known issue: the AI Studio endpoint can
take 6-30 s per call at times (independent of prompt size), which causes
timeouts and the "temporarily unavailable" reply. Do not "fix" it by
changing prompts or retrieval; measure first (`scripts/evaluate_acceptance.py`
at a quiet time) and keep live test bursts small so they do not worsen it.

---

# 13. Final Principle

The goal is not to produce the most sophisticated RAG architecture.

The goal is:

Reliable
Traceable
Tested
Simple
Demoable
Finishable

The project must reach a working final state before adding optional features.