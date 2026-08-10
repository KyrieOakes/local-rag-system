"""Bounded concurrent embedding request tests."""

from __future__ import annotations

import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.rag.ingestion.batch_embedder import embed_texts


class _ConcurrentEmbeddings:
    def __init__(self) -> None:
        self.barrier = threading.Barrier(2)
        self.lock = threading.Lock()
        self.active = 0
        self.max_active = 0

    def create(self, *, model, input):
        del model
        with self.lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            self.barrier.wait(timeout=2)
            return SimpleNamespace(
                data=[
                    SimpleNamespace(index=index, embedding=[float(text)])
                    for index, text in reversed(list(enumerate(input)))
                ]
            )
        finally:
            with self.lock:
                self.active -= 1


class BatchEmbedderConcurrencyTest(unittest.TestCase):
    def test_batches_overlap_but_results_keep_input_order(self):
        embeddings_api = _ConcurrentEmbeddings()
        client = SimpleNamespace(
            embeddings=embeddings_api,
            close=lambda: None,
        )

        with (
            patch("app.rag.ingestion.batch_embedder._get_client", return_value=client),
            patch(
                "app.rag.ingestion.batch_embedder.settings.embedding_max_concurrency",
                2,
            ),
        ):
            result = embed_texts(["0", "1", "2", "3"], batch_size=2)

        self.assertEqual(result, [[0.0], [1.0], [2.0], [3.0]])
        self.assertEqual(embeddings_api.max_active, 2)

    def test_invalid_response_indexes_are_rejected(self):
        client = SimpleNamespace(
            embeddings=SimpleNamespace(
                create=lambda **_kwargs: SimpleNamespace(
                    data=[SimpleNamespace(index=1, embedding=[0.1])]
                )
            ),
            close=lambda: None,
        )

        with (
            patch("app.rag.ingestion.batch_embedder._get_client", return_value=client),
            patch(
                "app.rag.ingestion.batch_embedder.settings.embedding_max_concurrency",
                1,
            ),
            self.assertRaisesRegex(ValueError, "invalid batch indexes"),
        ):
            embed_texts(["only"], batch_size=1)


if __name__ == "__main__":
    unittest.main()
