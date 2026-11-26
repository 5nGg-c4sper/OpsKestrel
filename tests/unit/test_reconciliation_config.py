"""Tests for reconciliation field mapping and normalization."""

import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from soc_agent.reconciliation import reconcile_files
from soc_agent.reconciliation_config import (
    ReconciliationConfig,
    ReconciliationConfigError,
)


class ReconciliationConfigTests(unittest.TestCase):
    def test_maps_chinese_columns_status_and_currency(self):
        config = ReconciliationConfig(
            expected_columns={
                "invoice_id": "发票号",
                "customer_id": "客户号",
                "currency": "币种",
                "amount": "应收金额",
                "status": "状态",
                "due_date": "到期日",
            },
            status_aliases={"已支付": "paid"},
            currency_aliases={"人民币": "CNY"},
        )

        mapped = config.map_expected_row(
            {
                "发票号": "INV-1",
                "客户号": "CUST-1",
                "币种": "人民币",
                "应收金额": "100.00",
                "状态": "已支付",
                "到期日": "2026-11-20",
            }
        )

        self.assertEqual(mapped["invoice_id"], "INV-1")
        self.assertEqual(mapped["currency"], "CNY")
        self.assertEqual(mapped["expected_status"], "paid")
        self.assertEqual(mapped["expected_amount"], "100.00")

    def test_config_file_and_fingerprint_are_stable(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "mapping.json"
            payload = {
                "amount_tolerance": "0.02",
                "status_aliases": {"待审核": "pending"},
                "currency_aliases": {"美元": "USD"},
            }
            path.write_text(
                json.dumps(payload, ensure_ascii=False),
                encoding="utf-8",
            )

            first = ReconciliationConfig.from_file(path)
            second = ReconciliationConfig.from_file(path)

        self.assertEqual(first.amount_tolerance, Decimal("0.02"))
        self.assertEqual(first.fingerprint(), second.fingerprint())
        self.assertEqual(len(first.fingerprint()), 64)

    def test_config_rejects_unknown_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "mapping.json"
            path.write_text(
                json.dumps({"unknown": True}),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                ReconciliationConfigError,
                "unknown reconciliation config",
            ):
                ReconciliationConfig.from_file(path)

    def test_reconcile_files_applies_config(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            expected = root / "expected.csv"
            expected.write_text(
                "\n".join(
                    [
                        "发票号,客户号,币种,应收金额,状态,到期日",
                        "INV-1,CUST-1,人民币,100.00,已支付,2026-11-20",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            erp = root / "erp.json"
            erp.write_text(
                json.dumps(
                    {
                        "invoices": [
                            {
                                "invoice_id": "INV-1",
                                "customer_id": "CUST-1",
                                "currency": "CNY",
                                "amount": "100.00",
                                "status": "paid",
                                "due_date": "2026-11-20",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            config = ReconciliationConfig(
                expected_columns={
                    "invoice_id": "发票号",
                    "customer_id": "客户号",
                    "currency": "币种",
                    "amount": "应收金额",
                    "status": "状态",
                    "due_date": "到期日",
                },
                status_aliases={"已支付": "paid"},
                currency_aliases={"人民币": "CNY"},
            )

            report = reconcile_files(
                expected,
                erp,
                config=config,
            )

        self.assertEqual(report.summary["by_status"]["matched"], 1)


if __name__ == "__main__":
    unittest.main()
