"""Coordinate interactive and background LLM work in one local process."""

from __future__ import annotations

import threading
from contextlib import contextmanager


class InferenceCoordinator:
    """Let memory work start only while no user query is active."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._interactive_requests = 0
        self._background_active = False

    @contextmanager
    def interactive(self):
        with self._lock:
            self._interactive_requests += 1
        try:
            yield
        finally:
            with self._lock:
                self._interactive_requests = max(
                    0,
                    self._interactive_requests - 1,
                )

    def try_acquire_background(self) -> bool:
        """Reserve the single background slot without blocking a user request."""
        with self._lock:
            if self._interactive_requests > 0 or self._background_active:
                return False
            self._background_active = True
            return True

    def release_background(self) -> None:
        with self._lock:
            self._background_active = False

    def snapshot(self) -> dict[str, int | bool]:
        """Expose minimal state for deterministic tests and diagnostics."""
        with self._lock:
            return {
                "interactive_requests": self._interactive_requests,
                "background_active": self._background_active,
            }


inference_coordinator = InferenceCoordinator()
