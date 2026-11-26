"""Tests for accessibility element matching and normalization."""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from soc_agent.accessibility import (
    AccessibilityLocator,
    AccessibilityLookupError,
    PyObjCAccessibilityAdapter,
)
from soc_agent.task_models import UIElementLocator


class FakeAccessibilityAdapter:
    def __init__(self):
        self.elements = {
            "root": {
                "role": "AXApplication",
                "title": "计算器",
                "children": ["window"],
            },
            "window": {
                "role": "AXWindow",
                "title": "计算器",
                "children": ["button-7", "button-8"],
            },
            "button-7": {
                "role": "AXButton",
                "title": "7",
                "description": "Seven",
                "value": "7",
                "frame": (100, 200, 80, 60),
            },
            "button-8": {
                "role": "AXButton",
                "title": "8",
                "value": "8",
                "frame": (200, 200, 80, 60),
            },
        }

    def root_for_app(self, app_name):
        self.app_name = app_name
        return "root"

    def screen_size(self):
        return 1000.0, 500.0

    def children(self, element):
        return self.elements[element].get("children", [])

    def role(self, element):
        return self.elements[element].get("role")

    def title(self, element):
        return self.elements[element].get("title")

    def description(self, element):
        return self.elements[element].get("description")

    def value(self, element):
        return self.elements[element].get("value")

    def frame(self, element):
        return self.elements[element].get("frame")


class AccessibilityLocatorTests(unittest.TestCase):
    def setUp(self):
        self.adapter = FakeAccessibilityAdapter()
        self.locator = AccessibilityLocator(self.adapter)

    def test_finds_element_and_returns_normalized_center(self):
        match = self.locator.find(
            "计算器",
            UIElementLocator(
                role="AXButton",
                title="7",
            ),
        )

        self.assertEqual(self.adapter.app_name, "计算器")
        self.assertEqual(match.role, "AXButton")
        self.assertAlmostEqual(match.x, 0.1)
        self.assertAlmostEqual(match.y, 0.4)
        self.assertAlmostEqual(match.width, 0.08)
        self.assertAlmostEqual(match.height, 0.12)
        self.assertAlmostEqual(match.center_x, 0.14)
        self.assertAlmostEqual(match.center_y, 0.46)

    def test_matches_multiple_fields_case_insensitively(self):
        match = self.locator.find(
            "计算器",
            UIElementLocator(
                role="axbutton",
                description="SEVEN",
                value="7",
            ),
        )

        self.assertEqual(match.title, "7")

    def test_text_criterion_matches_title_description_or_value(self):
        match = self.locator.find(
            "计算器",
            UIElementLocator(
                role="AXButton",
                text="7",
            ),
        )

        self.assertEqual(match.title, "7")

    def test_match_index_selects_ordered_match(self):
        match = self.locator.find(
            "计算器",
            UIElementLocator(
                role="AXButton",
                match_index=1,
            ),
        )

        self.assertEqual(match.title, "8")

    def test_missing_match_raises(self):
        with self.assertRaisesRegex(
            AccessibilityLookupError,
            "accessibility element not found",
        ):
            self.locator.find(
                "计算器",
                UIElementLocator(role="AXButton", title="9"),
            )

    def test_pyobjc_adapter_falls_back_to_application_windows(self):
        adapter = PyObjCAccessibilityAdapter.__new__(
            PyObjCAccessibilityAdapter
        )
        adapter._ax = SimpleNamespace(
            kAXChildrenAttribute="children",
            kAXWindowsAttribute="windows",
            kAXMenuBarAttribute="menu_bar",
        )
        values = {
            "children": [],
            "windows": ["window"],
            "menu_bar": "menu",
        }
        adapter._copy_attribute = lambda element, attribute: values.get(
            attribute
        )

        with patch.object(
            adapter,
            "role",
            return_value="AXApplication",
        ):
            children = adapter.children("root")

        self.assertEqual(children, ["window", "menu"])

    def test_pyobjc_pair_parser_accepts_version_specific_shapes(self):
        adapter = PyObjCAccessibilityAdapter

        self.assertEqual(
            adapter._pair_values((10, 20), "x", "y"),
            (10.0, 20.0),
        )
        self.assertEqual(
            adapter._pair_values(((10, 20),), "x", "y"),
            (10.0, 20.0),
        )
        self.assertEqual(
            adapter._pair_values(
                (True, (10, 20)),
                "x",
                "y",
            ),
            (10.0, 20.0),
        )
        self.assertEqual(
            adapter._pair_values(
                SimpleNamespace(x=10, y=20),
                "x",
                "y",
            ),
            (10.0, 20.0),
        )


if __name__ == "__main__":
    unittest.main()
