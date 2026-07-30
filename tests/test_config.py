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


if __name__ == "__main__":
    unittest.main()
