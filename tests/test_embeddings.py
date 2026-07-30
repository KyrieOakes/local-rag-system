"""Embedding client reuse and true-LRU cache tests."""

import unittest
from unittest.mock import patch

from langchain_openai import OpenAIEmbeddings

from app.rag import embeddings as embeddings_module
from app.rag.embeddings import CachedOpenAIEmbeddings


class EmbeddingCacheTest(unittest.TestCase):
    def setUp(self):
        with embeddings_module._cache_lock:
            embeddings_module._embedding_cache.clear()
            embeddings_module._cache_hits = 0
            embeddings_module._cache_misses = 0
        embeddings_module._build_embedding_model.cache_clear()

    @staticmethod
    def _model(name: str = "model-a", revision: str = ""):
        model = CachedOpenAIEmbeddings(
            model=name,
            base_url="http://127.0.0.1:1234/v1",
            api_key="test-placeholder",
            check_embedding_ctx_length=False,
        )
        model._localrag_revision = revision
        return model

    def test_repeated_query_hits_cache(self):
        model = self._model()
        with patch.object(
            OpenAIEmbeddings,
            "embed_query",
            return_value=[0.1, 0.2],
        ) as embed_mock:
            self.assertEqual(model.embed_query("same"), [0.1, 0.2])
            self.assertEqual(model.embed_query("same"), [0.1, 0.2])

        embed_mock.assert_called_once()
        self.assertEqual(embeddings_module._cache_hits, 1)
        self.assertEqual(embeddings_module._cache_misses, 1)

    def test_cache_identity_includes_model(self):
        first = self._model("model-a")
        second = self._model("model-b")
        with patch.object(
            OpenAIEmbeddings,
            "embed_query",
            return_value=[0.5],
        ) as embed_mock:
            first.embed_query("question")
            second.embed_query("question")

        self.assertEqual(embed_mock.call_count, 2)

    def test_cache_identity_includes_embedding_revision(self):
        first = self._model(revision="weights-v1")
        second = self._model(revision="weights-v2")
        with patch.object(
            OpenAIEmbeddings,
            "embed_query",
            return_value=[0.5],
        ) as embed_mock:
            first.embed_query("question")
            second.embed_query("question")

        self.assertEqual(embed_mock.call_count, 2)

    def test_recently_accessed_entry_is_not_evicted(self):
        model = self._model()
        with (
            patch.object(
                OpenAIEmbeddings,
                "embed_query",
                return_value=[0.5],
            ) as embed_mock,
            patch.object(embeddings_module, "_CACHE_MAX_SIZE", 2),
        ):
            model.embed_query("a")
            model.embed_query("b")
            model.embed_query("a")  # promote a to most-recently used
            model.embed_query("c")  # evicts b
            model.embed_query("b")  # miss again

        self.assertEqual(embed_mock.call_count, 4)


if __name__ == "__main__":
    unittest.main()
