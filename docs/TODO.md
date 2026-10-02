# TODO

## Current Priority

### P0 — Finish baseline RAG

- [x] Clean normal text vs native table duplication
- [x] Improve retrieval content quality
- [x] Implement retrieve_context
- [x] Implement grounded LLM answer
- [x] Add source/page citation
- [x] Add RAG generation tests

### P1 — CRAG

- [x] Relevance grader
- [x] Grader tests
- [x] Tavily fallback
- [x] Fallback tests
- [x] Abstain path
- [x] Abstain tests

### P2 — LINE

- [x] Connect CRAG service to webhook
- [x] Verify LINE signature
- [x] Reply through LINE
- [x] Error handling
- [x] LINE integration tests

### P3 — Deployment

- [ ] Deployment configuration
- [ ] Environment variables
- [ ] Live webhook
- [ ] End-to-end LINE test

### P4 — Final verification

- [x] 20-30 real Thai questions
- [x] In-scope questions
- [x] Out-of-scope questions
- [x] Ambiguous questions
- [x] Unsupported questions
- [x] Latency check
- [x] Final documentation

## Future Roadmap — Planned after Core RAG is 100% Stable

### P5 — Multi-turn Conversation Context (Session Memory)
- Note: Explicitly deferred until Core RAG & Full Ingestion are 100% stable per project plan.
- [ ] Session ID / User ID tracking (LINE User ID state mapping)
- [ ] SQLite Conversation Memory (Sliding window of last 2-3 turns)
- [ ] Query contextualizer / rephraser using previous turn context
- [ ] Multi-turn regression test suite