"""Tests for persisted reconciliation review decisions."""

import tempfile
import unittest
from pathlib import Path

from soc_agent.reconciliation import (
    ReconciliationReport,
    ReconciliationResult,
    ReconciliationStatus,
)
from soc_agent.reviews import (
    ReviewAuditError,
    ReviewAuditLog,
    ReviewError,
    ReviewRecord,
    ReviewStatus,
    ReviewStore,
    apply_reviews_to_payload,
    build_review_summary,
)


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.report = ReconciliationReport(
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
                ),
                ReconciliationResult(
                    "INV-3",
                    ReconciliationStatus.MISSING_IN_ERP,
                    expected={"amount": "30.00"},
                    actual=None,
                ),
            )
        )

    def test_store_persists_reviewer_decision(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "review.json"
            store = ReviewStore(path)
            store.set(
                "INV-2",
                ReviewStatus.CONFIRMED,
                "operator-a",
                "供应商已确认金额差异",
            )

            reloaded = ReviewStore(path)
            record = reloaded.get("inv-2")

        self.assertIsNotNone(record)
        self.assertEqual(record.status, ReviewStatus.CONFIRMED)
        self.assertEqual(record.reviewer, "operator-a")
        self.assertEqual(record.note, "供应商已确认金额差异")
        self.assertIsNotNone(record.updated_at)

    def test_summary_defaults_unrecorded_differences_to_pending(self):
        records = {
            "inv-2": ReviewRecord(
                "INV-2",
                ReviewStatus.CONFIRMED,
                "operator-a",
            )
        }

        summary = build_review_summary(self.report, records)

        self.assertEqual(summary["total_differences"], 2)
        self.assertEqual(summary["pending"], 1)
        self.assertEqual(summary["confirmed"], 1)
        self.assertEqual(summary["false_positive"], 0)
        self.assertFalse(summary["all_reviewed"])

    def test_payload_overlay_preserves_algorithm_result(self):
        records = {
            "inv-2": ReviewRecord(
                "INV-2",
                ReviewStatus.FALSE_POSITIVE,
                "operator-b",
                "ERP 页面曾返回缓存值",
            )
        }
        payload = {
            "reconciliation": self.report.to_dict(),
        }

        updated = apply_reviews_to_payload(payload, records)
        results = {
            item["invoice_id"]: item
            for item in updated["reconciliation"]["results"]
        }

        self.assertEqual(
            results["INV-2"]["status"],
            ReconciliationStatus.AMOUNT_MISMATCH.value,
        )
        self.assertEqual(
            results["INV-2"]["review"]["status"],
            ReviewStatus.FALSE_POSITIVE.value,
        )
        self.assertNotIn("review", results["INV-1"])
        self.assertEqual(updated["review_summary"]["pending"], 1)
        self.assertEqual(updated["review_summary"]["false_positive"], 1)

    def test_empty_reviewer_is_rejected(self):
        with self.assertRaises(ReviewError):
            ReviewRecord(
                "INV-2",
                ReviewStatus.CONFIRMED,
                " ",
            )

    def test_audit_log_detects_modified_event(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "review-audit.jsonl"
            audit = ReviewAuditLog(path)
            audit.append(
                "INV-2",
                None,
                ReviewRecord(
                    "INV-2",
                    ReviewStatus.CONFIRMED,
                    "operator-a",
                    "original",
                ),
            )
            lines = path.read_text(encoding="utf-8").splitlines()
            lines[0] = lines[0].replace("original", "tampered")
            path.write_text(
                "\n".join(lines) + "\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                ReviewAuditError,
                "hash mismatch",
            ):
                ReviewAuditLog(path)


if __name__ == "__main__":
    unittest.main()
