"""Tests for retrieval evaluation report reproducibility metadata."""

import argparse
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.core.config import settings
from evaluation.run_retrieval_eval import _build_report, _validate_args


class RetrievalEvaluationReportTest(unittest.TestCase):
    def test_rerank_candidate_count_cannot_be_smaller_than_evaluation_k(self):
        args = argparse.Namespace(
            top_k=10,
            rerank_top_n=5,
            use_reranker=True,
        )

        with self.assertRaisesRegex(ValueError, "greater than or equal"):
            _validate_args(args)

    def test_report_adds_provenance_without_breaking_v1_shape(self):
        dataset_content = '{"id":"q1","question":"What is RAG?"}\n'
        with tempfile.TemporaryDirectory() as directory:
            dataset_path = Path(directory) / "golden.jsonl"
            dataset_path.write_text(dataset_content, encoding="utf-8")
            args = argparse.Namespace(
                experiment_name="provenance-test",
                dataset=str(dataset_path),
                top_k=5,
                use_query_processor=False,
                use_reranker=True,
                reranker_type="hybrid",
                rerank_top_n=20,
            )

            def fake_git(*git_args):
                return "abc123" if git_args == ("rev-parse", "HEAD") else ""

            with patch(
                "evaluation.run_retrieval_eval._run_git_command",
                side_effect=fake_git,
            ):
                report = _build_report(args, per_question=[])

        expected_hash = hashlib.sha256(dataset_content.encode("utf-8")).hexdigest()
        self.assertEqual(report["report_schema"], "retrieval-eval-v1")
        self.assertEqual(report["metric_semantics_version"], "evidence-label-v2")
        self.assertEqual(report["provenance"]["dataset_sha256"], expected_hash)
        self.assertEqual(report["provenance"]["git_sha"], "abc123")
        self.assertFalse(report["provenance"]["git_dirty"])
        self.assertTrue(
            report["provenance"]["settings_fingerprint"].startswith("sha256:")
        )
        self.assertEqual(
            report["settings_snapshot"]["schema_version"],
            "retrieval-settings-v1",
        )
        self.assertEqual(report["rerank_config"]["reranker_type"], "hybrid")
        self.assertIn("trust_remote_code", report["rerank_config"])
        self.assertEqual(
            report["settings_snapshot"]["embedding_revision"],
            settings.embedding_revision,
        )
        self.assertIn(
            "pipeline_fingerprint",
            report["settings_snapshot"],
        )

    def test_settings_fingerprint_changes_with_experiment_configuration(self):
        dataset_content = '{"id":"q1","question":"What is RAG?"}\n'
        with tempfile.TemporaryDirectory() as directory:
            dataset_path = Path(directory) / "golden.jsonl"
            dataset_path.write_text(dataset_content, encoding="utf-8")
            base = {
                "experiment_name": "fingerprint-test",
                "dataset": str(dataset_path),
                "use_query_processor": False,
                "use_reranker": False,
                "reranker_type": "cross_encoder",
                "rerank_top_n": 20,
            }
            first_args = argparse.Namespace(top_k=5, **base)
            second_args = argparse.Namespace(top_k=10, **base)

            with patch(
                "evaluation.run_retrieval_eval._run_git_command",
                return_value=None,
            ):
                first = _build_report(first_args, per_question=[])
                second = _build_report(second_args, per_question=[])

        self.assertNotEqual(
            first["provenance"]["settings_fingerprint"],
            second["provenance"]["settings_fingerprint"],
        )


if __name__ == "__main__":
    unittest.main()
