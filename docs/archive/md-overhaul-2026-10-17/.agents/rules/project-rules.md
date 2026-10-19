> Historical snapshot before the 2026-10-17 MD overhaul. Not current instructions or status. Relative Markdown links rebased for this location.

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
   - PostgreSQL
   - Redis
   unless explicitly requested.
   (Hybrid retrieval and reranking ARE in scope, see `docs/PROJECT_REQUIREMENTS.md` R2;
   they must follow rule 15.)

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

13. Answer policy: answer exactly what was asked, concisely and precisely
    according to the documents. Every factual claim carries a verified citation
    (file + page, or URL). Never fill gaps from model memory.

14. Web policy: the web may supplement a partial knowledge-base answer, or answer
    alone when the documents do not cover the question, only from trusted/official
    domains and always with the URL. If nothing reliable is found, abstain explicitly.

15. Retrieval changes (query handling, fusion, reranking, top-k, chunking) must be
    measured with `python -m scripts.eval_retrieval` on the dev AND holdout sets, and
    must not lower the holdout result. Do not add keyword- or page-specific score
    multipliers tuned on test questions.

16. Ingestion must produce clean data at ingest time: repair the Thai text layer
    (`app/ingestion/thai_text.py`) and drop native text that vision already covers
    (`app/ingestion/dedupe.py`). `scripts/repair_kb.py` is a one-time migration only.
    Run `scripts/verify_ingestion.py` after ingesting.

17. Provider settings (LLM, base URL, model names, fallbacks, keys) come from
    environment variables only. Never hardcode them and never commit keys.
