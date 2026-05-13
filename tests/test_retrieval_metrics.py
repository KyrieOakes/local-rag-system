import math
import unittest

from evaluation.retrieval_metrics import (
    context_redundancy_at_k,
    mean_reciprocal_rank,
    mrr,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
)


class RetrievalMetricsTest(unittest.TestCase):
    def test_recall_at_k_counts_relevant_hits_in_top_k(self):
        self.assertEqual(recall_at_k(["a", "b", "c", "d"], {"b", "d"}, k=3), 0.5)

    def test_recall_at_k_drops_to_zero_when_correct_policy_is_below_cutoff(self):
        retrieved = ["office-wifi", "lunch-menu", "holiday-calendar", "security-policy"]

        self.assertEqual(recall_at_k(retrieved, {"security-policy"}, k=3), 0.0)
        self.assertEqual(recall_at_k(retrieved, {"security-policy"}, k=4), 1.0)

    def test_precision_at_k_uses_k_as_denominator(self):
        self.assertEqual(precision_at_k(["a", "b", "c"], {"a", "c", "x"}, k=2), 0.5)

    def test_precision_at_k_penalizes_noisy_context_window(self):
        retrieved = ["deploy-runbook", "cafeteria-hours", "vpn-troubleshooting", "random-release-notes"]
        relevant = {"deploy-runbook", "vpn-troubleshooting"}

        self.assertEqual(precision_at_k(retrieved, relevant, k=4), 0.5)

    def test_context_redundancy_at_k_reports_noise_and_duplicates(self):
        metrics = context_redundancy_at_k(
            ["a", "b", "c", "d"],
            {"a", "c"},
            k=4,
            context_keys=["doc-1:same", "doc-1:same", "doc-2:useful", "doc-3:noise"],
        )

        self.assertEqual(metrics["irrelevant_rate@4"], 0.5)
        self.assertEqual(metrics["duplicate_rate@4"], 0.25)
        self.assertEqual(metrics["context_redundancy@4"], 0.75)

    def test_context_redundancy_at_k_is_zero_for_clean_unique_contexts(self):
        metrics = context_redundancy_at_k(
            ["handbook-benefits", "handbook-leave"],
            {"handbook-benefits", "handbook-leave"},
            k=2,
            context_keys=["hr.md:benefits", "hr.md:leave"],
        )

        self.assertEqual(metrics["context_redundancy@2"], 0.0)
        self.assertEqual(metrics["irrelevant_rate@2"], 0.0)
        self.assertEqual(metrics["duplicate_rate@2"], 0.0)

    def test_mrr_returns_reciprocal_rank_of_first_relevant_result(self):
        self.assertAlmostEqual(mrr(["a", "b", "c"], {"c"}), 1 / 3)

    def test_mrr_returns_zero_when_no_relevant_result_is_found(self):
        self.assertEqual(mrr(["a", "b", "c"], {"x"}), 0.0)

    def test_mrr_rewards_correct_document_at_rank_one(self):
        self.assertEqual(mrr(["incident-runbook", "general-faq"], {"incident-runbook"}), 1.0)

    def test_mean_reciprocal_rank_averages_multiple_queries(self):
        score = mean_reciprocal_rank(
            [["a", "b"], ["c", "d"], ["e", "f"]],
            [{"b"}, {"c"}, {"x"}],
        )

        self.assertAlmostEqual(score, ((1 / 2) + 1 + 0) / 3)

    def test_mean_reciprocal_rank_requires_matching_input_lengths(self):
        with self.assertRaisesRegex(ValueError, "must have the same length"):
            mean_reciprocal_rank([["a"]], [{"a"}, {"b"}])

    def test_ndcg_at_k_supports_binary_relevance(self):
        score = ndcg_at_k(["a", "x", "b"], relevant_ids={"a", "b"}, k=3)
        ideal = 1 + (1 / math.log2(3))
        actual = 1 + (1 / math.log2(4))

        self.assertAlmostEqual(score, actual / ideal)

    def test_ndcg_at_k_supports_graded_relevance_scores(self):
        score = ndcg_at_k(
            ["doc_low", "doc_high", "doc_none"],
            k=2,
            relevance_scores={"doc_high": 3, "doc_low": 1},
        )
        ideal = ((2**3 - 1) / math.log2(2)) + ((2**1 - 1) / math.log2(3))
        actual = ((2**1 - 1) / math.log2(2)) + ((2**3 - 1) / math.log2(3))

        self.assertAlmostEqual(score, actual / ideal)

    def test_recall_k_must_be_greater_than_zero(self):
        with self.assertRaisesRegex(ValueError, "k must be greater than 0"):
            recall_at_k(["a"], {"a"}, 0)

    def test_precision_k_must_be_greater_than_zero(self):
        with self.assertRaisesRegex(ValueError, "k must be greater than 0"):
            precision_at_k(["a"], {"a"}, 0)

    def test_ndcg_k_must_be_greater_than_zero(self):
        with self.assertRaisesRegex(ValueError, "k must be greater than 0"):
            ndcg_at_k(["a"], {"a"}, 0)


if __name__ == "__main__":
    unittest.main()
