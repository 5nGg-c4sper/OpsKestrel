"""Tests for structured DOM browser adapters."""

import tempfile
import unittest
from pathlib import Path

from soc_agent.browser import (
    ERPSearchResult,
    MockERPAdapter,
)


class FakeLocator:
    def __init__(self, records):
        self.records = records

    def evaluate_all(self, script, argument):
        self.script = script
        self.argument = argument
        return self.records


class FakePage:
    def __init__(self, records):
        self.records = records
        self.calls = []
        self.screenshot_path = None

    def goto(self, url, **kwargs):
        self.calls.append(("goto", url, kwargs))

    def fill(self, selector, value, **kwargs):
        self.calls.append(("fill", selector, value, kwargs))

    def click(self, selector, **kwargs):
        self.calls.append(("click", selector, kwargs))

    def wait_for_selector(self, selector, **kwargs):
        self.calls.append(("wait", selector, kwargs))

    def locator(self, selector):
        self.calls.append(("locator", selector))
        return FakeLocator(self.records)

    def screenshot(self, path, full_page=False):
        Path(path).write_bytes(b"fake-image")
        self.screenshot_path = (path, full_page)


class MockERPAdapterTests(unittest.TestCase):
    def test_search_collects_single_record_and_screenshot(self):
        page = FakePage(
            [
                {
                    "invoice_id": "INV-1001",
                    "currency": "CNY",
                    "amount": "1200.00",
                    "status": "paid",
                }
            ]
        )
        adapter = MockERPAdapter(page, "http://127.0.0.1:8765")

        with tempfile.TemporaryDirectory() as directory:
            screenshot = Path(directory) / "erp.png"
            result = adapter.search(
                " INV-1001 ",
                screenshot_path=str(screenshot),
            )

            self.assertTrue(screenshot.is_file())
            self.assertEqual(result.screenshot_path, str(screenshot.resolve()))

        self.assertTrue(result.found)
        self.assertEqual(result.records[0]["amount"], "1200.00")
        self.assertEqual(
            page.calls[:3],
            [
                (
                    "goto",
                    "http://127.0.0.1:8765/",
                    {
                        "wait_until": "domcontentloaded",
                        "timeout": 10000,
                    },
                ),
                (
                    "fill",
                    '[data-testid="invoice-id-input"]',
                    "INV-1001",
                    {"timeout": 10000},
                ),
                (
                    "click",
                    '[data-testid="invoice-search-submit"]',
                    {"timeout": 10000},
                ),
            ],
        )

    def test_search_reports_duplicate_records(self):
        page = FakePage(
            [
                {"invoice_id": "INV-1017", "amount": "150.00"},
                {"invoice_id": "INV-1017", "amount": "150.00"},
            ]
        )

        result = MockERPAdapter(page, "http://localhost").search(
            "INV-1017"
        )

        self.assertEqual(result.record_count, 2)
        self.assertTrue(result.duplicate)

    def test_search_returns_not_found_result(self):
        page = FakePage([])

        result = MockERPAdapter(page, "http://localhost").search(
            "UNKNOWN"
        )

        self.assertFalse(result.found)
        self.assertEqual(result.record_count, 0)
        self.assertFalse(result.duplicate)

    def test_blank_invoice_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "must not be empty"):
            MockERPAdapter(FakePage([]), "http://localhost").search(" ")

    def test_result_serializes_to_dict(self):
        result = ERPSearchResult(
            invoice_id="INV-1",
            base_url="http://localhost/",
            records=({"invoice_id": "INV-1", "amount": "10.00"},),
        )

        self.assertEqual(
            result.to_dict(),
            {
                "invoice_id": "INV-1",
                "base_url": "http://localhost/",
                "found": True,
                "record_count": 1,
                "duplicate": False,
                "records": [
                    {"invoice_id": "INV-1", "amount": "10.00"}
                ],
                "screenshot_path": None,
            },
        )


if __name__ == "__main__":
    unittest.main()
