"""
统一评估器单元测试。

测试 evaluation/retrieval_metrics/evaluator.py 的 evaluate_retrieval_case()：
- 验证返回的指标分组结构（core_metrics + context_quality）
- 验证 Recall 以完整 gold evidence 为分母
- 验证同一 evidence 的重复 chunk 只计一次命中
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
            RelevantSource(
                file_path="docs/deploy.md",
                text="deployment",
                relevance=2,
                evidence_id="deployment",
            ),
        ]

        result = evaluate_retrieval_case(retrieved_items, relevant_sources, k=3)

        self.assertIn("recall@3", result.core_metrics)
        self.assertIn("precision@3", result.core_metrics)
        self.assertIn("mrr", result.core_metrics)
        self.assertIn("ndcg@3", result.core_metrics)
        self.assertIn("context_redundancy@3", result.context_quality)
        self.assertEqual(result.core_metrics["mrr"], 1.0)

    def test_partial_recall_uses_all_gold_evidence_as_denominator(self):
        retrieved_items = [
            build_retrieved_item(
                "Deploy behind a feature flag.",
                {"file_path": "docs/deploy.md", "chunk_index": 1},
            ),
            build_retrieved_item(
                "Company picnic schedule",
                {"file_path": "events/picnic.md", "chunk_index": 1},
            ),
        ]
        relevant_sources = [
            RelevantSource(
                file_path="docs/deploy.md",
                text="feature flag",
                evidence_id="feature-flag",
            ),
            RelevantSource(
                file_path="docs/deploy.md",
                text="rollback verification",
                evidence_id="rollback",
            ),
        ]

        result = evaluate_retrieval_case(retrieved_items, relevant_sources, k=2)

        self.assertEqual(result.core_metrics["recall@2"], 0.5)
        self.assertEqual(result.core_metrics["precision@2"], 0.5)
        self.assertEqual(result.matched_relevant_ids, ["feature-flag"])
        self.assertEqual(result.gold_evidence_ids, ["feature-flag", "rollback"])

    def test_duplicate_chunks_only_hit_the_same_evidence_once(self):
        retrieved_items = [
            build_retrieved_item("Password reset steps for SSO users", {"file_path": "it/sso.md", "chunk_index": 1}),
            build_retrieved_item("Password reset steps for SSO users", {"file_path": "it/sso.md", "chunk_index": 2}),
            build_retrieved_item("Company picnic schedule", {"file_path": "events/picnic.md", "chunk_index": 1}),
        ]
        relevant_sources = [
            RelevantSource(
                file_path="it/sso.md",
                text="Password reset",
                relevance=3,
                evidence_id="sso-password-reset",
            ),
        ]

        result = evaluate_retrieval_case(retrieved_items, relevant_sources, k=3)

        self.assertEqual(result.core_metrics["recall@3"], 1.0)
        self.assertAlmostEqual(result.core_metrics["precision@3"], 1 / 3)
        self.assertEqual(result.matched_relevant_ids, ["sso-password-reset"])
        self.assertGreater(result.context_quality["context_redundancy@3"], 0)
        self.assertGreater(result.context_quality["duplicate_rate@3"], 0)

    def test_evaluator_shows_complete_miss_as_zero_retrieval_quality(self):
        retrieved_items = [
            build_retrieved_item("Office snack policy", {"file_path": "office/snacks.md", "chunk_index": 1}),
            build_retrieved_item("Holiday calendar", {"file_path": "office/holidays.md", "chunk_index": 1}),
        ]
        relevant_sources = [
            RelevantSource(
                file_path="security/access.md",
                text="least privilege",
                relevance=3,
                evidence_id="least-privilege",
            ),
        ]

        result = evaluate_retrieval_case(retrieved_items, relevant_sources, k=2)

        self.assertEqual(result.core_metrics["recall@2"], 0.0)
        self.assertEqual(result.core_metrics["precision@2"], 0.0)
        self.assertEqual(result.core_metrics["mrr"], 0.0)
        self.assertEqual(result.context_quality["irrelevant_rate@2"], 1.0)

    def test_ndcg_preserves_the_original_retrieval_rank(self):
        retrieved_items = [
            build_retrieved_item(
                "Unrelated first result",
                {"file_path": "noise.md", "chunk_index": 1},
            ),
            build_retrieved_item(
                "Rollback verification is required",
                {"file_path": "deploy.md", "chunk_index": 1},
            ),
        ]
        relevant_sources = [
            RelevantSource(
                file_path="deploy.md",
                text="rollback verification",
                relevance=3,
                evidence_id="rollback",
            ),
        ]

        result = evaluate_retrieval_case(retrieved_items, relevant_sources, k=2)

        self.assertEqual(result.core_metrics["mrr"], 0.5)
        self.assertGreater(result.core_metrics["ndcg@2"], 0)
        self.assertLess(result.core_metrics["ndcg@2"], 1)


if __name__ == "__main__":
    unittest.main()
