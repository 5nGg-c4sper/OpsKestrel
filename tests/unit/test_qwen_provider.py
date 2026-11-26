"""Tests for the Qwen vision provider."""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from opskestrel.providers.base import VisionProviderError
from opskestrel.providers.qwen import QwenVisionProvider


class FakeCompletions:
    def __init__(self, response_content=None, error=None):
        self.response_content = response_content
        self.error = error
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error

        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=self.response_content)
                )
            ]
        )


class FakeClient:
    def __init__(self, completions):
        self.chat = SimpleNamespace(completions=completions)


class QwenVisionProviderTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.image_path = (
            Path(self.temporary_directory.name) / "screenshot.png"
        )
        self.image_path.write_bytes(b"fake-image")

    def make_provider(self, response_content=None, error=None):
        completions = FakeCompletions(response_content, error)
        provider = QwenVisionProvider(
            client=FakeClient(completions),
            model="Qwen/Qwen3-VL-8B-Instruct",
        )
        return provider, completions

    def test_verify_returns_true(self):
        provider, completions = self.make_provider("true")

        result = provider.verify(str(self.image_path), "结果为 391")

        self.assertTrue(result)
        self.assertEqual(
            completions.calls[0]["model"],
            "Qwen/Qwen3-VL-8B-Instruct",
        )
        self.assertEqual(completions.calls[0]["temperature"], 0.0)

    def test_verify_returns_false(self):
        provider, _ = self.make_provider("false")

        result = provider.verify(str(self.image_path), "结果为 392")

        self.assertFalse(result)

    def test_parses_true_from_short_sentence(self):
        provider, _ = self.make_provider("The answer is true.")

        result = provider.verify(str(self.image_path), "结果为 391")

        self.assertTrue(result)

    def test_unparseable_response_raises_error(self):
        provider, _ = self.make_provider("cannot determine")

        with self.assertRaises(VisionProviderError):
            provider.verify(str(self.image_path), "结果为 391")

    def test_missing_image_raises_error(self):
        provider, completions = self.make_provider("true")

        with self.assertRaises(VisionProviderError):
            provider.verify(
                str(self.image_path.with_name("missing.png")),
                "结果为 391",
            )
        self.assertEqual(completions.calls, [])

    def test_api_error_is_wrapped(self):
        provider, _ = self.make_provider(error=RuntimeError("network down"))

        with self.assertRaisesRegex(
            VisionProviderError,
            "network down",
        ):
            provider.verify(str(self.image_path), "结果为 391")


if __name__ == "__main__":
    unittest.main()
