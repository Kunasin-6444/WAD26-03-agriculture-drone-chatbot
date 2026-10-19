> Historical snapshot before the 2026-10-17 MD overhaul. Not current instructions or status. Relative Markdown links rebased for this location.

---
description: Prevents unnecessary architecture changes and scope creep.
alwaysOn: true
---

# Change Control

Before implementing a substantial architecture change:

1. inspect the current implementation
2. explain why the current implementation cannot satisfy the requirement
3. prefer a local fix if possible

Do NOT:
- replace Chroma
- replace Gemini Embedding 2 (it would require re-ingesting the whole knowledge base)
- replace FastAPI
- introduce a framework abstraction
- add another database
- redesign the ingestion architecture

unless the current implementation is demonstrably insufficient
for an explicit project requirement.

LLM provider: Google AI Studio (Gemini via its OpenAI-compatible endpoint) is the
default; KKU GenAI remains an alternative selected only through environment variables
(`LLM_BASE_URL`, `LLM_API_KEY`, `RAG_MODEL`, `LLM_FALLBACK_MODELS`). Changing the
default provider or model needs measured evidence (latency and answer correctness on
the acceptance set), not a guess.

For ambiguous improvements, choose the simplest MVP solution.
