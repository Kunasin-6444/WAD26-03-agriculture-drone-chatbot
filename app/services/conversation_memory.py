from __future__ import annotations

import threading
import time
from collections import deque

MAX_TURNS = 3
TTL_SECONDS = 30 * 60

_lock = threading.Lock()
_store: dict[str, deque[tuple[str, str, float]]] = {}


def get_history(user_id: str | None) -> list[tuple[str, str]]:
    """Return recent (question, answer) turns for a user, dropping expired ones."""
    if not user_id:
        return []
    cutoff = time.time() - TTL_SECONDS
    with _lock:
        turns = _store.get(user_id)
        if not turns:
            return []
        while turns and turns[0][2] < cutoff:
            turns.popleft()
        return [(q, a) for q, a, _ in turns]


def add_turn(user_id: str | None, question: str, answer: str) -> None:
    if not user_id:
        return
    with _lock:
        _store.setdefault(user_id, deque(maxlen=MAX_TURNS)).append(
            (question, answer, time.time())
        )
