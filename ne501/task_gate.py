"""Invalidate queued work when a STOP ALL request takes precedence."""
from __future__ import annotations

from threading import Lock
from typing import Optional


class TaskGate:
    def __init__(self) -> None:
        self._lock = Lock()
        self._generation = 0
        self._stopping = False

    def ordinary_ticket(self) -> Optional[int]:
        with self._lock:
            return None if self._stopping else self._generation

    def begin_stop(self) -> Optional[int]:
        with self._lock:
            if self._stopping:
                return None
            self._generation += 1
            self._stopping = True
            return self._generation

    def is_current(self, ticket: int) -> bool:
        with self._lock:
            return ticket == self._generation

    def end_stop(self, ticket: int) -> None:
        with self._lock:
            if self._stopping and ticket == self._generation:
                self._stopping = False
