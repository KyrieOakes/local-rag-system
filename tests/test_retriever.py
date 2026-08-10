"""Dense, BM25, and Qdrant fusion retrieval regression tests."""

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from langchain_core.documents import Document
from qdrant_client import models

from app.rag import retriever


def _point(*, point_id="point-1", score=0.75, content="chunk", metadata=None):
    return SimpleNamespace(
        id=point_id,
        score=score,
        payload={
            "page_content": content,
            "metadata": metadata or {"source": "guide.md"},
        },
    )


class RetrievalModeTest(unittest.TestCase):
    @patch("app.rag.retriever.get_vectorstore")
    def test_legacy_dense_mode_keeps_langchain_vectorstore_path(self, store_factory):
        expected = [(Document(page_content="dense"), 0.8)]
        store_factory.return_value.similarity_search_with_score.return_value = expected

        with patch.object(retriever.settings, "retrieval_index_schema", "dense"):
            result = retriever.retrieve_relevant_documents(
                "query",
                top_k=3,
                mode="dense",
            )

        self.assertEqual(result, expected)
        store_factory.return_value.similarity_search_with_score.assert_called_once_with(
            query="query",
            k=3,
        )

    @patch("app.rag.retriever.get_qdrant_client")
    @patch("app.rag.retriever.get_embedding_model")
    def test_named_dense_mode_queries_hybrid_collection(
        self,
        embedding_factory,
        client_factory,
    ):
        embedding_factory.return_value.embed_query.return_value = [0.1, 0.2]
        client_factory.return_value.query_points.return_value = SimpleNamespace(
            points=[_point(content="named dense")]
        )

        with (
            patch.object(retriever.settings, "retrieval_index_schema", "hybrid"),
            patch.object(retriever.settings, "dense_vector_name", "dense-v"),
        ):
            result = retriever.retrieve_relevant_documents(
                "query",
                top_k=2,
                mode="dense",
            )

        self.assertEqual(result[0][0].page_content, "named dense")
        kwargs = client_factory.return_value.query_points.call_args.kwargs
        self.assertEqual(kwargs["query"], [0.1, 0.2])
        self.assertEqual(kwargs["using"], "dense-v")
        self.assertEqual(kwargs["limit"], 2)

    @patch("app.rag.retriever.get_qdrant_client")
    def test_bm25_mode_uses_shared_multilingual_configuration(self, client_factory):
        client_factory.return_value.query_points.return_value = SimpleNamespace(
            points=[_point(content="lexical")]
        )

        with (
            patch.object(retriever.settings, "retrieval_index_schema", "hybrid"),
            patch.object(retriever.settings, "sparse_vector_name", "lexical"),
            patch.object(retriever.settings, "bm25_tokenizer", "multilingual"),
            patch.object(retriever.settings, "bm25_language", "none"),
        ):
            result = retriever.retrieve_relevant_documents(
                "村上春树",
                mode="bm25",
            )

        self.assertEqual(result[0][0].page_content, "lexical")
        kwargs = client_factory.return_value.query_points.call_args.kwargs
        self.assertEqual(kwargs["using"], "lexical")
        self.assertIsInstance(kwargs["query"], models.Document)
        self.assertEqual(
            kwargs["query"].options.tokenizer,
            models.TokenizerType.MULTILINGUAL,
        )
        self.assertEqual(kwargs["query"].options.language, "none")

    @patch("app.rag.retriever.get_qdrant_client")
    @patch("app.rag.retriever.get_embedding_model")
    def test_hybrid_mode_prefetches_both_branches_and_uses_rrf(
        self,
        embedding_factory,
        client_factory,
    ):
        embedding_factory.return_value.embed_query.return_value = [0.2, 0.4]
        client_factory.return_value.query_points.return_value = SimpleNamespace(
            points=[_point(score=0.032, metadata={"chunk_index": 2})]
        )

        with (
            patch.object(retriever.settings, "retrieval_index_schema", "hybrid"),
            patch.object(retriever.settings, "dense_vector_name", "dense-v"),
            patch.object(retriever.settings, "sparse_vector_name", "sparse-v"),
        ):
            result = retriever.retrieve_relevant_documents(
                "hybrid query",
                top_k=5,
                mode="hybrid",
                hybrid_fusion="rrf",
                hybrid_prefetch_top_n=12,
            )

        self.assertEqual(result[0][1], 0.032)
        kwargs = client_factory.return_value.query_points.call_args.kwargs
        self.assertIsInstance(kwargs["query"], models.RrfQuery)
        self.assertEqual(kwargs["limit"], 5)
        self.assertIsNone(kwargs["using"])
        self.assertEqual(len(kwargs["prefetch"]), 2)
        self.assertEqual(kwargs["prefetch"][0].using, "dense-v")
        self.assertEqual(kwargs["prefetch"][0].query, [0.2, 0.4])
        self.assertEqual(kwargs["prefetch"][0].limit, 12)
        self.assertEqual(kwargs["prefetch"][1].using, "sparse-v")
        self.assertIsInstance(kwargs["prefetch"][1].query, models.Document)

    def test_bm25_rejects_dense_only_collection_schema(self):
        with patch.object(retriever.settings, "retrieval_index_schema", "dense"):
            with self.assertRaisesRegex(ValueError, "requires"):
                retriever.retrieve_relevant_documents("query", mode="bm25")

    def test_dbsf_query_is_explicit(self):
        query = retriever._fusion_query("dbsf")
        self.assertIsInstance(query, models.FusionQuery)
        self.assertEqual(query.fusion, models.Fusion.DBSF)

    def test_missing_payload_is_rejected(self):
        malformed = SimpleNamespace(
            id="bad",
            score=0.1,
            payload={"metadata": {}},
        )
        with self.assertRaisesRegex(ValueError, "expected RAG payload"):
            retriever._scored_points_to_results([malformed])


if __name__ == "__main__":
    unittest.main()
