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

---

# 3. Current Technology Stack

## LLM

KKU GenAI OpenAI-compatible API.

Do not replace this with another provider unless explicitly requested.

## Embedding

Google Gemini Embedding 2.

Current vector dimension:
3072

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
- grounded LLM answering
- source/page citation
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
- reranker
- hybrid search
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

---

# 7. Current Code Structure

Important modules currently include:

app/
  ingestion/
    models.py
    vision_extractor.py
    knowledge_builder.py

  rag/
    chunking.py
    embedding.py
    vector_store.py

scripts/
  test_vision_page.py
  test_knowledge_builder.py
  test_chunking.py
  test_embedding.py
  test_vector_store.py
  test_real_retrieval.py
  ingest_pdf.py

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