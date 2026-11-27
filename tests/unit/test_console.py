"""Tests for the local OpsKestrel operations console."""

import json
import sys
import tempfile
import threading
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from opskestrel.console import create_console_server
from opskestrel.queue_models import QueueWorkerRecord, WorkerState


class FakeQueueStore:
    def list_workers(self, online_within_seconds=None):
        now = datetime.now(timezone.utc)
        return [
            QueueWorkerRecord(
                worker_id="office-mac-1",
                hostname="macbook",
                pid=123,
                state=WorkerState.IDLE,
                labels=["office-mac"],
                started_at=now,
                last_heartbeat=now,
            )
        ]


class ConsoleTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        self.reports = self.root / "reports"
        self.reports.mkdir()
        (self.reports / "report.json").write_text(
            json.dumps(
                {
                    "dataset_name": "invoice_demo",
                    "status": "passed",
                    "duration_seconds": 12.5,
                }
            ),
            encoding="utf-8",
        )
        self.server = create_console_server(
            project_root=self.root,
            reports_dir=self.reports,
            queue_db=self.root / "queue.db",
            command_factory=lambda output_dir: [
                sys.executable,
                "-c",
                "pass",
            ],
            upload_command_factory=lambda output_dir, input_path: [
                sys.executable,
                "-c",
                "pass",
            ],
            operator_name="operator-a",
            operator_token="test-token",
            operator_role="admin",
        )
        self.server.state.overview = lambda: {
            "reports": [
                {
                    "name": "invoice_demo",
                    "type": "dataset",
                    "status": "passed",
                    "duration_seconds": 12.5,
                    "updated_at": time.time(),
                    "url": "/files/report.json",
                }
            ],
            "workers": [
                {
                    "worker_id": "office-mac-1",
                    "state": "idle",
                }
            ],
            "worker_error": None,
            "demo": self.server.state.demo_status(),
        }
        self.thread = threading.Thread(
            target=self.server.serve_forever,
            daemon=True,
        )
        self.thread.start()
        self.base_url = (
            f"http://{self.server.server_address[0]}:"
            f"{self.server.server_address[1]}"
        )
        self.addCleanup(self.stop_server)

    def stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def get_json(self, path, headers=None):
        request = Request(
            self.base_url + path,
            headers=headers or {},
            method="GET",
        )
        with urlopen(request, timeout=2) as response:
            return response.status, json.loads(
                response.read().decode("utf-8")
            )

    @property
    def auth_headers(self):
        return {"Authorization": "Bearer test-token"}

    def post_json(self, path, payload, authenticated=True):
        headers = {"Content-Type": "application/json"}
        if authenticated:
            headers.update(self.auth_headers)
        request = Request(
            self.base_url + path,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with urlopen(request, timeout=3) as response:
            return response.status, json.loads(
                response.read().decode("utf-8")
            )

    def write_reconciliation_run(self):
        run_dir = self.reports / "console-review-001"
        run_dir.mkdir()
        payload = {
            "expected_csv": "/tmp/expected.csv",
            "checkpoint_path": None,
            "collection": {
                "lookups": 1,
                "errors": 0,
                "cached": 0,
                "retried": 0,
            },
            "reconciliation": {
                "summary": {
                    "total": 1,
                    "by_status": {
                        "matched": 0,
                        "amount_mismatch": 1,
                        "currency_mismatch": 0,
                        "status_mismatch": 0,
                        "missing_in_erp": 0,
                        "duplicate_in_erp": 0,
                        "invalid_input": 0,
                    },
                    "all_matched": False,
                },
                "results": [
                    {
                        "invoice_id": "INV-1",
                        "status": "amount_mismatch",
                        "expected": {"amount": "100.00"},
                        "actual": {"amount": "120.00"},
                        "differences": ["amount mismatch"],
                        "error": None,
                    }
                ],
            },
            "lookups": [
                {
                    "invoice_id": "INV-1",
                    "found": True,
                    "record_count": 1,
                    "duplicate": False,
                    "screenshot_path": None,
                    "error": None,
                    "attempts": 1,
                    "retry_errors": [],
                    "diagnostics_path": None,
                    "cached": False,
                }
            ],
        }
        (run_dir / "reconciliation.json").write_text(
            json.dumps(payload),
            encoding="utf-8",
        )
        return run_dir

    def test_console_html_and_overview(self):
        with urlopen(self.base_url + "/", timeout=2) as response:
            html = response.read().decode("utf-8")
        status, payload = self.get_json("/api/overview")

        self.assertEqual(response.status, 200)
        self.assertIn("OpsKestrel Console", html)
        self.assertIn('<div id="root"></div>', html)
        self.assertIn("/assets/", html)
        self.assertEqual(status, 200)
        self.assertEqual(payload["reports"][0]["status"], "passed")
        self.assertEqual(len(payload["workers"]), 1)

    def test_console_assets_are_served_without_path_traversal(self):
        asset_dir = (
            Path(__file__).resolve().parents[2]
            / "opskestrel"
            / "console_static"
            / "assets"
        )
        script = next(asset_dir.glob("index-*.js"))
        with urlopen(
            self.base_url + f"/assets/{script.name}",
            timeout=2,
        ) as response:
            content = response.read()
        self.assertEqual(response.status, 200)
        self.assertIn(
            "javascript",
            response.headers.get("Content-Type", ""),
        )
        self.assertGreater(len(content), 1000)

        request = Request(
            self.base_url + "/assets/../console.py",
            method="GET",
        )
        with self.assertRaises(HTTPError) as context:
            urlopen(request, timeout=2)
        error = context.exception
        self.assertEqual(error.code, 404)
        error.close()

    def test_health_endpoint_reports_runtime_checks(self):
        status, payload = self.get_json("/healthz")

        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["service"], "opskestrel-console")
        self.assertTrue(payload["checks"]["reports_writable"])
        self.assertTrue(
            payload["checks"]["operator_authentication_configured"]
        )

    def test_idle_demo_status_has_complete_frontend_shape(self):
        status, payload = self.get_json("/api/demo/status")

        self.assertEqual(status, 200)
        self.assertEqual(payload["state"], "idle")
        self.assertEqual(payload["log_tail"], [])
        self.assertEqual(payload["artifacts"], [])
        self.assertIn("history", payload)

    def test_report_file_is_served_and_traversal_is_rejected(self):
        with urlopen(
            self.base_url + "/files/report.json",
            timeout=2,
        ) as response:
            content = response.read().decode("utf-8")
        self.assertIn("invoice_demo", content)

        request = Request(
            self.base_url + "/files/../secret.txt",
            method="GET",
        )
        with self.assertRaises(HTTPError) as context:
            urlopen(request, timeout=2)
        error = context.exception
        self.assertEqual(error.code, 404)
        error.close()

    def test_demo_can_start_and_finish(self):
        request = Request(
            self.base_url + "/api/demo/run",
            data=b"",
            method="POST",
        )
        with urlopen(request, timeout=2) as response:
            payload = json.loads(response.read().decode("utf-8"))

        self.assertEqual(response.status, 202)
        self.assertTrue(payload["started"])
        for _ in range(20):
            _, status = self.get_json("/api/demo/status")
            if status["state"] == "finished":
                break
            time.sleep(0.01)
        self.assertEqual(status["state"], "finished")
        self.assertEqual(status["exit_code"], 0)
        request = Request(
            self.base_url + "/api/demo/bundle",
            data=b"",
            method="POST",
        )
        with urlopen(request, timeout=2) as response:
            bundle = json.loads(response.read().decode("utf-8"))
        self.assertTrue(bundle["created"])
        self.assertEqual(bundle["name"], "evidence-bundle.zip")
        _, status = self.get_json("/api/demo/status")
        self.assertIn(
            "evidence-bundle.zip",
            [item["name"] for item in status["artifacts"]],
        )

    def test_uploaded_input_starts_run_and_history(self):
        request = Request(
            self.base_url + "/api/upload/run?filename=input.csv",
            data=b"invoice_id,customer_id\nINV-1,CUST-1\n",
            method="POST",
        )
        with urlopen(request, timeout=2) as response:
            payload = json.loads(response.read().decode("utf-8"))

        self.assertEqual(response.status, 202)
        self.assertTrue(payload["started"])
        for _ in range(20):
            _, status = self.get_json("/api/demo/status")
            if status["state"] == "finished":
                break
            time.sleep(0.01)
        self.assertEqual(status["kind"], "upload")
        self.assertEqual(status["source_name"], "input.csv")
        self.assertTrue(
            (Path(status["output_dir"]) / "input.csv").is_file()
        )
        self.assertTrue(
            (Path(status["output_dir"]) / "run.json").is_file()
        )
        self.assertGreaterEqual(len(status["history"]), 1)

    def test_active_demo_can_be_cancelled(self):
        self.server.state.command_factory = lambda output_dir: [
            sys.executable,
            "-c",
            "import time; time.sleep(30)",
        ]
        self.addCleanup(self.server.state.cancel_active_run)
        request = Request(
            self.base_url + "/api/demo/run",
            data=b"",
            method="POST",
        )
        with urlopen(request, timeout=2) as response:
            payload = json.loads(response.read().decode("utf-8"))
        self.assertTrue(payload["started"])
        _, status = self.get_json("/api/demo/status")
        self.assertEqual(status["state"], "running")
        request = Request(
            self.base_url + "/api/demo/bundle",
            data=b"",
            method="POST",
        )
        with self.assertRaises(HTTPError) as context:
            urlopen(request, timeout=2)
        error = context.exception
        self.assertEqual(error.code, 409)
        error.close()

        request = Request(
            self.base_url + "/api/demo/cancel",
            data=b"",
            method="POST",
        )
        with urlopen(request, timeout=8) as response:
            cancelled = json.loads(response.read().decode("utf-8"))

        self.assertEqual(response.status, 200)
        self.assertTrue(cancelled["cancelled"])
        self.assertEqual(cancelled["state"], "cancelled")
        self.assertNotEqual(cancelled["exit_code"], 0)
        _, status = self.get_json("/api/demo/status")
        self.assertEqual(status["state"], "cancelled")
        metadata = json.loads(
            (Path(status["output_dir"]) / "run.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertTrue(metadata["cancel_requested"])
        self.assertEqual(metadata["state"], "cancelled")

    def test_cancel_without_active_run_is_rejected(self):
        request = Request(
            self.base_url + "/api/demo/cancel",
            data=b"",
            method="POST",
        )
        with self.assertRaises(HTTPError) as context:
            urlopen(request, timeout=2)
        error = context.exception
        self.assertEqual(error.code, 409)
        error.close()

    def test_upload_rejects_unsupported_file_type(self):
        request = Request(
            self.base_url + "/api/upload/run?filename=malware.exe",
            data=b"not-an-invoice",
            method="POST",
        )
        with self.assertRaises(HTTPError) as context:
            urlopen(request, timeout=2)
        error = context.exception
        self.assertEqual(error.code, 400)
        error.close()

    def test_review_api_persists_operator_decision(self):
        run_dir = self.write_reconciliation_run()
        status, state = self.get_json(
            "/api/review/state",
            headers=self.auth_headers,
        )

        self.assertEqual(status, 200)
        self.assertEqual(state["run"], "console-review-001")
        self.assertEqual(state["review_summary"]["pending"], 1)

        request = Request(
            self.base_url + "/api/review",
            data=json.dumps(
                {
                    "run": state["run"],
                    "invoice_id": "INV-1",
                    "status": "confirmed",
                    "note": "已核对 ERP 页面",
                }
            ).encode("utf-8"),
            headers={
                **self.auth_headers,
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urlopen(request, timeout=2) as response:
            reviewed = json.loads(response.read().decode("utf-8"))

        self.assertEqual(response.status, 200)
        self.assertEqual(reviewed["review_summary"]["confirmed"], 1)
        self.assertTrue((run_dir / "review.json").is_file())
        report = json.loads(
            (run_dir / "reconciliation.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(
            report["reconciliation"]["results"][0]["review"]["status"],
            "confirmed",
        )
        self.assertEqual(
            report["reconciliation"]["results"][0]["review"]["reviewer"],
            "operator-a",
        )
        audit_lines = (
            run_dir / "review-audit.jsonl"
        ).read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(audit_lines), 1)

    def test_review_api_requires_authentication(self):
        run_dir = self.write_reconciliation_run()
        request = Request(
            self.base_url + "/api/review",
            data=json.dumps(
                {
                    "run": run_dir.name,
                    "invoice_id": "INV-1",
                    "status": "confirmed",
                }
            ).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        with self.assertRaises(HTTPError) as context:
            urlopen(request, timeout=2)
        error = context.exception
        self.assertEqual(error.code, 401)
        error.close()

    def test_batch_review_and_close_api(self):
        run_dir = self.write_reconciliation_run()

        status, reviewed = self.post_json(
            "/api/review/batch",
            {
                "run": run_dir.name,
                "invoice_ids": ["INV-1"],
                "status": "false_positive",
                "note": "批量核对完成",
            },
        )
        self.assertEqual(status, 200)
        self.assertEqual(
            reviewed["review_summary"]["false_positive"],
            1,
        )
        self.assertTrue(reviewed["can_close"])

        status, closed = self.post_json(
            "/api/review/close",
            {
                "run": run_dir.name,
                "note": "本轮对账完成",
            },
        )
        self.assertEqual(status, 200)
        self.assertEqual(closed["closure"]["status"], "closed")
        self.assertTrue(
            (run_dir / "review-close.json").is_file()
        )
        self.assertEqual(
            len(
                (run_dir / "review-audit.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
            ),
            1,
        )


if __name__ == "__main__":
    unittest.main()
