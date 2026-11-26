"""Tests for the enterprise-like Mock ERP."""

import json
import threading
import time
import tempfile
import unittest
from http.cookiejar import CookieJar
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import (
    HTTPCookieProcessor,
    Request,
    build_opener,
)

from soc_agent.mock_erp_enterprise import (
    EnterpriseERPConfig,
    create_enterprise_erp_server,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ERP_FIXTURE = (
    PROJECT_ROOT
    / "scenarios"
    / "invoice_reconciliation"
    / "data"
    / "erp_invoices.json"
)


class EnterpriseMockERPTests(unittest.TestCase):
    def start_server(self, config=None):
        self.server = create_enterprise_erp_server(
            ERP_FIXTURE,
            config=config or EnterpriseERPConfig(),
        )
        self.thread = threading.Thread(
            target=self.server.serve_forever,
            daemon=True,
        )
        self.thread.start()
        self.base_url = (
            f"http://{self.server.server_address[0]}:"
            f"{self.server.server_address[1]}"
        )
        self.cookies = CookieJar()
        self.opener = build_opener(HTTPCookieProcessor(self.cookies))
        self.addCleanup(self.stop_server)

    def stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def request_json(
        self,
        path,
        method="GET",
        payload=None,
    ):
        data = None
        headers = {}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = Request(
            self.base_url + path,
            data=data,
            headers=headers,
            method=method,
        )
        with self.opener.open(request, timeout=2) as response:
            return response.status, json.loads(
                response.read().decode("utf-8")
            )

    def login(self):
        return self.request_json(
            "/api/login",
            method="POST",
            payload={"username": "demo", "password": "demo"},
        )

    def test_login_page_and_successful_session(self):
        self.start_server()

        with self.opener.open(self.base_url + "/", timeout=2) as response:
            html = response.read().decode("utf-8")

        self.assertIn('data-testid="login-username"', html)
        status, payload = self.login()
        self.assertEqual(status, 200)
        self.assertTrue(payload["authenticated"])
        status, session = self.request_json("/api/session")
        self.assertEqual(status, 200)
        self.assertTrue(session["authenticated"])

    def test_invalid_login_and_logout(self):
        self.start_server()

        with self.assertRaises(HTTPError) as context:
            self.request_json(
                "/api/login",
                method="POST",
                payload={"username": "demo", "password": "bad"},
            )
        error = context.exception
        self.assertEqual(error.code, 401)
        error.close()

        self.login()
        self.request_json("/api/logout", method="POST")
        with self.assertRaises(HTTPError) as context:
            self.request_json("/api/invoices")
        error = context.exception
        self.assertEqual(error.code, 401)
        error.close()

    def test_pagination_and_csv_export(self):
        self.start_server()
        self.login()

        _, first_page = self.request_json(
            "/api/invoices?page=1&page_size=5"
        )
        _, second_page = self.request_json(
            "/api/invoices?page=2&page_size=5"
        )

        self.assertEqual(first_page["count"], 5)
        self.assertEqual(first_page["total"], 17)
        self.assertEqual(first_page["page"], 1)
        self.assertEqual(second_page["page"], 2)
        self.assertNotEqual(
            first_page["records"][0]["invoice_id"],
            second_page["records"][0]["invoice_id"],
        )

        with self.opener.open(
            self.base_url + "/api/export.csv",
            timeout=2,
        ) as response:
            csv_content = response.read().decode("utf-8-sig")
        self.assertTrue(csv_content.startswith("invoice_id,customer_id"))
        self.assertIn("INV-1001", csv_content)

    def test_failure_injection_succeeds_on_retry(self):
        self.start_server(
            EnterpriseERPConfig(
                fail_once_invoices={"INV-1001": 1},
            )
        )
        self.login()

        with self.assertRaises(HTTPError) as context:
            self.request_json(
                "/api/invoices?invoice_id=INV-1001"
            )
        error = context.exception
        self.assertEqual(error.code, 503)
        error.close()

        status, payload = self.request_json(
            "/api/invoices?invoice_id=INV-1001"
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["count"], 1)

    def test_slow_invoice_injection(self):
        self.start_server(
            EnterpriseERPConfig(
                slow_invoices={"INV-1001": 0.05},
            )
        )
        self.login()

        started = time.monotonic()
        self.request_json("/api/invoices?invoice_id=INV-1001")
        elapsed = time.monotonic() - started

        self.assertGreaterEqual(elapsed, 0.04)

    def test_session_expires_and_requires_login(self):
        self.start_server(
            EnterpriseERPConfig(session_ttl_seconds=0.05)
        )
        self.login()
        time.sleep(0.07)

        with self.assertRaises(HTTPError) as context:
            self.request_json("/api/invoices")

        error = context.exception
        self.assertEqual(error.code, 401)
        error.close()

    def test_failure_config_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "failures.json"
            path.write_text(
                json.dumps({"unknown": {}}),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                ValueError,
                "unknown failure config",
            ):
                EnterpriseERPConfig.from_file(path)


if __name__ == "__main__":
    unittest.main()
