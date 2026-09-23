---
description: Core engineering rules for the Agriculture Drone LINE Chatbot.
alwaysOn: true
---

# Project Rules

1. Preserve the current architecture unless a change is necessary.

2. Prefer the smallest working change.

3. Do not add dependencies without a concrete reason.

4. Do not introduce:
   - LangChain
   - LangGraph
   - LlamaIndex
   - rerankers
   - hybrid search
   - PostgreSQL
   - Redis
   unless explicitly requested.

5. Keep ingestion, RAG, API, and LINE integration separated.

6. Keep system prompts separate from Python code where required.

7. Every bug fix must include a regression test when practical.

8. Do not report success without running verification.

9. Do not silently change requirements.

10. When requirements conflict, use `docs/PROJECT_REQUIREMENTS.md`
    as the source of truth.

11. Avoid speculative optimization.

12. Do not implement out-of-scope features simply because they are
    technically interesting.