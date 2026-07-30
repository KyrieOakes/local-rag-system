"""Bounded background executor reliability tests."""

import threading
import unittest
from unittest.mock import patch

from app.core import background_tasks
from app.core.background_tasks import BoundedBackgroundExecutor


class BoundedBackgroundExecutorTest(unittest.TestCase):
    def test_default_capacity_comes_from_settings(self):
        started = threading.Event()
        release = threading.Event()

        def blocking_task():
            started.set()
            release.wait(timeout=2)

        with (
            patch.object(background_tasks.settings, "background_task_workers", 1),
            patch.object(
                background_tasks.settings,
                "background_task_queue_size",
                1,
            ),
        ):
            executor = BoundedBackgroundExecutor(
                thread_name_prefix="test-background"
            )

        try:
            first = executor.submit(blocking_task)
            self.assertIsNotNone(first)
            self.assertTrue(started.wait(timeout=1))
            queued = executor.submit(lambda: None)
            self.assertIsNotNone(queued)
            self.assertIsNone(executor.submit(lambda: None))
        finally:
            release.set()
            executor.shutdown(wait=True)

    def test_rejects_work_when_running_and_queue_capacity_is_full(self):
        executor = BoundedBackgroundExecutor(
            max_workers=1,
            max_queued_tasks=0,
            thread_name_prefix="test-background",
        )
        started = threading.Event()
        release = threading.Event()

        def blocking_task():
            started.set()
            release.wait(timeout=2)
            return "done"

        try:
            first = executor.submit(blocking_task)
            self.assertIsNotNone(first)
            self.assertTrue(started.wait(timeout=1))

            rejected = executor.submit(lambda: None)
            self.assertIsNone(rejected)

            release.set()
            self.assertEqual(first.result(timeout=1), "done")
        finally:
            release.set()
            executor.shutdown(wait=True)

    def test_graceful_shutdown_drains_accepted_work(self):
        executor = BoundedBackgroundExecutor(
            max_workers=1,
            max_queued_tasks=1,
            thread_name_prefix="test-background",
        )
        completed = []

        future = executor.submit(completed.append, "persisted")
        self.assertIsNotNone(future)
        executor.shutdown(wait=True)

        self.assertEqual(completed, ["persisted"])
        self.assertIsNone(executor.submit(lambda: None))


if __name__ == "__main__":
    unittest.main()
