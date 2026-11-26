"""Tests for applying operator reviews to all run artifacts."""

import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from openpyxl import load_workbook

from soc_agent.erp_reconciliation import (
    BrowserReconciliationReport,
    ERPLookupEvidence,
)
from soc_agent.evidence_bundle import create_evidence_bundle
from soc_agent.reconciliation import (
    ReconciliationReport,
    ReconciliationResult,
    ReconciliationStatus,
)
from soc_agent.reporting.reconciliation_report import (
    ReconciliationHTMLReportWriter,
)
from soc_agent.reporting.reconciliation_xlsx import (
    ReconciliationXLSXWriter,
)
from soc_agent.review_workflow import review_state, save_review
from soc_agent.reviews import ReviewError, ReviewStatus


class ReviewWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.run_dir = Path(self.temporary_directory.name) / "run-001"
        self.run_dir.mkdir()
        self.report = BrowserReconciliationReport(
            expected_csv="/tmp/expected.csv",
            reconciliation=ReconciliationReport(
                (
                    ReconciliationResult(
                        "INV-1",
                        ReconciliationStatus.MATCHED,
                        expected={"amount": "10.00"},
                        actual={"amount": "10.00"},
                    ),
                    ReconciliationResult(
                        "INV-2",
                        ReconciliationStatus.AMOUNT_MISMATCH,
                        expected={"amount": "20.00"},
                        actual={"amount": "21.00"},
                        differences=("amount mismatch",),
                    ),
                )
            ),
            lookups=(
                ERPLookupEvidence(
                    invoice_id="INV-2",
                    found=True,
                    record_count=1,
                    duplicate=False,
                    screenshot_path=None,
                ),
            ),
        )
        (self.run_dir / "reconciliation.json").write_text(
            json.dumps(
                self.report.to_dict(),
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        ReconciliationHTMLReportWriter().write(
            self.report,
            self.run_dir / "reconciliation.html",
        )
        ReconciliationXLSXWriter().write(
            self.report,
            self.run_dir / "reconciliation.xlsx",
        )

    def test_save_review_updates_json_html_xlsx_and_bundle(self):
        create_evidence_bundle(self.run_dir)

        state = save_review(
            self.run_dir,
            "INV-2",
            ReviewStatus.CONFIRMED,
            "operator-a",
            "供应商确认金额差异",
        )

        self.assertTrue(state["available"])
        self.assertEqual(state["review_summary"]["pending"], 0)
        self.assertEqual(state["review_summary"]["confirmed"], 1)
        self.assertTrue(state["bundle_refreshed"])
        report = json.loads(
            (self.run_dir / "reconciliation.json").read_text(
                encoding="utf-8"
            )
        )
        reviewed = next(
            item
            for item in report["reconciliation"]["results"]
            if item["invoice_id"] == "INV-2"
        )
        self.assertEqual(reviewed["status"], "amount_mismatch")
        self.assertEqual(reviewed["review"]["status"], "confirmed")
        self.assertEqual(report["review_summary"]["confirmed"], 1)
        self.assertTrue((self.run_dir / "review.json").is_file())
        self.assertIn(
            "已确认",
            (self.run_dir / "reconciliation.html").read_text(
                encoding="utf-8"
            ),
        )
        workbook = load_workbook(self.run_dir / "reconciliation.xlsx")
        try:
            results = workbook["Results"]
            self.assertEqual(results["N3"].value, "confirmed")
            self.assertEqual(results["O3"].value, "operator-a")
            self.assertEqual(results["P3"].value, "供应商确认金额差异")
        finally:
            workbook.close()
        with zipfile.ZipFile(
            self.run_dir / "evidence-bundle.zip"
        ) as archive:
            self.assertIn("review.json", archive.namelist())
            bundled_report = json.loads(
                archive.read("reconciliation.json").decode("utf-8")
            )
            self.assertEqual(
                bundled_report["review_summary"]["confirmed"],
                1,
            )

    def test_matched_or_unknown_invoice_cannot_be_reviewed(self):
        with self.assertRaises(ReviewError):
            save_review(
                self.run_dir,
                "INV-1",
                ReviewStatus.CONFIRMED,
                "operator-a",
            )
        with self.assertRaises(ReviewError):
            save_review(
                self.run_dir,
                "INV-X",
                ReviewStatus.CONFIRMED,
                "operator-a",
            )

    def test_review_state_lists_only_differences(self):
        state = review_state(self.run_dir)

        self.assertEqual(len(state["results"]), 1)
        self.assertEqual(state["results"][0]["invoice_id"], "INV-2")
        self.assertEqual(
            state["results"][0]["review"]["status"],
            "pending",
        )


if __name__ == "__main__":
    unittest.main()
