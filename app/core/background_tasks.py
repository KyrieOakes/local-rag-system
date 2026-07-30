"""Bounded background execution for best-effort post-response work.

The RAG service uses this module for query logging, conversation persistence,
and memory compaction.  A fixed-size executor avoids creating two daemon
threads per request, while the semaphore keeps the executor's otherwise
unbounded work queue under control.
"""

from __future__ import annotations

import atexit
import logging
import threading
from concurrent.futures import CancelledError, Future, ThreadPoolExecutor
from typing import Any, Callable

from app.core.config import settings

logger = logging.getLogger(__name__)

class BoundedBackgroundExecutor:
    """A fixed worker pool with bounded running + queued task capacity."""

    def __init__(
        self,
        max_workers: int | None = None,
        max_queued_tasks: int | None = None,
        thread_name_prefix: str = "rag-background",
    ):
        if max_workers is None:
            max_workers = settings.background_task_workers
        if max_queued_tasks is None:
            max_queued_tasks = settings.background_task_queue_size
        if max_workers < 1:
            raise ValueError("max_workers must be at least 1")
        if max_queued_tasks < 0:
            raise ValueError("max_queued_tasks cannot be negative")

        self._executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix=thread_name_prefix,
        )
        self._capacity = threading.BoundedSemaphore(
            max_workers + max_queued_tasks
        )
        self._state_lock = threading.Lock()
        self._closed = False

    def submit(
        self,
        function: Callable[..., Any],
        /,
        *args: Any,
        **kwargs: Any,
    ) -> Future | None:
        """Submit without blocking; return ``None`` when capacity is exhausted."""
        if not self._capacity.acquire(blocking=False):
            logger.error(
                "Background task queue is full; rejected task %s",
                getattr(function, "__name__", repr(function)),
            )
            return None

        with self._state_lock:
            if self._closed:
                self._capacity.release()
                logger.warning(
                    "Background executor is closed; rejected task %s",
                    getattr(function, "__name__", repr(function)),
                )
                return None
            try:
                future = self._executor.submit(function, *args, **kwargs)
            except RuntimeError:
                self._capacity.release()
                logger.exception("Failed to submit background task")
                return None

        future.add_done_callback(self._task_completed)
        return future

    def _task_completed(self, future: Future) -> None:
        self._capacity.release()
        try:
            error = future.exception()
        except CancelledError:
            return
        if error is not None:
            logger.error(
                "Background task failed: %s",
                error,
                exc_info=(type(error), error, error.__traceback__),
            )

    def shutdown(self, wait: bool = True) -> None:
        """Stop accepting work and optionally drain all accepted tasks."""
        with self._state_lock:
            if self._closed:
                return
            self._closed = True
        self._executor.shutdown(wait=wait, cancel_futures=not wait)


_executor: BoundedBackgroundExecutor | None = None
_executor_lock = threading.Lock()


def get_background_executor() -> BoundedBackgroundExecutor:
    """Return the process-wide executor, creating it lazily."""
    global _executor
    if _executor is None:
        with _executor_lock:
            if _executor is None:
                _executor = BoundedBackgroundExecutor()
    return _executor


def submit_background_task(
    function: Callable[..., Any],
    /,
    *args: Any,
    **kwargs: Any,
) -> Future | None:
    """Submit post-response work to the shared bounded executor."""
    return get_background_executor().submit(function, *args, **kwargs)


def shutdown_background_tasks(wait: bool = True) -> None:
    """Gracefully drain and dispose of the shared executor."""
    global _executor
    with _executor_lock:
        executor = _executor
        _executor = None
    if executor is not None:
        executor.shutdown(wait=wait)


atexit.register(shutdown_background_tasks)
