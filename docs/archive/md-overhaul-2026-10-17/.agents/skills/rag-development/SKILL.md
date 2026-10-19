> Historical snapshot before the 2026-10-17 MD overhaul. Not current instructions or status. Relative Markdown links rebased for this location.

---
name: rag-development
description: Develop and debug the project's RAG pipeline including retrieval, context building, grounded generation, CRAG, and source citation. Use when implementing or debugging RAG behavior.
---

# RAG Development Skill

## Pipeline

Follow this pipeline:

User Query
 ->
Embedding
 ->
Chroma Retrieval
 ->
Context
 ->
Generation

For CRAG:

Retrieval
 ->
Relevance Grader
 ->
KB answer OR Web fallback
 ->
Answer / Abstain

---

## Rules

1. Inspect retrieval results before modifying generation.

2. If retrieval is wrong:
   fix retrieval/content preparation first.

3. Do not solve retrieval problems by adding arbitrary prompt text.

4. Preserve source metadata.

5. Every generated answer must be traceable to evidence.

6. Test Thai semantic variations.

7. Use real project questions for retrieval evaluation.

8. Do not add reranking or hybrid retrieval unless baseline evidence
   shows that it is necessary.

---

## Debug order

When answer quality is wrong:

1. inspect source document
2. inspect KnowledgeUnit
3. inspect chunk
4. inspect embedding/retrieval
5. inspect retrieved context
6. only then inspect generation prompt

---

## Completion checklist

- retrieval works
- relevant chunks returned
- source metadata preserved
- grounded generation works
- unsupported question is handled
- tests pass