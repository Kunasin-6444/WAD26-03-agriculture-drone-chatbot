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

- [ ] Relevance grader
- [ ] Grader tests
- [ ] Tavily fallback
- [ ] Fallback tests
- [ ] Abstain path
- [ ] Abstain tests

### P2 — LINE

- [ ] Connect CRAG service to webhook
- [ ] Verify LINE signature
- [ ] Reply through LINE
- [ ] Error handling
- [ ] LINE integration tests

### P3 — Deployment

- [ ] Deployment configuration
- [ ] Environment variables
- [ ] Live webhook
- [ ] End-to-end LINE test

### P4 — Final verification

- [ ] 20-30 real Thai questions
- [ ] In-scope questions
- [ ] Out-of-scope questions
- [ ] Ambiguous questions
- [ ] Unsupported questions
- [ ] Latency check
- [ ] Final documentation

## Optional — Do only after core is stable

- [ ] SQLite conversation memory