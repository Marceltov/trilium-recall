"""Remembers, per Claude Code session, which notes were already injected, so they are not sent again."""

import threading
import time


class SessionMemory:
    def __init__(self, ttl_seconds: int = 43200):
        self.ttl = ttl_seconds
        self._seen: dict[str, tuple[float, set[str]]] = {}  # session → (last activity, note ids)
        self._lock = threading.Lock()

    def peek(self, session_id: str | None, note_ids: list[str]) -> list[str]:
        """The ids not injected in this session yet, in order."""
        if not session_id:
            return list(note_ids)
        with self._lock:
            self.sweep()
            _, seen = self._seen.get(session_id, (0.0, set()))
            return [n for n in note_ids if n not in seen]

    def record(self, session_id: str | None, note_ids: list[str]) -> None:
        """Mark ids as injected in this session."""
        if not session_id:
            return
        with self._lock:
            _, seen = self._seen.get(session_id, (0.0, set()))
            self._seen[session_id] = (time.time(), seen | set(note_ids))

    def fresh(self, session_id: str | None, note_ids: list[str]) -> list[str]:
        """peek, then record what it returned."""
        new = self.peek(session_id, note_ids)
        self.record(session_id, new)
        return new

    def sweep(self, now: float | None = None) -> None:
        now = time.time() if now is None else now
        for sid in [s for s, (last, _) in self._seen.items() if now - last > self.ttl]:
            del self._seen[sid]
