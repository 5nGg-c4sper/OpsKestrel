"""Tests for Excel invoice reconciliation reports."""

import tempfile
import unittest
from pathlib import Path

from openpyxl import load_workbook

from soc_agent.erp_reconciliation import (
    BrowserReconciliationReport,
    ERPLookupEvidence,
)
from soc_agent.reconciliation import (
    ReconciliationReport,
    ReconciliationResult,
    ReconciliationStatus,
)
from soc_agent.reporting.reconciliation_xlsx import (
    ReconciliationXLSXWriter,
)
from soc_agent.reviews import ReviewRecord, ReviewStatus


class ReconciliationXLSXTests(unittest.TestCase):
    def test_workbook_contains_summary_results_and_links(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            screenshot = root / "inv-1.png"
            screenshot.write_bytes(b"image")
            report = BrowserReconciliationReport(
                expected_csv="/tmp/expected.csv",
                reconciliation=ReconciliationReport(
                    (
                        ReconciliationResult(
                            "INV-1",
                            ReconciliationStatus.AMOUNT_MISMATCH,
                            expected={
                                "amount": "100.00",
                                "currency": "CNY",
                                "status": "paid",
                            },
                            actual={
                                "amount": "120.00",
                                "currency": "CNY",
                                "status": "paid",
                            },
                            differences=("amount mismatch",),
                        ),
                    )
                ),
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
                ),
            )
            output = root / "report.xlsx"

            path = ReconciliationXLSXWriter().write(
                report,
                output,
                reviews={
                    "inv-1": ReviewRecord(
                        "INV-1",
                        ReviewStatus.CONFIRMED,
                        "+operator",
                        "=SUM(1,2)",
                    )
                },
            )
            workbook = load_workbook(path)
            try:
                self.assertEqual(
                    workbook.sheetnames,
                    ["Summary", "Results", "Collection"],
                )
                summary = workbook["Summary"]
                results = workbook["Results"]
                collection = workbook["Collection"]
                self.assertEqual(summary["A2"].value, "Total invoices")
                self.assertEqual(summary["B2"].value, 1)
                self.assertEqual(results["A2"].value, "INV-1")
                self.assertEqual(results["B2"].value, "amount_mismatch")
                self.assertTrue(results["L2"].hyperlink)
                self.assertEqual(results["N2"].value, "confirmed")
                self.assertEqual(results["O2"].value, "'+operator")
                self.assertEqual(results["P2"].value, "'=SUM(1,2)")
                self.assertEqual(collection["E2"].value, 2)
                self.assertEqual(collection["F2"].value, "yes")
            finally:
                workbook.close()

        self.assertEqual(path, output.resolve())


if __name__ == "__main__":
    unittest.main()
