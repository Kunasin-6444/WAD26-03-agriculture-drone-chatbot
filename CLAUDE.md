# CLAUDE.md

Agriculture drone LINE chatbot. Answers questions from an ingested PDF knowledge base,
falls back to live web search when the KB is insufficient, and cites every claim —
citations are server-verified against the actual evidence text, never trusted from the
LLM's own formatting.

## Architecture (current, as of 2026-10-15)

`docs/CURRENT_STATE.md` has rationale and feature-level detail. This is the call chain:

```
LINE webhook (app/api/webhook.py)
  -> ask_ai()                      app/services/ai_service.py
    -> run_crag_pipeline()         app/rag/crag_service.py
      -> route_intent()            app/rag/intent_router.py        (bot-usage shortcut)
      -> is_caat_air_law_or_airspace_topic()  app/rag/crag_grader.py (routes to CAAT, not PDF)
      -> retrieve_context()        app/rag/rag_service.py -> slide_retriever.search_slides_pipeline()
      -> document_evidence() + pack_evidence()   app/rag/evidence.py
      -> evaluate_evidence()       app/rag/rag_service.py  (1 LLM call: sufficiency + claims + citations)
      -> [if not sufficient] search_web_fallback() + web_evidence()   app/rag/web_fallback.py
      -> evaluate_evidence() again on combined KB+web evidence
      -> render_grounded_answer()  app/rag/evidence.py
  -> reply_text()                  app/services/line_service.py
```

**There is no separate grading LLM call.** Sufficiency grading and answer generation
happen in one `evaluate_evidence()` call — the LLM returns structured JSON
(`status`: sufficient/partial/insufficient, claims with per-claim `source_id` + verbatim
`quote`), and `evidence.parse_grounded_result()` is the actual grounding gate: it rejects
any claim whose quote isn't a literal substring of the cited evidence, whose numbers
aren't backed by the quoted text, or whose `source_id` doesn't exist in the supplied
evidence. The LLM cannot fabricate a citation that survives this check.

### Retrieval (`app/rag/slide_retriever.py`)
6-step hybrid pipeline: Thai query normalization → dense Chroma search (`gemini-embedding-2`)
+ custom BM25 over Thai n-grams → page-level Reciprocal Rank Fusion → merge that keeps
table/diagram chunks *and* sibling text/image chunks on the same page (don't regress this —
text carries units/caveats that tables alone lose) → domain/crop/topic reranking → topic-
diverse top-k selection.

### Request budget (`app/rag/crag_service.py`)
Each query gets `RAG_REQUEST_TIMEOUT_SECONDS` (default 22s, env var) total, enforced via a
`deadline` threaded through `call_llm`. **KB generation is deliberately capped to 1 model
attempt within an 8s sub-deadline** (`KB_GENERATION_BUDGET_SECONDS`) because it has a
fallback path (web search) — don't let it consume the full budget like it used to (a live
smoke test showed `kb_generation_ms: 12250` of a 22015ms total, forcing an incorrect
abstain). Final generation (no further fallback after it) keeps up to 2 attempts within
whatever budget remains. If you touch timeout/retry logic here, re-run
`scripts/evaluate_acceptance.py` against the live LLM — mocked unit tests won't catch
budget-starvation bugs like this.

### Numeric-claim check scope (`evidence.parse_grounded_result`)
A claim's numbers must appear somewhere in the **full content of its cited evidence
record(s)**, not just inside the model's trimmed quote span. This was tightened
2026-10-15: the stricter (quote-only) version deterministically rejected correct answers
whenever the model added genuinely-supported context from the same table that fell
outside its minimal quote — e.g. quoting a table row `"1 | พัดส้ม | 1600 | 500 | 1500"` but
writing "...or 1,500 ml **for 3 nozzles**", where "3" comes from the same table's column
header, not the quoted row. Reproduced deterministically (3/3 identical runs) before the
fix. The quote-is-a-literal-substring check (the actual anti-fabrication guarantee) is
unchanged — this only widened where *numbers* are allowed to come from, still scoped to
evidence the model actually cited.

### Validation-failure retry (`rag_service.evaluate_evidence`)
The live model is not perfectly deterministic even at `temperature=0`: it occasionally
paraphrases/rounds a quote instead of copying it verbatim, which `parse_grounded_result`
correctly rejects (reason prefixed `"Evidence validation failed: ..."`) — confirmed live:
the same query/evidence pair failed validation on one call and succeeded on an immediate
retry with an identical prompt. `evaluate_evidence` now retries the LLM call once (still
inside the same `deadline`, so this can't reintroduce budget starvation) when the first
response fails validation, before giving up. Don't treat "evidence validation failed" and
a legitimate LLM-reported "insufficient" as the same thing when changing this — they're
distinguished by the literal `"Evidence validation failed"` prefix.

### Source policy (`app/rag/source_policy.py`)
Single place for: which documents are excluded from ingestion/retrieval (air-law PDFs are
routed to CAAT instead, per policy), and web URL validation. `web_fallback.is_trusted_domain`
uses `urlparse().hostname` matching — never go back to substring matching on the full URL
(a spoofed domain like `caat.or.th.attacker.example` would pass a substring check).

## What's dead / don't resurrect
- `app/rag/format_utils.py` was deleted 2026-10-15 — it formatted free-text LLM output
  (markdown stripping, CoT-leakage stripping) for a pre-rewrite design where the LLM
  produced the final text directly. The current pipeline builds the answer server-side in
  `evidence.render_grounded_answer()`; there's no free text to clean.
- `crag_grader.py` no longer has a standalone `grade_retrieval()`/`GradeResult` — sufficiency
  grading is fused into `rag_service.evaluate_evidence()`. The file only keeps
  `is_caat_air_law_or_airspace_topic()` for CAAT routing.
- `rag_service.generate_grounded_answer()` was an unused convenience wrapper — removed.
- `docs/RAG_SYSTEM_REVIEW.md` is a historical audit of the *pre-rewrite* pipeline. Its
  file:line references don't match current code. Read its banner before trusting anything
  in its body.

## Testing
```
python -m pytest tests/            # or: python -m unittest discover -s tests
```
74 tests, all pass. These are **contract tests**, not output-matching tests — they assert
behavioral guarantees (citations map to real evidence, quotes are verbatim, fabricated
references get stripped, web fallback triggers exactly when it should, failures degrade
without inventing facts) rather than exact strings. Most mock the LLM/Tavily clients; a
couple deliberately hit real resources (an actual PDF under `data/`, a real but isolated
Chroma collection cleaned up via `addCleanup`) — expect those to make real embedding API
calls.

`scripts/evaluate_acceptance.py` is a separate **live** harness (real LLM + real vector
store + real Tavily, consumes API quota) — run it manually to validate live latency/quality
against 28 real Thai queries; it is not part of the pytest suite. `docs/LIVE_ACCEPTANCE_SMOKE.json`
is a checked-in 3-query sample run; re-run after changing anything in the request-budget or
retrieval path.

## Conventions
- Evidence IDs: `D1, D2, ...` for document/KB evidence, `W1, W2, ...` for web evidence —
  assigned in `evidence.document_evidence()` / `web_fallback.web_evidence()`.
- All user-facing strings are Thai. Don't introduce English UI strings.
- Never let the LLM's own text become the final answer unchecked — if you add a new
  generation path, run its output through the same verify-then-render pattern as
  `evidence.parse_grounded_result()` + `render_grounded_answer()`.
