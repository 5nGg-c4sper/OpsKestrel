"""Tests for the macOS environment adapter."""

import unittest
from pathlib import Path

from soc_agent.environments.macos import MacOSEnvironment


class FakeSystem:
    def __init__(self):
        self.calls = []

    def open_app(self, app_name):
        self.calls.append(("open_app", app_name))

    def write(self, content):
        self.calls.append(("write", content))

    def press(self, keys):
        self.calls.append(("press", keys))

    def mouse(self, click_detail):
        self.calls.append(("mouse", click_detail))


class MacOSEnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.system = FakeSystem()
        self.screenshot_calls = []
        self.sleep_calls = []

        self.environment = MacOSEnvironment(
            system=self.system,
            screenshot_capture=self.fake_screenshot,
            scale=0.5,
            sleep_fn=self.sleep_calls.append,
        )

    def fake_screenshot(self, path, scale):
        self.screenshot_calls.append((path, scale))

    def test_open_app(self):
        self.environment.open_app("计算器")
        self.assertEqual(self.system.calls, [("open_app", "计算器")])

    def test_write(self):
        self.environment.write("17*23")
        self.assertEqual(self.system.calls, [("write", "17*23")])

    def test_press(self):
        self.environment.press(["enter"])
        self.assertEqual(self.system.calls, [("press", ["enter"])])

    def test_click(self):
        self.environment.click(0.4, 0.7)
        self.assertEqual(
            self.system.calls,
            [("mouse", {"x": 0.4, "y": 0.7})],
        )

    def test_wait(self):
        self.environment.wait(1.5)
        self.assertEqual(self.sleep_calls, [1.5])

    def test_screenshot(self):
        path = self.environment.screenshot("/private/tmp/soc-test.png")
        self.assertEqual(path, Path("/private/tmp/soc-test.png"))
        self.assertEqual(
            self.screenshot_calls,
            [("/private/tmp/soc-test.png", 0.5)],
        )

    def test_invalid_click_is_rejected(self):
        with self.assertRaises(ValueError):
            self.environment.click(1.2, 0.5)

    def test_invalid_wait_is_rejected(self):
        with self.assertRaises(ValueError):
            self.environment.wait(0)


if __name__ == "__main__":
    unittest.main()
