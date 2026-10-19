"""Durable single-host inbox and worker for LINE webhook events.

The webhook verifies the signature, stores each text event keyed by `webhookEventId`
and returns 200 immediately; this worker then runs the (slow) answer pipeline and sends
the reply. Guarantees and limits, stated plainly:

* Uniqueness: `webhookEventId` is the primary key, so a redelivered or concurrently
  duplicated event is stored once, including across restarts (SQLite file).
* Once under normal operation: a row is claimed with a token + lease; only the holder of
  the current claim can advance it, so two workers never both send the same row.
* NOT exactly-once across arbitrary failures. The Reply API has no idempotency key. If the
  process dies, or a reply times out / returns 5xx, after the request may have reached
  LINE, the outcome is unknown. Such rows end in `unknown_outcome` and are never re-sent
  or pushed (a user may see no answer, but never a duplicate). Only the Push fallback
  carries an `X-Line-Retry-Key`, which LINE de-duplicates for 24h, so only pushes are
  retried after an unknown outcome.
* Single host: SQLite + leases are safe for several processes on one machine, not for
  several machines.
"""
import asyncio
import logging
import os
import sqlite3
import time
import uuid
from contextlib import closing
from pathlib import Path
from typing import Any

from app.services.ai_service import ask_ai
from app.services.line_service import (
    DELIVERED,
    PERMANENT,
    RETRYABLE,
    TOKEN_INVALID,
    UNKNOWN,
    send_push,
    send_reply,
    show_loading_animation,
)

logger = logging.getLogger(__name__)

PENDING = "pending"
PROCESSING = "processing"  # claimed; no send attempted yet (safe to redo)
SENDING = "sending"  # a send may be in flight (a crash here means unknown outcome)
DONE = "done"
FAILED_PERMANENT = "failed_permanent"
UNKNOWN_OUTCOME = "unknown_outcome"
TERMINAL_STATES = (DONE, FAILED_PERMANENT, UNKNOWN_OUTCOME)

DEFAULT_DB_PATH = "cache/line_inbox.sqlite3"
FRIENDLY_ERROR = (
    "ขออภัยครับ ระบบกำลังประสบปัญหาชั่วคราวในการประมวลผล "
    "กรุณาลองใหม่อีกครั้งในภายหลังครับ"
)
_RETRY_KEY_NAMESPACE = uuid.UUID("6f1c1c1e-5b0e-4a53-9d0e-0a1b2c3d4e5f")
# LINE's retry key lasts 24 hours from the first request. Keep a margin and
# never reuse one after a long outage, when it could deliver a duplicate.
PUSH_RETRY_WINDOW_SECONDS = 24 * 3600 - 60

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    event_id TEXT PRIMARY KEY,
    user_id TEXT,
    reply_token TEXT NOT NULL,
    text TEXT NOT NULL,
    state TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    answer TEXT,
    reply_dead INTEGER NOT NULL DEFAULT 0,
    push_started_at REAL,
    outcome TEXT,
    detail TEXT,
    claim_token TEXT,
    lease_until REAL,
    next_attempt_at REAL NOT NULL,
    received_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_state ON events (state, next_attempt_at);
"""


def retry_key_for(event_id: str) -> str:
    """Deterministic UUID so every push attempt for one event shares one retry key."""
    return str(uuid.uuid5(_RETRY_KEY_NAMESPACE, event_id))


class InboxStore:
    """SQLite persistence. One short-lived connection per call keeps it thread-safe."""

    def __init__(self, path: str | os.PathLike, lease_seconds: float = 120.0, max_attempts: int = 4):
        self.path = Path(path)
        self.lease_seconds = lease_seconds
        self.max_attempts = max_attempts
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(_SCHEMA)
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(events)")}
            if "push_started_at" not in columns:
                try:
                    conn.execute("ALTER TABLE events ADD COLUMN push_started_at REAL")
                except sqlite3.OperationalError as exc:
                    if "duplicate column" not in str(exc).lower():
                        raise

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA synchronous=FULL")  # an ACKed event must survive power loss
        return conn

    def add_events(self, events: list[dict[str, Any]]) -> int:
        """Persist events atomically. Returns how many were new (duplicates are ignored)."""
        now = time.time()
        added = 0
        with closing(self._connect()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                for event in events:
                    cursor = conn.execute(
                        "INSERT OR IGNORE INTO events (event_id, user_id, reply_token, text, state,"
                        " next_attempt_at, received_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (event["event_id"], event.get("user_id"), event["reply_token"], event["text"],
                         PENDING, now, now, now),
                    )
                    added += cursor.rowcount
                conn.execute("COMMIT")
            except BaseException:
                conn.execute("ROLLBACK")
                raise
        return added

    def claim(self) -> sqlite3.Row | None:
        now = time.time()
        with closing(self._connect()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                row = conn.execute(
                    "SELECT event_id FROM events WHERE state = ? AND next_attempt_at <= ?"
                    " ORDER BY received_at LIMIT 1", (PENDING, now)).fetchone()
                if row is None:
                    conn.execute("COMMIT")
                    return None
                token = uuid.uuid4().hex
                conn.execute(
                    "UPDATE events SET state = ?, claim_token = ?, lease_until = ?,"
                    " attempts = attempts + 1, updated_at = ? WHERE event_id = ?",
                    (PROCESSING, token, now + self.lease_seconds, now, row["event_id"]))
                claimed = conn.execute("SELECT * FROM events WHERE event_id = ?", (row["event_id"],)).fetchone()
                conn.execute("COMMIT")
                return claimed
            except BaseException:
                conn.execute("ROLLBACK")
                raise

    def reap(self) -> tuple[int, int]:
        """Recover rows whose worker vanished. Returns (requeued, marked_unknown)."""
        now = time.time()
        with closing(self._connect()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                requeued = conn.execute(
                    "UPDATE events SET state = ?, claim_token = NULL, lease_until = NULL, updated_at = ?,"
                    " next_attempt_at = ? WHERE state = ? AND lease_until < ?",
                    (PENDING, now, now, PROCESSING, now)).rowcount
                unknown = conn.execute(
                    "UPDATE events SET state = ?, outcome = 'unknown', detail = 'lease_expired_during_send',"
                    " reply_token = '', text = '', answer = NULL, claim_token = NULL, lease_until = NULL,"
                    " updated_at = ? WHERE state = ? AND lease_until < ?",
                    (UNKNOWN_OUTCOME, now, SENDING, now)).rowcount
                conn.execute("COMMIT")
            except BaseException:
                conn.execute("ROLLBACK")
                raise
        return requeued, unknown

    def _advance(self, sql: str, params: tuple, event_id: str, token: str, states: tuple[str, ...]) -> bool:
        placeholders = ",".join("?" for _ in states)
        with closing(self._connect()) as conn:
            cursor = conn.execute(
                f"UPDATE events SET {sql}, updated_at = ? WHERE event_id = ? AND claim_token = ?"
                f" AND state IN ({placeholders})",
                (*params, time.time(), event_id, token, *states))
            return cursor.rowcount == 1

    def set_answer(self, event_id: str, token: str, answer: str) -> bool:
        return self._advance("answer = ?", (answer,), event_id, token, (PROCESSING,))

    def begin_send(self, event_id: str, token: str) -> bool:
        """Mark that a send may now be in flight. After this, a lost worker means unknown."""
        return self._advance("state = ?, lease_until = ?", (SENDING, time.time() + self.lease_seconds),
                             event_id, token, (PROCESSING,))

    def begin_push(self, event_id: str, token: str) -> bool:
        return self._advance("reply_dead = 1, push_started_at = COALESCE(push_started_at, ?)",
            (time.time(),), event_id, token, (SENDING,))

    def finish(self, event_id: str, token: str, state: str, outcome: str, detail: str = "") -> bool:
        assert state in TERMINAL_STATES
        # Drop the user's text, reply token and answer once nothing more will be sent.
        return self._advance(
            "state = ?, outcome = ?, detail = ?, reply_token = '', text = '', answer = NULL,"
            " claim_token = NULL, lease_until = NULL",
            (state, outcome, detail), event_id, token, (PROCESSING, SENDING))

    def retry_later(self, event_id: str, token: str, delay: float, detail: str, reply_dead: bool = False) -> bool:
        return self._advance(
            "state = ?, next_attempt_at = ?, detail = ?, claim_token = NULL, lease_until = NULL,"
            " reply_dead = MAX(reply_dead, ?)",
            (PENDING, time.time() + delay, detail, int(reply_dead)), event_id, token, (PROCESSING, SENDING))

    def get(self, event_id: str) -> dict[str, Any] | None:
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT * FROM events WHERE event_id = ?", (event_id,)).fetchone()
        return dict(row) if row else None

    def count(self, state: str | None = None) -> int:
        with closing(self._connect()) as conn:
            if state is None:
                return conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
            return conn.execute("SELECT COUNT(*) FROM events WHERE state = ?", (state,)).fetchone()[0]

    def health_snapshot(self) -> dict[str, int]:
        """Bounded local probe; do not expose messages, tokens or user identifiers."""
        with closing(sqlite3.connect(self.path, timeout=1)) as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("UPDATE events SET updated_at = updated_at WHERE 0")
            result = dict(conn.execute("SELECT state, COUNT(*) FROM events GROUP BY state").fetchall())
            conn.rollback()  # prove write access without changing any user data
            return result

    def prune(self, older_than_seconds: float) -> int:
        """Delete finished rows old enough that LINE will no longer redeliver them."""
        cutoff = time.time() - older_than_seconds
        placeholders = ",".join("?" for _ in TERMINAL_STATES)
        with closing(self._connect()) as conn:
            return conn.execute(
                f"DELETE FROM events WHERE state IN ({placeholders}) AND updated_at < ?",
                (*TERMINAL_STATES, cutoff)).rowcount


class LineInbox:
    """Owns the store and the background worker; lives on `app.state.line_inbox`."""

    def __init__(self, store: InboxStore, concurrency: int = 3, poll_seconds: float = 1.0,
                 shutdown_grace: float = 5.0, backoff: tuple[float, ...] = (2.0, 10.0, 30.0)):
        self.store = store
        self.concurrency = max(1, concurrency)
        self.poll_seconds = poll_seconds
        self.shutdown_grace = shutdown_grace
        self.backoff = backoff
        self._stop: asyncio.Event | None = None
        self._wake: asyncio.Event | None = None
        self._runner: asyncio.Task | None = None
        self._running: set[asyncio.Task] = set()

    @property
    def is_running(self) -> bool:
        return self._runner is not None and not self._runner.done() and not self._stop.is_set()

    async def start(self) -> None:
        requeued, unknown = await asyncio.to_thread(self.store.reap)
        await asyncio.to_thread(self.store.prune, 30 * 24 * 3600)
        if requeued or unknown:
            logger.warning("LINE inbox recovery: %d re-queued, %d marked unknown_outcome", requeued, unknown)
        self._stop, self._wake = asyncio.Event(), asyncio.Event()
        self._runner = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._runner is None:
            return
        self._stop.set()
        self._wake.set()
        await self._runner
        if self._running:
            _, pending = await asyncio.wait(self._running, timeout=self.shutdown_grace)
            for task in pending:
                task.cancel()  # row keeps its lease and is recovered by the next start
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
        self._runner = None

    def notify(self) -> None:
        if self._wake is not None:
            self._wake.set()

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                await asyncio.to_thread(self.store.reap)
                while len(self._running) < self.concurrency and not self._stop.is_set():
                    row = await asyncio.to_thread(self.store.claim)
                    if row is None:
                        break
                    task = asyncio.create_task(self._process(row))
                    self._running.add(task)
                    task.add_done_callback(self._task_done)
            except Exception:
                logger.exception("LINE inbox loop error; will retry")
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=self.poll_seconds)
            except asyncio.TimeoutError:
                pass
            self._wake.clear()

    def _task_done(self, task: asyncio.Task) -> None:
        self._running.discard(task)
        if self._wake is not None:
            self._wake.set()  # a slot freed up: claim the next row without waiting for the poll

    async def _process(self, row) -> None:
        try:
            await self._deliver(row)
        except asyncio.CancelledError:
            raise
        except Exception:
            # The lease expires and reap() re-queues it; attempts cap a poison row.
            logger.exception("LINE inbox worker error for event %s", row["event_id"])

    def _delay(self, attempts: int) -> float:
        return self.backoff[min(max(attempts, 1) - 1, len(self.backoff) - 1)]

    async def _deliver(self, row) -> None:
        store, event_id, token = self.store, row["event_id"], row["claim_token"]
        attempts, user_id = row["attempts"], row["user_id"]

        if attempts > store.max_attempts:
            store.finish(event_id, token, FAILED_PERMANENT, "attempts_exhausted", f"claims={attempts}")
            return

        answer = row["answer"]
        if answer is None:
            loading = asyncio.create_task(asyncio.to_thread(show_loading_animation, user_id, loading_seconds=20))
            loading.add_done_callback(lambda t: t.cancelled() or t.exception())  # best effort only
            try:
                answer = await asyncio.to_thread(ask_ai, row["text"])
            except Exception as e:
                logger.error("Error processing user query in ask_ai: %s", type(e).__name__)
                answer = FRIENDLY_ERROR
            if not await asyncio.to_thread(store.set_answer, event_id, token, answer):
                return  # claim was lost to lease expiry; the newer claimant owns the row

        if not await asyncio.to_thread(store.begin_send, event_id, token):
            return

        result = None
        if not row["reply_dead"]:
            result = await asyncio.to_thread(send_reply, row["reply_token"], answer)
            if result.outcome == DELIVERED:
                store.finish(event_id, token, DONE, "delivered_reply", result.detail)
                return
            if result.outcome == UNKNOWN:
                # The reply may have been delivered. Pushing now could duplicate it.
                store.finish(event_id, token, UNKNOWN_OUTCOME, "reply_unknown", result.detail)
                return
            if result.outcome == PERMANENT:
                store.finish(event_id, token, FAILED_PERMANENT, "reply_permanent", result.detail)
                return
            if result.outcome == RETRYABLE:
                self._retry_or_fail(row, result, reply_dead=False)
                return
            assert result.outcome == TOKEN_INVALID  # verified expired/used: LINE did not send it

        if (row["push_started_at"] is not None
                and time.time() - row["push_started_at"] >= PUSH_RETRY_WINDOW_SECONDS):
            store.finish(event_id, token, UNKNOWN_OUTCOME, "push_retry_window_expired")
            return
        if not await asyncio.to_thread(store.begin_push, event_id, token):
            return
        push = await asyncio.to_thread(send_push, user_id, answer, retry_key_for(event_id))
        if push.outcome == DELIVERED:
            store.finish(event_id, token, DONE, "delivered_push", push.detail)
        elif push.outcome == PERMANENT:
            store.finish(event_id, token, FAILED_PERMANENT, "push_permanent", push.detail)
        else:  # RETRYABLE, or UNKNOWN: safe to retry only because the push carries a retry key
            self._retry_or_fail(row, push, reply_dead=True)

    def _retry_or_fail(self, row, result, reply_dead: bool) -> None:
        store, event_id, token, attempts = self.store, row["event_id"], row["claim_token"], row["attempts"]
        if attempts >= store.max_attempts:
            if result.outcome == UNKNOWN:
                store.finish(event_id, token, UNKNOWN_OUTCOME, "push_unknown", result.detail)
            else:
                store.finish(event_id, token, FAILED_PERMANENT, "retries_exhausted", result.detail)
            return
        store.retry_later(event_id, token, self._delay(attempts), result.detail, reply_dead=reply_dead)


def build_inbox_from_env() -> LineInbox:
    path = os.getenv("LINE_INBOX_DB_PATH", "").strip() or DEFAULT_DB_PATH
    store = InboxStore(
        path,
        lease_seconds=float(os.getenv("LINE_INBOX_LEASE_SECONDS", "120")),
        max_attempts=int(os.getenv("LINE_INBOX_MAX_ATTEMPTS", "4")),
    )
    return LineInbox(store, concurrency=int(os.getenv("LINE_WORKER_CONCURRENCY", "3")))
