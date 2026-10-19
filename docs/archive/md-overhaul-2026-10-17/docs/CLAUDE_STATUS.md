> Historical snapshot before the 2026-10-17 MD overhaul. Not current instructions or status. Relative Markdown links rebased for this location.

# Claude Code status — LINE delivery reliability (R7)

Status: `done` — implementation reviewed and tested by Codex (see verification below).
Updated: 2026-10-17

## Codex integration verification

Claude's original test command could not run under its tool permissions; the historical
Results section below records that truthfully. Codex subsequently ran the focused tests,
reviewed and tightened send classification and push retry-key expiry, and ran the full suite:
**236 tests + 55 subtests passed**, one existing Starlette/AnyIO warning.
The updated R3/R7 probe reports zero remaining failures for its original cases.
See `COLLAB_FIXES_2026-10-17.md` for exact changes, commands, live samples and remaining work.

## Acknowledgement
Read `docs/CLAUDE_HANDOFF.md`. I own the R7 assignment: LINE delivery reliability.

## Scope (allowed ownership only)
- `app/api/webhook.py`
- `app/services/line_service.py`
- new inbox/worker module under `app/services/`
- new tests (isolated temp SQLite DB, mocked LINE client, mocked `ask_ai`)
- this file

Not touching: RAG, ingestion, retrieval, prompts, provider settings, source policies,
audit scripts, requirement docs. Pre-existing uncommitted changes are preserved (no
reset/stash/revert). `app/main.py` is needed for lifespan wiring; I will record that
here before editing it.

## Proposed design (to be refined after reading current code)
SQLite inbox keyed by `webhookEventId` (PRIMARY KEY, `INSERT OR IGNORE` => uniqueness
across concurrent redelivery and restarts). Webhook: verify signature -> persist events
-> return 200; no RAG wait. A background worker claims `pending` rows, runs `ask_ai`,
and sends the reply, recording state transitions
(`pending -> processing -> done | failed_permanent | failed_retryable | unknown_outcome`).
Ambiguous send timeouts become `unknown_outcome` and are never blindly pushed.
On restart, rows left in `processing` before a send was attempted are re-queued;
rows left `sending` are marked `unknown_outcome`.

## Refined design (after reading code)
Files I will touch (declared before editing, per handoff):
- `app/services/line_inbox.py` (new): SQLite store + async worker.
- `app/services/line_service.py`: add `SendResult` + `send_reply`/`send_push` that classify
  failures; `reply_text`/`push_text` stay as bool wrappers (back-compat).
- `app/api/webhook.py`: verify signature -> persist -> 200; no RAG wait.
- **`app/main.py`** (outside the named ownership list, allowed by handoff if recorded):
  lifespan creates the inbox + starts/stops the worker, stored on `app.state`.
  Webhook returns 503 (so LINE redelivers) if the inbox is not initialised.
- `tests/test_line_inbox_contract.py` (new) and `tests/test_line_integration_contract.py`
  (existing; its patch targets/`TestClient` usage must change because the webhook no
  longer calls `ask_ai`/`reply_text` inline).
- DB path: env `LINE_INBOX_DB_PATH`, default `cache/line_inbox.sqlite3` (gitignored dir).
  Tests always point it at a temp dir.

Mechanics: `webhookEventId` is the PRIMARY KEY (`INSERT OR IGNORE`). Claims use a
per-claim token + lease, so a stale worker cannot overwrite a newer claim and a restart
(or second process) recovers expired leases without double-processing live ones.
States: `pending -> processing -> sending -> done | failed_permanent | unknown_outcome`;
retryable failures return to `pending` with backoff up to a max attempt count.
Send classification: reply delivered / reply-token verified invalid (HTTP 400
"Invalid reply token") -> push fallback with a deterministic `X-Line-Retry-Key`;
429 or connection-never-established -> retryable; other 4xx -> permanent; 5xx, read
timeouts, resets -> **unknown outcome: no blind push**.

## Results

### Verification: NOT done
My one attempt to run the focused tests with the project venv was auto-denied (this
session has no approval surface), and I did not retry or route around it. **Nothing below
has been executed**; I only reviewed the code and tests by reading them. Please run:

```
.venv\Scripts\python.exe -m pytest tests/test_line_inbox_contract.py tests/test_line_integration_contract.py tests/test_payload_and_warmup_contract.py -q
```

Expect possible test-side bugs on first run (timing-based restart tests in particular).
No LINE delivery occurred or was attempted; no live APIs were called.

### Changed files
- `app/services/line_inbox.py` (new) — `InboxStore` (SQLite, WAL, `synchronous=FULL`),
  `LineInbox` worker, `build_inbox_from_env()`.
- `app/services/line_service.py` — `SendResult`, `classify_send_error`, `send_reply`,
  `send_push` (retry key + `_request_timeout`); `reply_text`/`push_text` kept as bool wrappers.
- `app/api/webhook.py` — verify signature, persist, 200; 503 if not persisted.
- `app/main.py` — lifespan starts/stops the inbox (`app.state.line_inbox`).
- `tests/line_helpers.py` (new), `tests/test_line_inbox_contract.py` (new).
- `tests/test_line_integration_contract.py` — rewritten onto the inbox (patch targets moved
  to `app.services.line_inbox.*`). The old `test_slow_ai_does_not_block_async_event_loop`
  is replaced by `test_ack_is_prompt_and_loop_free_while_ai_is_blocked`, which keeps its
  health-check-while-AI-blocked assertion and adds prompt ACK + no reply before release.
- `tests/test_payload_and_warmup_contract.py` — `setUp` points the inbox at a temp dir,
  because entering the lifespan now opens the inbox (would otherwise write `cache/`).
- `docs/CLAUDE_STATUS.md`.
No RAG/ingestion/retrieval/prompt/provider files touched.

### Needs Codex attention
- `scripts/audit_contract_gaps.py` (R7 probe, lines ~51-55) patches
  `app.api.webhook.ask_ai/reply_text/push_text/show_loading_animation`, which no longer
  exist there, and uses `TestClient(app)` without lifespan (now answers 503). I did not
  edit that shared script. Re-point it at `app.services.line_inbox.*`, use `with TestClient`,
  set `LINE_INBOX_DB_PATH` to a temp file, and wait for the worker before counting.
- Any other test entering the lifespan must set `LINE_INBOX_DB_PATH` to a temp path.
  Default is `cache/line_inbox.sqlite3` (gitignored).

### Behaviour and limitations (as designed)
- Not exactly-once. The Reply API has no idempotency key. A reply that times out, resets
  or returns 5xx, or a crash while a send is in flight, becomes `unknown_outcome`: never
  re-sent, never pushed (user may get no answer, but not a duplicate).
- Only a verified `HTTP 400 ... reply token` triggers the push fallback (previous
  behaviour for expired tokens preserved). Pushes carry a deterministic `X-Line-Retry-Key`
  so an unknown push can be retried; that relies on LINE de-duplicating the key for 24h
  (including treating 409 as already-accepted) — untested against the real API.
- 429 and connection-never-established are retryable with backoff (2s/10s/30s, max 4
  attempts, then `failed_permanent/retries_exhausted`); other 4xx permanent.
- A crash before the send starts (`processing`) is re-queued after the lease (default
  120s, `LINE_INBOX_LEASE_SECONDS`), so recovery after restart waits for lease expiry
  and the single-use reply token may by then be invalid (push fallback applies). The AI call
  may be re-run once for such rows.
- Single host only. Finished rows have text/token/answer scrubbed; rows pruned after 30 days.
- Env knobs: `LINE_INBOX_DB_PATH`, `LINE_INBOX_LEASE_SECONDS`, `LINE_INBOX_MAX_ATTEMPTS`,
  `LINE_WORKER_CONCURRENCY` (default 3).
- Unlike before, the loading animation is triggered by the worker (when it starts the AI
  call), not before ACK.
