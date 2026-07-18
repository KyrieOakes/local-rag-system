"""安全配置默认值与环境变量覆盖测试。"""

import os
import unittest
from unittest.mock import patch

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


if __name__ == "__main__":
    unittest.main()
