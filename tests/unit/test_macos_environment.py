"""Tests for the macOS environment adapter."""

import unittest
import tempfile
from pathlib import Path

from opskestrel.accessibility import UIElementMatch
from opskestrel.environments.macos import MacOSEnvironment
from opskestrel.task_models import UIElementLocator


class FakeSystem:
    def __init__(self):
        self.calls = []

    def open_app(self, app_name):
        self.calls.append(("open_app", app_name))

    def activate_app(self, app_name):
        self.calls.append(("activate_app", app_name))

    def close_document(self, app_name, save_changes=False):
        self.calls.append(
            ("close_document", app_name, save_changes)
        )

    def write(self, content):
        self.calls.append(("write", content))

    def press(self, keys):
        self.calls.append(("press", keys))

    def mouse(self, click_detail):
        self.calls.append(("mouse", click_detail))


class FakeAccessibilityLocator:
    def __init__(self):
        self.calls = []

    def find(self, app_name, locator):
        self.calls.append((app_name, locator))
        return UIElementMatch(
            role="AXButton",
            title="7",
            description=None,
            value="7",
            x=0.1,
            y=0.2,
            width=0.05,
            height=0.1,
        )


class MacOSEnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.system = FakeSystem()
        self.accessibility = FakeAccessibilityLocator()
        self.screenshot_calls = []
        self.sleep_calls = []

        self.environment = MacOSEnvironment(
            system=self.system,
            screenshot_capture=self.fake_screenshot,
            accessibility_locator=self.accessibility,
            scale=0.5,
            sleep_fn=self.sleep_calls.append,
        )

    def fake_screenshot(self, path, scale):
        self.screenshot_calls.append((path, scale))

    def test_open_app(self):
        self.environment.open_app("计算器")
        self.assertEqual(self.system.calls, [("open_app", "计算器")])

    def test_activate_app(self):
        self.environment.activate_app("Safari")
        self.assertEqual(
            self.system.calls,
            [("activate_app", "Safari")],
        )

    def test_activate_app_rejects_empty_name(self):
        with self.assertRaises(ValueError):
            self.environment.activate_app(" ")

    def test_close_document(self):
        self.environment.close_document(
            "文本编辑",
            save_changes=False,
        )

        self.assertEqual(
            self.system.calls,
            [("close_document", "文本编辑", False)],
        )

    def test_close_document_rejects_empty_name(self):
        with self.assertRaises(ValueError):
            self.environment.close_document(" ")

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

    def test_click_element_uses_normalized_center(self):
        locator = UIElementLocator(role="AXButton", title="7")

        self.environment.click_element("计算器", locator)

        self.assertEqual(
            self.accessibility.calls,
            [("计算器", locator)],
        )
        self.assertEqual(
            self.system.calls,
            [("mouse", {"x": 0.125, "y": 0.25})],
        )

    def test_read_element_uses_selected_attribute(self):
        locator = UIElementLocator(role="AXButton", title="7")

        value = self.environment.read_element(
            "计算器",
            locator,
            attribute="value",
        )
        title = self.environment.read_element(
            "计算器",
            locator,
            attribute="title",
        )

        self.assertEqual(value, "7")
        self.assertEqual(title, "7")

    def test_wait(self):
        self.environment.wait(1.5)
        self.assertEqual(self.sleep_calls, [1.5])

    def test_screenshot(self):
        expected_path = (
            Path(self.temporary_directory.name) / "opskestrel-test.png"
        )
        path = self.environment.screenshot(expected_path)
        self.assertEqual(path, expected_path)
        self.assertEqual(
            self.screenshot_calls,
            [(str(expected_path), 0.5)],
        )

    def test_invalid_click_is_rejected(self):
        with self.assertRaises(ValueError):
            self.environment.click(1.2, 0.5)

    def test_invalid_wait_is_rejected(self):
        with self.assertRaises(ValueError):
            self.environment.wait(0)


if __name__ == "__main__":
    unittest.main()
