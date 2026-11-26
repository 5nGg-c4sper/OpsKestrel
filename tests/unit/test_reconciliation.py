"""Tests for deterministic invoice reconciliation."""

import unittest
import tempfile
from pathlib import Path

from openpyxl import Workbook
from reportlab.pdfgen import canvas

from soc_agent.reconciliation import (
    ReconciliationStatus,
    load_expected_invoices,
    reconcile_files,
    reconcile_invoices,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class ReconciliationTests(unittest.TestCase):
    def expected(self, **updates):
        row = {
            "invoice_id": "INV-1",
            "customer_id": "CUST-1",
            "currency": "CNY",
            "expected_amount": "100.00",
            "expected_status": "paid",
            "due_date": "2026-11-20",
        }
        row.update(updates)
        return row

    def erp(self, **updates):
        row = {
            "invoice_id": "INV-1",
            "customer_id": "CUST-1",
            "currency": "CNY",
            "amount": "100.00",
            "status": "paid",
            "due_date": "2026-11-20",
        }
        row.update(updates)
        return row

    def result_for(self, report, invoice_id):
        return next(
            result
            for result in report.results
            if result.invoice_id == invoice_id
        )

    def test_fixture_covers_every_reconciliation_outcome(self):
        report = reconcile_files(
            PROJECT_ROOT
            / "scenarios"
            / "invoice_reconciliation"
            / "data"
            / "input_invoices.csv",
            PROJECT_ROOT
            / "scenarios"
            / "invoice_reconciliation"
            / "data"
            / "erp_invoices.json",
        )

        self.assertEqual(report.summary["total"], 20)
        self.assertEqual(
            report.summary["by_status"],
            {
                "matched": 10,
                "amount_mismatch": 2,
                "currency_mismatch": 1,
                "status_mismatch": 1,
                "missing_in_erp": 2,
                "duplicate_in_erp": 1,
                "invalid_input": 3,
            },
        )
        self.assertEqual(
            self.result_for(report, "INV-1011").status,
            ReconciliationStatus.AMOUNT_MISMATCH,
        )
        self.assertEqual(
            self.result_for(report, "INV-1014").status,
            ReconciliationStatus.CURRENCY_MISMATCH,
        )
        self.assertEqual(
            self.result_for(report, "INV-1015").status,
            ReconciliationStatus.MISSING_IN_ERP,
        )
        self.assertEqual(
            self.result_for(report, "INV-1017").status,
            ReconciliationStatus.DUPLICATE_IN_ERP,
        )

    def test_results_are_sorted_deterministically(self):
        expected_rows = [
            self.expected(invoice_id="INV-2"),
            self.expected(invoice_id="INV-1"),
        ]
        erp_rows = [
            self.erp(invoice_id="INV-2"),
            self.erp(invoice_id="INV-1"),
        ]

        first = reconcile_invoices(expected_rows, erp_rows)
        second = reconcile_invoices(
            reversed(expected_rows),
            reversed(erp_rows),
        )

        self.assertEqual(
            [result.invoice_id for result in first.results],
            ["INV-1", "INV-2"],
        )
        self.assertEqual(first.to_dict(), second.to_dict())

    def test_amount_tolerance_is_configurable(self):
        within = reconcile_invoices(
            [self.expected(expected_amount="100.00")],
            [self.erp(amount="100.01")],
            amount_tolerance="0.01",
        )
        outside = reconcile_invoices(
            [self.expected(expected_amount="100.00")],
            [self.erp(amount="100.02")],
            amount_tolerance="0.01",
        )

        self.assertEqual(
            within.results[0].status,
            ReconciliationStatus.MATCHED,
        )
        self.assertEqual(
            outside.results[0].status,
            ReconciliationStatus.AMOUNT_MISMATCH,
        )

    def test_duplicate_expected_invoice_is_invalid(self):
        report = reconcile_invoices(
            [self.expected(), self.expected()],
            [self.erp()],
        )

        self.assertEqual(len(report.results), 2)
        self.assertTrue(
            all(
                result.status == ReconciliationStatus.INVALID_INPUT
                for result in report.results
            )
        )
        self.assertIn(
            "duplicate expected",
            report.results[0].error,
        )

    def test_invalid_erp_row_is_linked_to_expected_invoice(self):
        report = reconcile_invoices(
            [self.expected()],
            [self.erp(amount="invalid")],
        )

        self.assertEqual(len(report.results), 1)
        self.assertEqual(
            report.results[0].status,
            ReconciliationStatus.INVALID_INPUT,
        )
        self.assertEqual(
            report.results[0].actual["amount"],
            "invalid",
        )

    def test_report_serializes_decimal_values_as_strings(self):
        report = reconcile_invoices(
            [self.expected()],
            [self.erp()],
        )

        payload = report.to_dict()

        self.assertTrue(payload["summary"]["all_matched"])
        self.assertEqual(
            payload["results"][0]["expected"]["amount"],
            "100.00",
        )
        self.assertEqual(
            payload["results"][0]["actual"]["amount"],
            "100.00",
        )

    def test_xlsx_expected_invoice_input_is_supported(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invoices.xlsx"
            workbook = Workbook()
            sheet = workbook.active
            sheet.append(
                [
                    "invoice_id",
                    "customer_id",
                    "currency",
                    "expected_amount",
                    "expected_status",
                    "due_date",
                ]
            )
            sheet.append(
                [
                    "INV-XLSX",
                    "CUST-X",
                    "CNY",
                    100.5,
                    "paid",
                    "2026-11-20",
                ]
            )
            workbook.save(path)

            rows = load_expected_invoices(path)

        self.assertEqual(rows[0]["invoice_id"], "INV-XLSX")
        self.assertEqual(rows[0]["expected_amount"], "100.5")

    def test_pdf_expected_invoice_input_is_supported(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invoices.pdf"
            document = canvas.Canvas(str(path))
            lines = [
                "Invoice ID: INV-PDF-1",
                "Customer ID: CUST-PDF",
                "Currency: CNY",
                "Expected Amount: 99.50",
                "Expected Status: paid",
                "Due Date: 2026-12-01",
            ]
            y = 800
            for line in lines:
                document.drawString(72, y, line)
                y -= 24
            document.showPage()
            document.save()

            rows = load_expected_invoices(path)

        self.assertEqual(rows[0]["invoice_id"], "INV-PDF-1")
        self.assertEqual(rows[0]["expected_amount"], "99.50")
        self.assertEqual(rows[0]["due_date"], "2026-12-01")


if __name__ == "__main__":
    unittest.main()
