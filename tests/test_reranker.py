"""Regression tests for explicit vector-score reranker inputs."""

import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from langchain_core.documents import Document

from app.rag.reranker import (
    CrossEncoderReranker,
    HybridFusionReranker,
    NoOpReranker,
    RerankCandidate,
    build_rerank_candidates,
)


class _Scores(list):
    def tolist(self):
        return list(self)


class _FakeCrossEncoderModel:
    def __init__(self, scores):
        self._scores = scores

    def predict(self, pairs, show_progress_bar=False):
        return _Scores(self._scores)


class RerankerTest(unittest.TestCase):
    def test_candidate_builder_preserves_tuple_vector_scores(self):
        document = Document(page_content="retrieved")

        candidates = build_rerank_candidates([(document, 0.73)])

        self.assertEqual(candidates, [RerankCandidate(document, 0.73)])

    def test_noop_returns_explicit_score_not_document_metadata_score(self):
        document = Document(
            page_content="retrieved",
            metadata={"score": 999.0},
        )

        result = NoOpReranker().rerank(
            query="query",
            candidates=[RerankCandidate(document, 0.73)],
            top_k=1,
        )

        self.assertEqual(result[0][1], 0.73)
        self.assertEqual(result[0][0].metadata["vector_score"], 0.73)
        self.assertEqual(result[0][0].metadata["score"], 0.73)

    def test_hybrid_formula_uses_explicit_vector_score(self):
        vector_first = Document(
            page_content="unrelated text",
            metadata={"name": "vector", "score": -100.0},
        )
        keyword_first = Document(
            page_content="keyword",
            metadata={"name": "keyword", "score": 100.0},
        )
        middle = Document(
            page_content="other",
            metadata={"name": "middle"},
        )
        candidates = [
            RerankCandidate(vector_first, 0.9),
            RerankCandidate(keyword_first, 0.1),
            RerankCandidate(middle, 0.5),
        ]

        result = HybridFusionReranker(alpha=0.7).rerank(
            query="keyword",
            candidates=candidates,
            top_k=2,
        )

        self.assertEqual([doc.metadata["name"] for doc, _ in result], ["vector", "middle"])
        self.assertAlmostEqual(result[0][1], 0.7)
        self.assertAlmostEqual(result[1][1], 0.35)
        self.assertEqual(result[0][0].metadata["vector_score"], 0.9)

    def test_cross_encoder_preserves_vector_score_metadata(self):
        candidates = [
            RerankCandidate(Document(page_content="one", metadata={"name": "one"}), 0.9),
            RerankCandidate(Document(page_content="two", metadata={"name": "two"}), 0.1),
            RerankCandidate(Document(page_content="three", metadata={"name": "three"}), 0.5),
        ]
        reranker = CrossEncoderReranker()
        reranker._model = _FakeCrossEncoderModel([0.1, 0.8, 0.2])

        result = reranker.rerank(
            query="query",
            candidates=candidates,
            top_k=2,
        )

        self.assertEqual([doc.metadata["name"] for doc, _ in result], ["two", "three"])
        self.assertEqual(result[0][0].metadata["vector_score"], 0.1)
        self.assertEqual(result[0][0].metadata["rerank_score"], 0.8)
        self.assertEqual(result[0][1], 0.8)

    def test_hybrid_keyword_scoring_supports_cjk_bigrams(self):
        candidates = [
            RerankCandidate(
                Document(page_content="服务端上下文预算机制", metadata={"name": "relevant"}),
                0.1,
            ),
            RerankCandidate(
                Document(page_content="完全无关的内容", metadata={"name": "vector-only"}),
                0.9,
            ),
            RerankCandidate(
                Document(page_content="另一个普通文档", metadata={"name": "middle"}),
                0.5,
            ),
        ]

        result = HybridFusionReranker(alpha=0.2).rerank(
            query="上下文预算",
            candidates=candidates,
            top_k=1,
        )

        self.assertEqual(result[0][0].metadata["name"], "relevant")

    def test_cross_encoder_failure_falls_back_to_vector_order_and_scores(self):
        candidates = [
            RerankCandidate(Document(page_content="low", metadata={"name": "low"}), 0.1),
            RerankCandidate(Document(page_content="high", metadata={"name": "high"}), 0.9),
            RerankCandidate(Document(page_content="middle", metadata={"name": "middle"}), 0.5),
        ]
        reranker = CrossEncoderReranker()

        with patch.object(reranker, "_load_model", side_effect=RuntimeError("offline")):
            result = reranker.rerank(
                query="query",
                candidates=candidates,
                top_k=2,
            )

        self.assertEqual([doc.metadata["name"] for doc, _ in result], ["high", "middle"])
        self.assertEqual([score for _, score in result], [0.9, 0.5])

    def test_cross_encoder_remote_code_is_disabled_by_default(self):
        captured = {}

        class FakeCrossEncoder:
            def __init__(self, model_name, **kwargs):
                captured.update(kwargs)

        fake_module = SimpleNamespace(CrossEncoder=FakeCrossEncoder)
        reranker = CrossEncoderReranker()

        with patch.dict(sys.modules, {"sentence_transformers": fake_module}):
            reranker._load_model()

        self.assertFalse(captured["trust_remote_code"])

    def test_invalid_top_k_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "top_k must be greater than 0"):
            NoOpReranker().rerank(
                query="query",
                candidates=[],
                top_k=0,
            )


if __name__ == "__main__":
    unittest.main()
