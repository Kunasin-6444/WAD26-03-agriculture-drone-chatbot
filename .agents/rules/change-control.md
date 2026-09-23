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
- replace Gemini Embedding 2
- replace FastAPI
- replace KKU GenAI
- introduce a framework abstraction
- add another database
- redesign the ingestion architecture

unless the current implementation is demonstrably insufficient
for an explicit project requirement.

For ambiguous improvements, choose the simplest MVP solution.