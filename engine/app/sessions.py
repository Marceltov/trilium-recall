"""Remembers, per Claude Code session, which notes were already injected, so they are not sent again."""

import threading
import time


class SessionMemory:
    def __init__(self, ttl_seconds: int = 43200):
        self.ttl = ttl_seconds
        self._seen: dict[str, tuple[float, set[str]]] = {}  # session → (last activity, note ids)
        self._lock = threading.Lock()

    def fresh(self, session_id: str | None, note_ids: list[str]) -> list[str]:
        """The ids not injected in this session yet, in order; records them as injected."""
        if not session_id:
            return list(note_ids)
        with self._lock:
            self.sweep()
            _, seen = self._seen.get(session_id, (0.0, set()))
            new = [n for n in note_ids if n not in seen]
            self._seen[session_id] = (time.time(), seen | set(new))
            return new

    def sweep(self, now: float | None = None) -> None:
        now = time.time() if now is None else now
        for sid in [s for s, (last, _) in self._seen.items() if now - last > self.ttl]:
            del self._seen[sid]
