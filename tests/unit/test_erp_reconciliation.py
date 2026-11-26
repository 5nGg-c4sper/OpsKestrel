"""Tests for CSV-to-ERP browser reconciliation orchestration."""

import json
import tempfile
import unittest
from pathlib import Path

from soc_agent.browser import ERPSearchResult
from soc_agent.erp_reconciliation import (
    ReconciliationCheckpointError,
    reconcile_expected_csv_with_browser,
)


class FakeERPAdapter:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def search(self, invoice_id, screenshot_path=None):
        self.calls.append((invoice_id, screenshot_path))
        response = self.responses[invoice_id]
        if isinstance(response, Exception):
            raise response
        if screenshot_path:
            Path(screenshot_path).write_bytes(b"fake-image")
        return ERPSearchResult(
            invoice_id=invoice_id,
            base_url="http://localhost/",
            records=tuple(response),
            screenshot_path=screenshot_path,
        )


class ERPReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        self.expected_csv = self.root / "expected.csv"
        self.expected_csv.write_text(
            "\n".join(
                [
                    (
                        "invoice_id,customer_id,currency,expected_amount,"
                        "expected_status,due_date"
                    ),
                    (
                        "INV-1,CUST-1,CNY,100.00,paid,2026-11-20"
                    ),
                    (
                        "INV-2,CUST-2,CNY,200.00,pending,2026-11-21"
                    ),
                    (
                        "INV-3,CUST-3,CNY,300.00,paid,2026-11-22"
                    ),
                    (
                        "INV-4,CUST-4,CNY,400.00,pending,2026-11-23"
                    ),
                ]
            )
            + "\n",
            encoding="utf-8",
        )

    def record(self, invoice_id, amount, status="paid"):
        return {
            "invoice_id": invoice_id,
            "customer_id": f"CUST-{invoice_id[-1]}",
            "currency": "CNY",
            "amount": amount,
            "status": status,
            "due_date": f"2026-11-2{invoice_id[-1]}",
        }

    def test_batch_collects_browser_records_and_reconciles(self):
        adapter = FakeERPAdapter(
            {
                "INV-1": [self.record("INV-1", "100.00")],
                "INV-2": [],
                "INV-3": [
                    self.record("INV-3", "300.00"),
                    self.record("INV-3", "300.00"),
                ],
                "INV-4": [
                    self.record("INV-4", "450.00", status="pending")
                ],
            }
        )
        screenshot_dir = self.root / "screenshots"

        report = reconcile_expected_csv_with_browser(
            self.expected_csv,
            adapter,
            screenshot_dir=screenshot_dir,
        )

        self.assertEqual(len(adapter.calls), 4)
        self.assertEqual(len(report.lookups), 4)
        self.assertEqual(
            report.reconciliation.summary["by_status"],
            {
                "matched": 1,
                "amount_mismatch": 1,
                "currency_mismatch": 0,
                "status_mismatch": 0,
                "missing_in_erp": 1,
                "duplicate_in_erp": 1,
                "invalid_input": 0,
            },
        )
        self.assertTrue(
            (screenshot_dir / "inv-1.png").is_file()
        )
        self.assertEqual(report.collection_errors, ())

    def test_collection_error_is_preserved(self):
        adapter = FakeERPAdapter(
            {
                "INV-1": RuntimeError("browser failed"),
                "INV-2": [],
                "INV-3": [],
                "INV-4": [],
            }
        )

        report = reconcile_expected_csv_with_browser(
            self.expected_csv,
            adapter,
        )

        self.assertEqual(len(report.collection_errors), 1)
        self.assertEqual(
            report.collection_errors[0].invoice_id,
            "INV-1",
        )
        self.assertIn(
            "browser failed",
            report.collection_errors[0].error,
        )

    def test_report_serializes_collection_and_reconciliation(self):
        adapter = FakeERPAdapter(
            {
                "INV-1": [self.record("INV-1", "100.00")],
                "INV-2": [],
                "INV-3": [],
                "INV-4": [],
            }
        )
        report = reconcile_expected_csv_with_browser(
            self.expected_csv,
            adapter,
        )

        payload = report.to_dict()

        self.assertEqual(payload["collection"]["lookups"], 4)
        self.assertEqual(payload["collection"]["errors"], 0)
        self.assertEqual(payload["reconciliation"]["summary"]["total"], 4)
        self.assertEqual(len(payload["lookups"]), 4)

    def test_checkpoint_reuses_successful_browser_lookups(self):
        responses = {
            "INV-1": [self.record("INV-1", "100.00")],
            "INV-2": [],
            "INV-3": [],
            "INV-4": [],
        }
        checkpoint = self.root / "checkpoint.json"
        first_adapter = FakeERPAdapter(responses)

        first = reconcile_expected_csv_with_browser(
            self.expected_csv,
            first_adapter,
            checkpoint_path=checkpoint,
        )
        second_adapter = FakeERPAdapter({})
        second = reconcile_expected_csv_with_browser(
            self.expected_csv,
            second_adapter,
            checkpoint_path=checkpoint,
        )

        self.assertEqual(len(first_adapter.calls), 4)
        self.assertEqual(second_adapter.calls, [])
        self.assertEqual(len(second.cached_lookups), 4)
        self.assertEqual(
            first.reconciliation.to_dict(),
            second.reconciliation.to_dict(),
        )
        self.assertEqual(
            second.to_dict()["collection"]["cached"],
            4,
        )

    def test_checkpoint_resumes_only_missing_invoice(self):
        checkpoint = self.root / "resume.json"
        first_adapter = FakeERPAdapter(
            {
                "INV-1": RuntimeError("browser failed"),
                "INV-2": [],
                "INV-3": [],
                "INV-4": [],
            }
        )

        reconcile_expected_csv_with_browser(
            self.expected_csv,
            first_adapter,
            checkpoint_path=checkpoint,
        )
        second_adapter = FakeERPAdapter(
            {"INV-1": [self.record("INV-1", "100.00")]}
        )
        resumed = reconcile_expected_csv_with_browser(
            self.expected_csv,
            second_adapter,
            checkpoint_path=checkpoint,
        )

        self.assertEqual(second_adapter.calls[0][0], "INV-1")
        self.assertEqual(len(second_adapter.calls), 1)
        self.assertEqual(len(resumed.cached_lookups), 3)
        self.assertEqual(resumed.collection_errors, ())
        self.assertEqual(
            resumed.reconciliation.summary["by_status"]["matched"],
            1,
        )

    def test_checkpoint_rejects_changed_expected_csv(self):
        checkpoint = self.root / "changed.json"
        reconcile_expected_csv_with_browser(
            self.expected_csv,
            FakeERPAdapter(
                {
                    "INV-1": [],
                    "INV-2": [],
                    "INV-3": [],
                    "INV-4": [],
                }
            ),
            checkpoint_path=checkpoint,
        )
        self.expected_csv.write_text(
            self.expected_csv.read_text(encoding="utf-8")
            + "INV-5,CUST-5,CNY,500.00,paid,2026-11-24\n",
            encoding="utf-8",
        )

        with self.assertRaises(ReconciliationCheckpointError):
            reconcile_expected_csv_with_browser(
                self.expected_csv,
                FakeERPAdapter({}),
                checkpoint_path=checkpoint,
            )


if __name__ == "__main__":
    unittest.main()
