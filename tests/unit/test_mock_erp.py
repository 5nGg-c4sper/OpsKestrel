"""Tests for the local Mock ERP browser fixture."""

import json
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen

from soc_agent.mock_erp import create_mock_erp_server


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ERP_FIXTURE = (
    PROJECT_ROOT
    / "scenarios"
    / "invoice_reconciliation"
    / "data"
    / "erp_invoices.json"
)


class MockERPServerTests(unittest.TestCase):
    def setUp(self):
        self.server = create_mock_erp_server(ERP_FIXTURE)
        self.thread = threading.Thread(
            target=self.server.serve_forever,
            daemon=True,
        )
        self.thread.start()
        self.base_url = (
            f"http://{self.server.server_address[0]}:"
            f"{self.server.server_address[1]}"
        )

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def get_json(self, path):
        with urlopen(self.base_url + path, timeout=2) as response:
            return response.status, json.loads(
                response.read().decode("utf-8")
            )

    def test_home_page_exposes_stable_browser_selectors(self):
        with urlopen(self.base_url + "/", timeout=2) as response:
            html = response.read().decode("utf-8")

        self.assertEqual(response.status, 200)
        self.assertIn('data-testid="invoice-id-input"', html)
        self.assertIn('data-testid="invoice-search-submit"', html)
        self.assertIn('"invoice-record"', html)
        self.assertIn("dataset.field", html)

    def test_health_reports_unique_invoice_count(self):
        status, payload = self.get_json("/health")

        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["unique_invoices"], 16)

    def test_search_returns_invoice_fields(self):
        status, payload = self.get_json(
            "/api/invoices?invoice_id=INV-1001"
        )

        self.assertEqual(status, 200)
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["records"][0]["amount"], "1200.00")
        self.assertEqual(payload["records"][0]["status"], "paid")

    def test_search_returns_all_duplicate_records(self):
        _, payload = self.get_json(
            "/api/invoices?invoice_id=INV-1017"
        )

        self.assertEqual(payload["count"], 2)
        self.assertEqual(len(payload["records"]), 2)

    def test_missing_invoice_returns_404(self):
        with self.assertRaises(HTTPError) as context:
            urlopen(
                self.base_url + "/api/invoices?invoice_id=UNKNOWN",
                timeout=2,
            )

        self.assertEqual(context.exception.code, 404)
