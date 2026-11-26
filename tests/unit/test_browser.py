"""Tests for structured DOM browser adapters."""

import json
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path

from opskestrel.browser import (
    BrowserAdapterError,
    ERPSelectors,
    ERPSearchResult,
    MockERPAdapter,
)


class FakeLocator:
    def __init__(self, records, text=""):
        self.records = records
        self.text = text

    def evaluate_all(self, script, argument):
        self.script = script
        self.argument = argument
        return self.records

    def inner_text(self):
        return self.text

    def count(self):
        return 1 if self.text == "ERP server error" else 0


class FakeDownload:
    def save_as(self, path):
        Path(path).write_bytes(b"csv-data")


class FakePage:
    def __init__(self, records):
        self.records = records
        self.calls = []
        self.screenshot_path = None
        self.url = ""
        self.page_status = "Page 1"
        self.requires_login = False

    def goto(self, url, **kwargs):
        self.calls.append(("goto", url, kwargs))
        self.url = url.rstrip("/") + (
            "/login" if self.requires_login else "/"
        )

    def fill(self, selector, value, **kwargs):
        self.calls.append(("fill", selector, value, kwargs))

    def click(self, selector, **kwargs):
        self.calls.append(("click", selector, kwargs))
        if selector == '[data-testid="login-submit"]':
            self.url = "http://localhost/"
            self.requires_login = False
        if selector == '[data-testid="page-next"]':
            self.page_status = "Page 2"

    def wait_for_selector(self, selector, **kwargs):
        self.calls.append(("wait", selector, kwargs))

    def locator(self, selector):
        self.calls.append(("locator", selector))
        text = (
            "ERP server error"
            if selector == '[data-testid="erp-error"]'
            and getattr(self, "has_erp_error", False)
            else self.page_status
        )
        return FakeLocator(self.records, text)

    def screenshot(self, path, full_page=False):
        Path(path).write_bytes(b"fake-image")
        self.screenshot_path = (path, full_page)

    def wait_for_timeout(self, milliseconds):
        self.calls.append(("wait_timeout", milliseconds))

    @contextmanager
    def expect_download(self):
        yield type(
            "DownloadInfo",
            (),
            {"value": FakeDownload()},
        )()


class FlakyPage(FakePage):
    def __init__(self, records, failures):
        super().__init__(records)
        self.failures = failures

    def goto(self, url, **kwargs):
        if self.failures > 0:
            self.failures -= 1
            raise RuntimeError("temporary navigation failure")
        super().goto(url, **kwargs)


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

    def test_search_retries_transient_failure(self):
        page = FlakyPage(
            [{"invoice_id": "INV-1", "amount": "100.00"}],
            failures=1,
        )
        sleeps = []
        adapter = MockERPAdapter(
            page,
            "http://localhost",
            attempts=2,
            retry_delay_seconds=0.25,
            sleep_fn=sleeps.append,
        )

        result = adapter.search("INV-1")

        self.assertEqual(result.attempts, 2)
        self.assertEqual(len(result.retry_errors), 1)
        self.assertIn("temporary navigation failure", result.retry_errors[0])
        self.assertEqual(sleeps, [0.25])

    def test_permanent_failure_writes_diagnostics(self):
        page = FlakyPage([], failures=2)
        adapter = MockERPAdapter(
            page,
            "http://localhost",
            attempts=2,
            retry_delay_seconds=0,
        )

        with tempfile.TemporaryDirectory() as directory:
            screenshot = Path(directory) / "inv-1.png"
            with self.assertRaises(BrowserAdapterError) as context:
                adapter.search(
                    "INV-1",
                    screenshot_path=str(screenshot),
                )

            error = context.exception
            self.assertEqual(error.attempts, 2)
            self.assertEqual(len(error.failures), 2)
            self.assertTrue(Path(error.diagnostics_path).is_file())
            self.assertIn(
                "temporary navigation failure",
                Path(error.diagnostics_path).read_text(encoding="utf-8"),
            )

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
                "attempts": 1,
                "retry_errors": [],
            },
        )

    def test_selector_profile_loads_and_rejects_unknown_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            profile = root / "selectors.json"
            profile.write_text(
                json.dumps(
                    {
                        "invoice_input": "#invoice",
                        "search_submit": "#submit",
                        "record": ".record",
                    }
                ),
                encoding="utf-8",
            )

            selectors = ERPSelectors.from_file(profile)

            self.assertEqual(selectors.invoice_input, "#invoice")
            self.assertEqual(selectors.record, ".record")

            profile.write_text(
                json.dumps({"unknown": "#value"}),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                BrowserAdapterError,
                "unknown selector fields",
            ):
                ERPSelectors.from_file(profile)

    def test_login_pagination_and_csv_download(self):
        page = FakePage(
            [
                {"invoice_id": "INV-1", "amount": "100.00"},
                {"invoice_id": "INV-2", "amount": "200.00"},
            ]
        )
        page.url = "http://localhost/login"
        adapter = MockERPAdapter(
            page,
            "http://localhost",
            username="demo",
            password="demo",
        )

        login = adapter.login()
        first_page = adapter.list_page(page_size=2)
        next_page = adapter.next_page()
        with tempfile.TemporaryDirectory() as directory:
            exported = adapter.export_csv(
                Path(directory) / "erp.csv"
            )
            self.assertTrue(Path(exported).is_file())

        self.assertTrue(login.authenticated)
        self.assertEqual(first_page.records[0]["invoice_id"], "INV-1")
        self.assertEqual(next_page.page, 2)
        self.assertIn(
            (
                "fill",
                '[data-testid="login-username"]',
                "demo",
            ),
            [
                (call[0], call[1], call[2])
                for call in page.calls
                if call[0] == "fill"
            ],
        )

    def test_search_recovers_from_login_redirect(self):
        page = FakePage(
            [{"invoice_id": "INV-1", "amount": "100.00"}]
        )
        page.requires_login = True
        adapter = MockERPAdapter(
            page,
            "http://localhost",
            username="demo",
            password="demo",
        )

        result = adapter.search("INV-1")

        self.assertTrue(result.found)
        self.assertIn(
            (
                "fill",
                '[data-testid="login-username"]',
                "demo",
            ),
            [
                (call[0], call[1], call[2])
                for call in page.calls
                if call[0] == "fill"
            ],
        )


if __name__ == "__main__":
    unittest.main()
