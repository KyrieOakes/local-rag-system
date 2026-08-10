"""Durable conversation-memory job and worker tests."""

import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from app.core.config import settings
from app.core.inference_coordinator import InferenceCoordinator
from app.rag.context_manager import CompactionOutcome, CompactionStatus
from app.rag.conversation_store import ConversationStore
from app.rag.memory_worker import ConversationMemoryWorker


class ConversationMemoryJobStoreTest(unittest.TestCase):
    def _store(self, directory: str) -> ConversationStore:
        return ConversationStore(Path(directory) / "conversations.db")

    def test_exchange_and_memory_job_commit_atomically(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = self._store(tmp_dir)
            with (
                patch.object(settings, "memory_job_debounce_seconds", 0),
                patch.object(
                    store,
                    "_upsert_memory_job",
                    side_effect=RuntimeError("outbox unavailable"),
                ),
            ):
                saved = store.save_exchange(
                    "c1",
                    "question",
                    "answer",
                    turn_id="turn-1",
                )

            self.assertFalse(saved)
            self.assertIsNone(store.get_conversation("c1"))
            self.assertIsNone(store.get_memory_job("c1"))

    def test_repeated_saves_coalesce_to_latest_assistant_message(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = self._store(tmp_dir)
            with patch.object(settings, "memory_job_debounce_seconds", 0):
                self.assertTrue(
                    store.save_exchange(
                        "c1", "q1", "a1", turn_id="turn-1"
                    )
                )
                self.assertTrue(
                    store.save_exchange(
                        "c1", "q2", "a2", turn_id="turn-2"
                    )
                )

            job = store.get_memory_job("c1")
            self.assertEqual(job["status"], "pending")
            self.assertEqual(job["requested_through_message_id"], 4)

    def test_new_exchange_during_lease_is_not_lost_on_completion(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = self._store(tmp_dir)
            with patch.object(settings, "memory_job_debounce_seconds", 0):
                store.save_exchange("c1", "q1", "a1", turn_id="turn-1")
                claim = store.claim_due_memory_job(
                    "worker-1",
                    lease_seconds=30,
                    now=time.time() + 1,
                )
                store.save_exchange("c1", "q2", "a2", turn_id="turn-2")

            acknowledged = store.complete_memory_job(
                "c1",
                "worker-1",
                claim["claimed_through_message_id"],
            )

            self.assertTrue(acknowledged)
            job = store.get_memory_job("c1")
            self.assertEqual(job["status"], "pending")
            self.assertEqual(job["requested_through_message_id"], 4)

    def test_expired_lease_can_be_reclaimed(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = self._store(tmp_dir)
            with patch.object(settings, "memory_job_debounce_seconds", 0):
                store.save_exchange("c1", "q1", "a1", turn_id="turn-1")
            base = time.time() + 1
            first = store.claim_due_memory_job(
                "worker-1",
                lease_seconds=10,
                now=base,
            )
            self.assertIsNotNone(first)
            self.assertIsNone(
                store.claim_due_memory_job(
                    "worker-2",
                    lease_seconds=10,
                    now=base + 5,
                )
            )

            reclaimed = store.claim_due_memory_job(
                "worker-2",
                lease_seconds=10,
                now=base + 11,
            )
            self.assertEqual(reclaimed["lease_owner"], "worker-2")
            self.assertEqual(reclaimed["attempts"], 2)

    def test_conversation_delete_cascades_to_memory_job(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = self._store(tmp_dir)
            with patch.object(settings, "memory_job_debounce_seconds", 0):
                store.save_exchange("c1", "q1", "a1", turn_id="turn-1")
            self.assertIsNotNone(store.get_memory_job("c1"))

            self.assertTrue(store.delete_conversation("c1"))
            self.assertIsNone(store.get_memory_job("c1"))


class ConversationMemoryWorkerTest(unittest.TestCase):
    def test_interactive_query_prevents_worker_from_claiming(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = ConversationStore(Path(tmp_dir) / "conversations.db")
            with patch.object(settings, "memory_job_debounce_seconds", 0):
                store.save_exchange("c1", "q1", "a1", turn_id="turn-1")
            coordinator = InferenceCoordinator()
            worker = ConversationMemoryWorker(
                store=store,
                coordinator=coordinator,
                compactor=lambda _conversation_id, _store: CompactionOutcome(
                    status=CompactionStatus.NOT_NEEDED
                ),
            )

            with coordinator.interactive():
                self.assertFalse(worker.run_once())
                self.assertEqual(store.get_memory_job("c1")["status"], "pending")

            self.assertTrue(worker.run_once())
            self.assertIsNone(store.get_memory_job("c1"))

    def test_retryable_failure_is_persisted_for_later_retry(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = ConversationStore(Path(tmp_dir) / "conversations.db")
            with patch.object(settings, "memory_job_debounce_seconds", 0):
                store.save_exchange("c1", "q1", "a1", turn_id="turn-1")
            worker = ConversationMemoryWorker(
                store=store,
                coordinator=InferenceCoordinator(),
                compactor=lambda _conversation_id, _store: CompactionOutcome(
                    status=CompactionStatus.RETRYABLE_FAILURE,
                    error_code="invalid_summary_json",
                ),
            )

            with (
                patch.object(settings, "memory_job_max_attempts", 3),
                patch.object(settings, "memory_job_retry_base_seconds", 1),
            ):
                self.assertTrue(worker.run_once())

            job = store.get_memory_job("c1")
            self.assertEqual(job["status"], "retry")
            self.assertEqual(job["attempts"], 1)
            self.assertEqual(job["last_error_code"], "invalid_summary_json")


if __name__ == "__main__":
    unittest.main()
