"""Tests for runtime configuration."""

import unittest

from soc_agent.config import AgentConfig, ConfigError


class AgentConfigTests(unittest.TestCase):
    def test_loads_values_from_environment(self):
        config = AgentConfig.from_env(
            {
                "OPENAI_API_KEY": "test-key",
                "OPENAI_BASE_URL": "https://example.test/v1",
                "MODEL": "test-vision-model",
                "SCREENSHOT_SCALE": "0.4",
                "ACTION_SETTLE_DELAY": "0.2",
                "QWEN_TIMEOUT_SECONDS": "15",
                "REPORTS_DIR": "custom-reports",
            }
        )

        self.assertEqual(config.api_key, "test-key")
        self.assertEqual(config.base_url, "https://example.test/v1")
        self.assertEqual(config.model, "test-vision-model")
        self.assertEqual(config.screenshot_scale, 0.4)
        self.assertEqual(config.settle_delay, 0.2)
        self.assertEqual(config.qwen_timeout, 15.0)
        self.assertEqual(str(config.reports_dir), "custom-reports")

    def test_uses_optional_defaults(self):
        config = AgentConfig.from_env({"OPENAI_API_KEY": "test-key"})

        self.assertEqual(
            config.base_url,
            "https://api.siliconflow.cn/v1",
        )
        self.assertEqual(config.model, "Qwen/Qwen3-VL-8B-Instruct")
        self.assertEqual(config.screenshot_scale, 0.5)
        self.assertEqual(config.settle_delay, 0.6)
        self.assertEqual(config.qwen_timeout, 30.0)

    def test_overrides_are_validated(self):
        config = AgentConfig.from_env({"OPENAI_API_KEY": "test-key"})

        updated = config.with_overrides(
            screenshot_scale=0.75,
            settle_delay=0.1,
        )

        self.assertEqual(updated.screenshot_scale, 0.75)
        self.assertEqual(updated.settle_delay, 0.1)

    def test_missing_api_key_is_rejected(self):
        with self.assertRaisesRegex(ConfigError, "OPENAI_API_KEY"):
            AgentConfig.from_env({})

    def test_invalid_scale_is_rejected(self):
        with self.assertRaisesRegex(ConfigError, "SCREENSHOT_SCALE"):
            AgentConfig.from_env(
                {
                    "OPENAI_API_KEY": "test-key",
                    "SCREENSHOT_SCALE": "1.5",
                }
            )

    def test_negative_settle_delay_is_rejected(self):
        with self.assertRaisesRegex(ConfigError, "ACTION_SETTLE_DELAY"):
            AgentConfig.from_env(
                {
                    "OPENAI_API_KEY": "test-key",
                    "ACTION_SETTLE_DELAY": "-1",
                }
            )

    def test_invalid_timeout_is_rejected(self):
        with self.assertRaisesRegex(ConfigError, "QWEN_TIMEOUT_SECONDS"):
            AgentConfig.from_env(
                {
                    "OPENAI_API_KEY": "test-key",
                    "QWEN_TIMEOUT_SECONDS": "0",
                }
            )

    def test_api_key_is_hidden_from_repr(self):
        config = AgentConfig.from_env({"OPENAI_API_KEY": "secret-value"})

        self.assertNotIn("secret-value", repr(config))


if __name__ == "__main__":
    unittest.main()
