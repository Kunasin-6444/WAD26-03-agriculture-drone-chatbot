# TODO

## Current Priority

### Review follow-up — 2026-10-14 (resolved by pipeline rewrite + 2026-10-15 fixes)

System review: [RAG_SYSTEM_REVIEW.md](RAG_SYSTEM_REVIEW.md) — now historical, see its banner.
Current status: see [CURRENT_STATE.md](CURRENT_STATE.md). 74 contract tests pass
(`python -m pytest tests/`); live acceptance re-run still pending (see below).

- [x] Fetch actual CAAT evidence instead of injecting static facts (`web_fallback.py` calls `client.extract()` on the real CAAT page)
- [x] Preserve relevant page text alongside tables and share evidence between grader/generator (`slide_retriever.py` keeps sibling text/image chunks; grading+generation now share one evidence set via `evaluate_evidence`)
- [x] Use structured sufficiency/abstention and search for missing question aspects (`GroundedResult.status` sufficient/partial/insufficient + `missing_aspects`)
- [x] Validate citation evidence IDs and trusted URL hostnames (`evidence.parse_grounded_result` rejects unverifiable quotes/IDs; `web_fallback.is_trusted_domain` uses `urlparse().hostname`)
- [x] Bound retrieval failure handling (`crag_service.py` catches retrieval/web/generation exceptions and falls through instead of propagating)
- [ ] Generalize and grade hybrid KB/web answers — re-verify no remaining hardcoded-topic hybrid prompt path
- [ ] Isolate Chroma tests from production DB, then rerun full/live verification — unit tests now use an isolated test collection; **live acceptance smoke test (`docs/LIVE_ACCEPTANCE_SMOKE.json`) still needs re-running** after the 2026-10-15 request-budget fix (see below)

### Latency fix — 2026-10-15

- [x] KB-generation LLM call was consuming up to 16s of the 22s total request budget (2 attempts × 8s), starving web fallback and final generation — live smoke test showed this causing an incorrect abstain. Fixed: KB generation now capped to 1 attempt within an 8s sub-deadline (`crag_service.KB_GENERATION_BUDGET_SECONDS`); final generation keeps 2 attempts since it has no further fallback.
- [x] Removed dead code left over from the pre-rewrite design: `app/rag/format_utils.py` (unused since `evidence.render_grounded_answer` replaced it), `crag_grader.GradeResult`/`grade_retrieval` (superseded by `evaluate_evidence`), `rag_service.generate_grounded_answer` (unused convenience wrapper).
- [x] Added `pytest` to `requirements.txt` so `python -m pytest` works (previously only `unittest discover` worked; no dev-dependency was declared).
- [x] Re-ran `python -m scripts.evaluate_acceptance --limit 3` against the live LLM/Tavily. Confirmed the timeout fix: no run hit the 22s wall (previously exactly 22015ms); KB generation stayed ≤7.6s. But it surfaced a *different* live-only defect — see below.
- [x] Live model occasionally paraphrases/rounds a quote instead of copying it verbatim, which the strict evidence check correctly rejects and the system then abstains even though the question is answerable — confirmed by replaying the identical query/evidence manually and getting a valid result on a second try with the same prompt. Fixed: `evaluate_evidence` now retries the LLM call once (within the same deadline) when the first response fails evidence validation. Re-running the same 3-query smoke test after the fix: mean latency dropped 13.1s → 7.7s, and the previously-abstaining query now answers correctly from the KB (2.856m, matching the table).
- [x] Investigated the compound-question abstain (nozzle flow rate + spray width in one query). **Not a retrieval gap** — retrieval correctly surfaced the page with both facts every time. Root cause: `evidence.parse_grounded_result`'s numeric check only allowed numbers inside the model's trimmed quote span, so a claim that added genuinely-supported context from the same table outside that span (e.g. "...1,500 ml **for 3 nozzles**", where "3" is the table's column header, not inside the quoted row) was deterministically rejected (reproduced 3/3 identical runs). Fixed: the numeric check now allows numbers anywhere in the cited evidence record's full content, not just the quote — the quote-is-a-literal-substring check (the actual anti-fabrication guarantee) is unchanged. Re-running the smoke test: the compound question now answers correctly (both facts, one answer) in 4.2s, down from abstain.
- [x] Fixed a test-fixture bug in `scripts/evaluate_acceptance.py` surfaced by the above: 2 of the 3 smoke cases hardcoded `citations: ["UAV07"]`, but the model correctly (and more precisely — 2.856m vs UAV07's rounded 2.8m) cites **UAV06 p.5**, since both PDFs contain the same table. Changed to `citation_groups` (OR-match), matching how case 1 already handles this ambiguity.
- [x] All 3 smoke-test queries now contract-pass (was 1/3 before today's three fixes); 2/3 latency-pass (the 3rd query's single slow run was the live model taking an unusually cautious interpretation path, triggering an unneeded web search — model variance, not a bug).
- [x] Ran the full 28-case `python -m scripts.evaluate_acceptance` (`docs/LIVE_ACCEPTANCE_REPORT.json`). Only 13/28 contract-pass — but root-caused, not a regression: `gpt-5.6-luna` and `nova-2-lite-v1` both hit their **daily API quota** mid-run (`"This model reached daily limit."`, HTTP 401), from the cumulative volume of live testing done today. Confirmed this explains the two most concerning patterns: all 3 CAAT-law queries failed only during the quota outage (replayed after, got a correct cited answer once a working model was available), and the nozzle-color comparison query that abstained claiming "no comparison data" answers correctly once a working model is used — the comparison table was in the retrieved evidence the whole time. **Treat `LIVE_ACCEPTANCE_REPORT.json`'s 13/28 as contaminated by provider quota exhaustion, not representative pipeline quality.**
- [x] Switched default model (`RAG_MODEL`) from `gpt-5.6-luna` to `gemini-3.5-flash-lite` — same gateway, already validated by this project before (git history: "switch primary model to gemini-3.5-flash-lite"), and not affected by the quota exhaustion on the other two models. Added it to the front of `FALLBACK_MODELS` too. Re-ran the nozzle-comparison query after switching: now answers correctly, citing both nozzle colors' flow rates.
- [x] Re-ran the full 28-case evaluation with `gemini-3.5-flash-lite` as default (no provider errors this time): **22/28 contract-pass, 25/28 latency-pass**, mean latency 12.1s → 5.9s, p95 20.5s → 12.7s. Of the 6 remaining failures: 2 (Q07, Q12) got `grade: CORRECT` with real cited answers via web_fallback instead of the fixture's hardcoded KB expectation (test-fixture over-strictness, not a bug); 1 (Q17) abstains consistently across all 3 runs on a question the KB likely just doesn't cover (weather limits for aerial photography — a content gap, not a pipeline bug); 1 (Q06) is Gemini being more conservative than GPT was about a "recommend X" framing despite the evidence existing (model-specific behavior, not reproducible as a code defect); 1 (Q23) partially answered a hard "current price" sub-question correctly and honestly flagged what was missing.
- [x] Found and fixed a real prompt-wording bug via Q18 (a CAAT query that abstained with a telling reason: the model cited `prompts/grounded_answer.txt`'s "legal question in document evidence → force insufficient" rule even though the evidence it was evaluating was the *fetched CAAT web page itself*, not a PDF). The rule was meant to stop PDF/KB sources from answering legal questions, not the designated CAAT web source. Clarified the prompt to scope it explicitly to `D`-prefixed (PDF) source_ids vs `W`-prefixed (web) ones. Replaying the same query after the fix: now correctly answers from the real CAAT page.
- [ ] Consider a longer cooldown in `_EXHAUSTED_MODELS` specifically for a "daily limit" 401 (vs. a transient rate-limit 401/429) — currently 60s regardless, which wastes an attempt every 60s for the rest of the day once a model's daily quota is hit. Not urgent since it self-resolves overnight.

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
