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

### Startup warm-up (`app/main.py` lifespan -> `rag_service.warm_up_retrieval`)
`retrieve_context` imports `slide_retriever` lazily, and that import (opens Chroma) costs
~4.5s; the BM25 index build is only ~0.3s. Without warm-up the first LINE message after a
deploy paid ~4.2s of retrieval; measured with it: 0.9s, at +3.6s startup. `WARMUP_ON_STARTUP=false`
disables it; a failing warm-up is logged and never blocks startup. The LLM payload omits empty
fields (`url`/`title` on documents, `source_file`/`page_number` on web) — a lossless ~1.3%.
Do not trim *content* to save tokens: on 16 real KB answers a 10k-char budget lost a page the
model had cited in 13% of queries, 8k in 25% (see git history of this note).

### Cross-provider LLM failover (`rag_service.call_llm`, added 2026-10-16)
Optional second provider via `LLM_SECONDARY_BASE_URL` / `LLM_SECONDARY_API_KEY` /
`LLM_SECONDARY_MODELS` (disabled unless URL and key are both set). It is tried after the
primary provider's models, and **only quota/auth errors (401/429) walk on to it**: those
return instantly, so they are refunded from `max_attempts` and cost no request budget.
Timeouts and unusable responses still count against `max_attempts` and never fail over —
that is what keeps the 8s KB-generation cap intact. Secondary cooldown keys are prefixed
`secondary:` so the same model name on two providers cools down independently. Tested live
2026-10-16: Google primary (free tier exhausted, 429) -> KKU secondary answered in ~3s.

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

### Claim ↔ evidence consistency (`app/rag/claim_consistency.py`, added 2026-10-16)
The quote and number checks prove a quote is real, not that the claim *means* it: the model
can quote a real table row and attach another row's nozzle colour, crop, weed class or unit.
`parse_grounded_result` therefore also runs `claim_inconsistency()` per claim (deterministic,
no extra LLM call; a failure is an `"Evidence validation failed"` so it gets the same single
retry). It only compares labels the claim itself states: nozzle colour (Thai or English
colour word), crop, `ใบแคบ`/`ใบกว้าง`/`ใบแคบและกว้าง` as one class, units, and Latin terms.
Deliberately lenient where evidence is silent — tables often print no unit and slide titles
carry the crop — so it only rejects on *contradiction*. Measured on 97 real accepted claims:
0 false rejections; on label-swap mutations of those claims it caught 100% weed-class,
87% crop, 77% nozzle-colour swaps, and unit swaps only when the evidence prints a unit of
that dimension. **Known gap:** a quote that spans several table rows still lets the claim
pick the wrong row's label — closing it needs row-level table parsing. Don't loosen a rule
without re-running that mutation check; don't add corpus-specific words beyond the
standard label families (ISO nozzle colours, `SUPPORTED_CROPS`).

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
142 tests, all pass (run with `.venv/Scripts/python.exe -m unittest discover -s tests`; pytest is optional). These are **contract tests**, not output-matching tests — they assert
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
