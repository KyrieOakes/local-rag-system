"""
统一评估器单元测试。

测试 evaluation/retrieval_metrics/evaluator.py 的 evaluate_retrieval_case()：
- 验证返回的指标分组结构（core_metrics + context_quality）
- 验证重复和无关上下文被 context_redundancy 指标正确惩罚
- 验证完全未命中时所有检索质量指标归零

运行：python -m unittest tests.test_retrieval_evaluator
"""
import unittest

from evaluation.retrieval_metrics.evaluator import evaluate_retrieval_case
from evaluation.retrieval_metrics.matching import RelevantSource, build_retrieved_item


class RetrievalEvaluatorTest(unittest.TestCase):
    def test_evaluate_retrieval_case_returns_grouped_enterprise_metrics(self):
        retrieved_items = [
            build_retrieved_item("Useful deployment guide", {"file_path": "docs/deploy.md", "chunk_index": 1}),
            build_retrieved_item("Repeated deployment guide", {"file_path": "docs/deploy.md", "chunk_index": 2}),
            build_retrieved_item("Noise", {"file_path": "docs/noise.md", "chunk_index": 1}),
        ]
        relevant_sources = [
            RelevantSource(file_path="docs/deploy.md", text="deployment", relevance=2),
        ]

        result = evaluate_retrieval_case(retrieved_items, relevant_sources, k=3)

        self.assertIn("recall@3", result.core_metrics)
        self.assertIn("precision@3", result.core_metrics)
        self.assertIn("mrr", result.core_metrics)
        self.assertIn("ndcg@3", result.core_metrics)
        self.assertIn("context_redundancy@3", result.context_quality)
        self.assertEqual(result.core_metrics["mrr"], 1.0)

    def test_evaluator_penalizes_duplicate_and_irrelevant_contexts(self):
        retrieved_items = [
            build_retrieved_item("Password reset steps for SSO users", {"file_path": "it/sso.md", "chunk_index": 1}),
            build_retrieved_item("Password reset steps for SSO users", {"file_path": "it/sso.md", "chunk_index": 2}),
            build_retrieved_item("Company picnic schedule", {"file_path": "events/picnic.md", "chunk_index": 1}),
        ]
        relevant_sources = [
            RelevantSource(file_path="it/sso.md", text="Password reset", relevance=3),
        ]

        result = evaluate_retrieval_case(retrieved_items, relevant_sources, k=3)

        self.assertEqual(result.core_metrics["recall@3"], 1.0)
        self.assertAlmostEqual(result.core_metrics["precision@3"], 2 / 3)
        self.assertGreater(result.context_quality["context_redundancy@3"], 0)
        self.assertGreater(result.context_quality["duplicate_rate@3"], 0)

    def test_evaluator_shows_complete_miss_as_zero_retrieval_quality(self):
        retrieved_items = [
            build_retrieved_item("Office snack policy", {"file_path": "office/snacks.md", "chunk_index": 1}),
            build_retrieved_item("Holiday calendar", {"file_path": "office/holidays.md", "chunk_index": 1}),
        ]
        relevant_sources = [
            RelevantSource(file_path="security/access.md", text="least privilege", relevance=3),
        ]

        result = evaluate_retrieval_case(retrieved_items, relevant_sources, k=2)

        self.assertEqual(result.core_metrics["recall@2"], 0.0)
        self.assertEqual(result.core_metrics["precision@2"], 0.0)
        self.assertEqual(result.core_metrics["mrr"], 0.0)
        self.assertEqual(result.context_quality["irrelevant_rate@2"], 1.0)


if __name__ == "__main__":
    unittest.main()
