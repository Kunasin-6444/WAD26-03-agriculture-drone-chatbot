> Historical snapshot before the 2026-10-17 MD overhaul. Not current instructions or status. Relative Markdown links rebased for this location.

# Claude Code + Codex: targeted fixes — 2026-10-17

## Collaboration

The user replaced the Antigravity request with Claude Code. Antigravity dispatch was
not approved and no Antigravity agent ran. Codex dispatched the scoped assignment in
`CLAUDE_HANDOFF.md` to the installed Claude Code CLI. Claude acknowledged `working`
in `CLAUDE_STATUS.md` and implemented the LINE inbox/worker and focused tests.
Claude could not run its test command under its own tool permissions, so Codex ran
the tests, reviewed the code, made the corrections below, and verified the integrated result.

## Changes

### R3: table facts

`app/rag/table_grounding.py` builds rectangular table/row/cell coordinates from the
existing pipe-separated evidence. It checks identified row labels, numerical axis
selectors, declared units and per-head/group denominators, including transposed tables
and dimensionless column names such as MDR/RS. Multiple row/height pairs are checked
individually; unioning all values in a quote no longer licenses row swaps in these fixtures.
No new LLM call, source rewrite, rounding or unit invention is used.

Regression tests reject the original orange/red value swap, swapped comparisons,
RPM-as-volume, per-head vs three-head values, wrong height/width pairs, and Thai chemical
row swaps. Valid comparisons, header context, transposed tables and axis enumerations
remain accepted. Checking 59 saved claim/source pairs against the current KB flagged none;
this is a regression check, not independently annotated proof that all 59 claims are true.

Limits: ragged/non-pipe/OCR-damaged tables and arbitrary linguistic entailment still need
better structured extraction and evaluation. The verifier checks the extracted content;
it does not prove that a PDF reader/OCR transcribed the original correctly.

### R7: durable asynchronous LINE handling (Claude implementation, Codex review)

- Verify signatures, persist text events to SQLite, then ACK without waiting for RAG.
- Unique `webhookEventId`, atomic claims and leases prevent concurrent duplicate processing.
- FastAPI lifespan starts/stops the worker; unfinished pre-send work is recovered after lease expiry.
- Delivery outcomes distinguish accepted, permanent, retryable and unknown outcomes.
  Ambiguous reply sends are not blindly followed by push.
- Push retries use a deterministic LINE retry key. Codex added expiry protection so a long
  outage cannot reuse the key after its 24-hour deduplication window.
- Codex tightened invalid-token recognition and limited HTTP 409 acceptance to push requests
  that actually used a retry key; incidental error text cannot trigger a push fallback.
- Finished payloads are scrubbed; completed identifiers are retained for deduplication.

This supports a single host. It does not guarantee exactly-once external delivery after an
arbitrary crash: a reply whose outcome is unknown can remain unanswered. A crashed send
is conservatively retained as unknown rather than re-sent. The deduplication retention is
30 days. No real LINE message was sent during this work.

Retry-key behaviour was checked against
[LINE's retry guidance](https://developers.line.biz/en/docs/messaging-api/retrying-api-request/).
HTTP acceptance does not guarantee that a recipient received/read the message.

### Answer-cache correctness

The cache key now includes the retrieval mode, PDF reader/reranking settings, database
path, database/WAL file fingerprints and optional `KB_REVISION`. A database update or
text/direct switch invalidates older answers. An answer generated while the index changes
is not cached. CAAT and other web-derived answers are not cached as static knowledge.
For controlled/versioned deployment, set `KB_REVISION` when publishing a new index.

## Verification

```powershell
.venv/Scripts/python.exe -B -m pytest -q tests -p no:cacheprovider
# 236 passed, 55 subtests passed, 1 existing Starlette/AnyIO deprecation warning

.venv/Scripts/python.exe -B -m scripts.audit_contract_gaps --output docs/COLLAB_CONTRACT_GAPS_2026-10-17.json
# exit 0; critical_gap_count = 0 for the original R3/R7 probes
```

Live sample: `COLLAB_ACCEPTANCE_SMOKE_2026-10-17.json`:

- Three document questions: automatic answer/aspect/citation checks **3/3 passed**.
- Response times: **8.641s, 2.734s, 5.062s**, mean **5.479s**.
- **2/3** met the 8-second target; the first CLI query did not.
- This is a three-query sample, not a full acceptance run or a controlled before/after
  comparison. It does not establish a production p95 or universal correctness.
- The live sample was collected during this fix session. Final verifier refinements were
  subsequently checked with offline regressions and saved claim/source pairs.

## Remaining release work

1. Resolve the literal R2/default `global/none` mismatch using measured dev/holdout evidence;
   this change does not enable a worse reranker or silently rewrite the requirements.
2. Annotate table cells/units/facts from original PDFs and expand the semantic evaluation.
3. Run the complete live acceptance set, cold/warm latency and load/restart tests on the
   actual deployment and provider quota. No provider/model change was made here.
4. Confirm production persistent storage, backup/restore, retention, quota and readiness checks.
5. Keep Direct PDF experimental pending a full-corpus comparison.

The original two reproducible probes are closed. This is not a statement that all R3
semantic errors, all requirements, or production readiness have been certified.
