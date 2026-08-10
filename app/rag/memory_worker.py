"""Durable single-worker executor for rolling conversation summaries."""

from __future__ import annotations

import atexit
import logging
import threading
import uuid
from collections.abc import Callable

from app.core.config import settings
from app.core.inference_coordinator import (
    InferenceCoordinator,
    inference_coordinator,
)
from app.rag.context_manager import (
    CompactionOutcome,
    CompactionStatus,
    compact_conversation_memory_once,
)
from app.rag.conversation_store import ConversationStore, get_conversation_store

logger = logging.getLogger(__name__)


class ConversationMemoryWorker:
    """Claim coalesced SQLite jobs and summarize outside the request path."""

    def __init__(
        self,
        *,
        store: ConversationStore | None = None,
        coordinator: InferenceCoordinator | None = None,
        compactor: Callable[[str, ConversationStore | None], CompactionOutcome]
        | None = None,
    ) -> None:
        self._store = store or get_conversation_store()
        self._coordinator = coordinator or inference_coordinator
        self._compactor = compactor or compact_conversation_memory_once
        self._worker_id = f"memory-{uuid.uuid4().hex}"
        self._stop_event = threading.Event()
        self._wake_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._lifecycle_lock = threading.Lock()

    def start(self) -> None:
        with self._lifecycle_lock:
            if self._thread is not None and self._thread.is_alive():
                return
            try:
                queued = self._store.backfill_memory_jobs()
                if queued:
                    logger.info(
                        "[MEMORY] backfilled %d durable compaction jobs",
                        queued,
                    )
            except Exception:
                logger.exception(
                    "[MEMORY] startup backfill failed; worker will retry existing jobs"
                )
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._run,
                name="conversation-memory-worker",
                daemon=True,
            )
            self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        with self._lifecycle_lock:
            thread = self._thread
            if thread is None:
                return
            self._stop_event.set()
            self._wake_event.set()
        thread.join(timeout=max(0.0, timeout))
        with self._lifecycle_lock:
            if not thread.is_alive():
                self._thread = None

    def notify(self) -> None:
        self._wake_event.set()

    def run_once(self) -> bool:
        """Process at most one due job; return whether a job was claimed."""
        if not self._coordinator.try_acquire_background():
            return False
        try:
            job = self._store.claim_due_memory_job(
                self._worker_id,
                lease_seconds=settings.memory_job_lease_seconds,
            )
            if job is None:
                return False

            conversation_id = job["conversation_id"]
            claimed_through = job["claimed_through_message_id"]
            try:
                outcome = self._compactor(conversation_id, self._store)
            except Exception:
                logger.exception(
                    "[MEMORY] unhandled compaction error conversation=%s",
                    conversation_id,
                )
                outcome = CompactionOutcome(
                    status=CompactionStatus.RETRYABLE_FAILURE,
                    error_code="worker_compaction_failed",
                )

            if outcome.status in {
                CompactionStatus.COMPACTED,
                CompactionStatus.NOT_NEEDED,
                CompactionStatus.CONVERSATION_DELETED,
            }:
                self._store.complete_memory_job(
                    conversation_id,
                    self._worker_id,
                    claimed_through,
                    needs_follow_up=outcome.needs_follow_up,
                )
            elif outcome.status == CompactionStatus.STALE:
                self._store.complete_memory_job(
                    conversation_id,
                    self._worker_id,
                    claimed_through,
                    needs_follow_up=True,
                )
            else:
                status = self._store.retry_memory_job(
                    conversation_id,
                    self._worker_id,
                    error_code=outcome.error_code or "compaction_failed",
                    max_attempts=settings.memory_job_max_attempts,
                    retry_base_seconds=settings.memory_job_retry_base_seconds,
                )
                if status == "dead":
                    logger.error(
                        "[MEMORY] job exhausted retries conversation=%s error=%s",
                        conversation_id,
                        outcome.error_code,
                    )
            return True
        finally:
            self._coordinator.release_background()

    def _run(self) -> None:
        logger.info("[MEMORY] worker started")
        while not self._stop_event.is_set():
            try:
                processed = self.run_once()
            except Exception:
                logger.exception("[MEMORY] worker iteration failed")
                processed = False
            if processed:
                continue
            self._wake_event.wait(settings.memory_job_poll_seconds)
            self._wake_event.clear()
        logger.info("[MEMORY] worker stopped")


_worker: ConversationMemoryWorker | None = None
_worker_lock = threading.Lock()


def start_memory_worker() -> None:
    global _worker
    if not settings.memory_worker_enabled:
        logger.info("[MEMORY] worker disabled by configuration")
        return
    with _worker_lock:
        if _worker is None:
            _worker = ConversationMemoryWorker()
        _worker.start()


def stop_memory_worker() -> None:
    with _worker_lock:
        worker = _worker
    if worker is not None:
        worker.stop()


def notify_memory_worker() -> None:
    with _worker_lock:
        worker = _worker
    if worker is not None:
        worker.notify()


atexit.register(stop_memory_worker)
