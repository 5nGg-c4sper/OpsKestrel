"""Tests for the vision provider interface."""

import unittest

from opskestrel.providers.base import VisionProvider


class StubVisionProvider(VisionProvider):
    def __init__(self, response):
        self.response = response
        self.calls = []

    def verify(self, image_path, statement):
        self.calls.append((image_path, statement))
        return self.response


class VisionProviderTests(unittest.TestCase):
    def test_base_provider_cannot_be_instantiated(self):
        with self.assertRaises(TypeError):
            VisionProvider()

    def test_subclass_implements_verify_contract(self):
        provider = StubVisionProvider(True)

        result = provider.verify(
            "/private/tmp/screenshot.png",
            "结果是否为 391？",
        )

        self.assertTrue(result)
        self.assertEqual(
            provider.calls,
            [("/private/tmp/screenshot.png", "结果是否为 391？")],
        )


if __name__ == "__main__":
    unittest.main()
