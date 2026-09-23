---
name: testing-verification
description: Create, run, and review automated tests for the agriculture drone chatbot. Use whenever implementing features, fixing bugs, or verifying project completion.
---

# Testing and Verification Skill

## Required workflow

Before coding:

1. identify acceptance criteria
2. identify relevant tests

After coding:

1. run focused tests
2. inspect failures
3. fix implementation
4. add regression tests
5. rerun tests

Before completion:

1. run full test suite
2. report exact results
3. identify known limitations
4. update TODO/status

---

## Test categories

### Unit

- models
- chunking
- formatting
- utility logic

### Component

- embedding
- Chroma
- retrieval

### Integration

- RAG
- CRAG
- Tavily fallback
- FastAPI webhook
- LINE

### End-to-end

Real Thai user questions.

---

## Important test principle

A test must verify expected behavior.

Bad:

"function executes"

Good:

"query retrieves the relevant UAV07 page-12 table
containing the requested evidence"

---

## Regression testing

Whenever a bug is found:

1. reproduce
2. write a failing test
3. fix
4. rerun