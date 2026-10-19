> Historical snapshot before the 2026-10-17 MD overhaul. Not current instructions or status. Relative Markdown links rebased for this location.

# Antigravity collaboration — 2026-10-17

> Cancelled: dispatch was not approved. The user subsequently requested Claude instead.
> Active assignment: `docs/CLAUDE_HANDOFF.md`. No Antigravity work was started.

The user explicitly requested that Codex work with Antigravity to fix the current audit findings.
Workspace: `D:/Years4/webApp/project/agriculture-drone-chatbot`.

## Your assignment: LINE delivery reliability (R7)

Read `CLAUDE.md`, `.agents/rules/`, `docs/PROJECT_REQUIREMENTS.md`,
`docs/PROJECT_AUDIT_2026-10-16.md`, `app/api/webhook.py`, and `app/services/line_service.py`.
The audit reproduced a valid signed webhook with the same `webhookEventId` being processed
and replied to twice. The HTTP request also waits for RAG before acknowledgement.

Before editing, write `docs/ANTIGRAVITY_STATUS.md` with status `working`, your scope,
and your proposed design. Codex will read this file for acknowledgement and coordination.

Implement a small, durable single-host inbox/worker (SQLite is acceptable for this demonstrated
delivery problem; do not add Redis/PostgreSQL or conversation memory). Requirements:

1. Verify LINE signature before storing or processing any event.
2. Persist accepted events before returning HTTP 200; do not wait for RAG in the webhook.
3. Enforce uniqueness by `webhookEventId`, including concurrent redelivery and restarts.
4. Worker processes each accepted event once under normal/concurrent delivery and records
   progress/outcome. Be explicit about crash/unknown-send-outcome limitations: do not promise
   exactly-once delivery across arbitrary failures without an idempotent external send API.
5. Do not blindly push after an ambiguous reply timeout. Separate permanent, retryable, and
   unknown-outcome failures; preserve existing safe behaviour for verified-expired reply tokens.
6. Integrate startup/shutdown with FastAPI lifespan. Use an isolated test DB; no production
   LINE sends or production inbox/index writes while testing.
7. Test signed duplicate events, concurrent duplicates, prompt ACK while AI is blocked,
   invalid signatures, restart recovery, and safe behaviour after ambiguous delivery errors.

Allowed ownership: `app/api/webhook.py`, `app/services/line_service.py`, a new inbox/worker
module under `app/services/`, relevant new tests, and `docs/ANTIGRAVITY_STATUS.md`.
If you need `app/main.py` or config changes, record this in the status file before editing;
Codex is not currently editing those files. Do not modify RAG, ingestion, retrieval, prompts,
provider settings, source policies, shared audit scripts, or the requirement documents.
Do not reset/stash/revert other changes. There are pre-existing user changes in this workspace.

## Validation and response

Run focused offline tests, then report the exact command and results in
`docs/ANTIGRAVITY_STATUS.md`, including changed files and any limitations.
Set status `done` or `needs_input` truthfully. Do not claim a LINE delivery occurred.
Codex will integrate/review your work and run the full offline suite and failure probes.

## Codex ownership (do not overlap)

Codex handles row/column/value grounding in `app/rag/evidence.py` and table consistency
helpers, associated tests, cache revision/mode correctness and latency evaluation.
Direct PDF remains experimental; do not switch it on or change the LLM provider/model.
