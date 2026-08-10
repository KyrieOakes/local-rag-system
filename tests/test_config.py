"""安全配置默认值与环境变量覆盖测试。"""

import os
import unittest
from unittest.mock import patch

from pydantic import ValidationError

from app.core.config import Settings


class SettingsSecurityTest(unittest.TestCase):
    def test_cloud_api_key_has_no_source_code_default(self):
        with patch.dict(os.environ, {}, clear=True):
            settings = Settings(_env_file=None)

        self.assertEqual(settings.cloud_llm_api_key, "")

    def test_cloud_api_key_can_be_injected_from_environment(self):
        with patch.dict(
            os.environ,
            {"CLOUD_LLM_API_KEY": "test-only-placeholder"},
            clear=True,
        ):
            settings = Settings(_env_file=None)

        self.assertEqual(settings.cloud_llm_api_key, "test-only-placeholder")

    def test_local_endpoints_have_loopback_defaults(self):
        with patch.dict(os.environ, {}, clear=True):
            settings = Settings(_env_file=None)

        self.assertTrue(settings.llm_base_url.startswith("http://127.0.0.1:"))
        self.assertTrue(settings.embedding_base_url.startswith("http://127.0.0.1:"))
        self.assertEqual(settings.embedding_batch_size, 32)
        self.assertEqual(settings.embedding_max_concurrency, 2)
        self.assertEqual(settings.upload_ingestion_concurrency, 2)
        self.assertEqual(settings.context_short_term_max_turns, 6)
        self.assertEqual(settings.context_short_term_max_tokens, 4096)
        self.assertEqual(settings.context_summary_batch_turns, 4)

    def test_embedding_concurrency_is_bounded(self):
        with self.assertRaises(ValidationError):
            Settings(_env_file=None, embedding_max_concurrency=17)
        with self.assertRaises(ValidationError):
            Settings(_env_file=None, upload_ingestion_concurrency=9)

    def test_cloud_provider_requires_explicit_key(self):
        with patch.dict(
            os.environ,
            {"LLM_PROVIDER": "cloud"},
            clear=True,
        ):
            with self.assertRaises(ValidationError):
                Settings(_env_file=None)

    def test_chunk_overlap_must_be_smaller_than_chunk_size(self):
        with self.assertRaises(ValidationError):
            Settings(
                _env_file=None,
                chunk_size=100,
                chunk_overlap=100,
            )

    def test_context_reservations_must_fit_window(self):
        with self.assertRaises(ValidationError):
            Settings(
                _env_file=None,
                llm_context_window=512,
                llm_reserved_output_tokens=400,
                context_safety_margin_tokens=112,
            )

    def test_reranker_final_k_must_fit_candidate_count(self):
        with self.assertRaises(ValidationError):
            Settings(
                _env_file=None,
                reranker_candidate_top_n=3,
                reranker_final_top_k=5,
            )

    def test_hybrid_retrieval_requires_hybrid_index_schema(self):
        with self.assertRaises(ValidationError):
            Settings(
                _env_file=None,
                retrieval_index_schema="dense",
                retrieval_mode="hybrid",
            )

    def test_bm25_retrieval_accepts_hybrid_index_schema(self):
        configured = Settings(
            _env_file=None,
            retrieval_index_schema="hybrid",
            retrieval_mode="bm25",
        )

        self.assertEqual(configured.retrieval_mode, "bm25")

    def test_dense_and_sparse_vector_names_must_differ(self):
        with self.assertRaises(ValidationError):
            Settings(
                _env_file=None,
                dense_vector_name="shared",
                sparse_vector_name="shared",
            )


if __name__ == "__main__":
    unittest.main()
