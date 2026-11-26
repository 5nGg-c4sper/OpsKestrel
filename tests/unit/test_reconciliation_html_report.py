"""Tests for filterable invoice reconciliation HTML reports."""

import tempfile
import unittest
from pathlib import Path

from opskestrel.erp_reconciliation import (
    BrowserReconciliationReport,
    ERPLookupEvidence,
)
from opskestrel.reconciliation import (
    ReconciliationReport,
    ReconciliationResult,
    ReconciliationStatus,
)
from opskestrel.reporting.reconciliation_report import (
    ReconciliationHTMLReportWriter,
)


class ReconciliationHTMLReportTests(unittest.TestCase):
    def test_writer_renders_summary_filters_search_and_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            screenshot = root / "evidence" / "inv-1.png"
            screenshot.parent.mkdir()
            screenshot.write_bytes(b"image")
            reconciliation = ReconciliationReport(
                (
                    ReconciliationResult(
                        "INV-1",
                        ReconciliationStatus.AMOUNT_MISMATCH,
                        expected={
                            "amount": "100.00",
                            "note": "<script>bad()</script>",
                        },
                        actual={"amount": "120.00"},
                        differences=(
                            "amount: 100.00 != 120.00",
                            "<script>bad()</script>",
                        ),
                    ),
                    ReconciliationResult(
                        "INV-2",
                        ReconciliationStatus.MATCHED,
                        expected={"amount": "50.00"},
                        actual={"amount": "50.00"},
                    ),
                )
            )
            report = BrowserReconciliationReport(
                expected_csv="/tmp/expected.csv",
                reconciliation=reconciliation,
                lookups=(
                    ERPLookupEvidence(
                        invoice_id="INV-1",
                        found=True,
                        record_count=1,
                        duplicate=False,
                        screenshot_path=str(screenshot),
                        attempts=2,
                        cached=True,
                    ),
                    ERPLookupEvidence(
                        invoice_id="INV-2",
                        found=True,
                        record_count=1,
                        duplicate=False,
                        screenshot_path=None,
                    ),
                ),
            )
            output = root / "reports" / "reconciliation.html"

            path = ReconciliationHTMLReportWriter().write(
                report,
                output,
            )
            html = path.read_text(encoding="utf-8")

        self.assertEqual(path, output.resolve())
        self.assertIn("ERP 发票对账报告", html)
        self.assertIn('data-filter="amount_mismatch"', html)
        self.assertIn('id="invoice-filter"', html)
        self.assertIn("INV-1", html)
        self.assertIn("amount: 100.00 != 120.00", html)
        self.assertIn("../evidence/inv-1.png", html)
        self.assertIn("缓存命中", html)
        self.assertIn("重试 2 次", html)
        self.assertNotIn("<script>bad()</script>", html)
        self.assertIn("&lt;script&gt;bad()&lt;/script&gt;", html)

    def test_writer_renders_collection_errors(self):
        reconciliation = ReconciliationReport(())
        report = BrowserReconciliationReport(
            expected_csv="/tmp/expected.csv",
            reconciliation=reconciliation,
            lookups=(
                ERPLookupEvidence(
                    invoice_id="INV-X",
                    found=False,
                    record_count=0,
                    duplicate=False,
                    screenshot_path=None,
                    error="browser disconnected",
                ),
            ),
        )

        html = ReconciliationHTMLReportWriter().render(
            report,
            Path("/tmp"),
        )

        self.assertIn("浏览器采集错误", html)
        self.assertIn("browser disconnected", html)
        self.assertIn(
            "采集错误</span><strong>1</strong>",
            html,
        )


if __name__ == "__main__":
    unittest.main()
