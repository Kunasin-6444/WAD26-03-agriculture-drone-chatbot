---
name: rag-development
description: Diagnose or change KB retrieval, mixed KB and web answers, grounding and source citations. Use only for relevant RAG work.
---

# RAG development

Use [AGENTS](../../../AGENTS.md), [requirements](../../../docs/PROJECT_REQUIREMENTS.md),
[architecture](../../../docs/ARCHITECTURE.md) and [verification policy](../../../docs/TEST_PLAN.md).
This skill replaces the former fixed pipeline and mandatory completion checklist.

1. Start from the observed question/failure and the underlying evidence, not an assumed framework problem.
2. Inspect only relevant extraction, retrieval, evidence packing, generation or validation steps.
3. Keep verified KB facts when web fills missing aspects. Preserve units, conditions and source identity.
4. Cite KB filename/pages and the exact web page/document URL supporting each claim; never invent references.
5. Make the simplest working change; replacing architecture is allowed when justified by the task.
6. Use meaningful focused offline checks where risk warrants them, then hand back a usable trial.

Do not automatically call providers, run acceptance/holdout batches, re-ingest data or add grader/repair stages.
No specific Chroma/BM25/reranker/chunk size/provider is a permanent requirement.
Report what changed and remaining uncertainty; do not claim universal semantic correctness from validation or a small sample.
