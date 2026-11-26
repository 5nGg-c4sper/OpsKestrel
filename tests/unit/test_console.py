"""Tests for the local SOC Agent operations console."""

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

from soc_agent.console import create_console_server
from soc_agent.queue_models import QueueWorkerRecord, WorkerState


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

    def get_json(self, path):
        with urlopen(self.base_url + path, timeout=2) as response:
            return response.status, json.loads(
                response.read().decode("utf-8")
            )

    def test_console_html_and_overview(self):
        with urlopen(self.base_url + "/", timeout=2) as response:
            html = response.read().decode("utf-8")
        status, payload = self.get_json("/api/overview")

        self.assertEqual(response.status, 200)
        self.assertIn("SOC Agent Console", html)
        self.assertIn('join("\\n")', html)
        self.assertIn('id="cancel-run"', html)
        self.assertEqual(status, 200)
        self.assertEqual(payload["reports"][0]["status"], "passed")
        self.assertEqual(len(payload["workers"]), 1)

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
        self.assertEqual(context.exception.code, 404)

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
        self.assertEqual(context.exception.code, 409)

    def test_upload_rejects_unsupported_file_type(self):
        request = Request(
            self.base_url + "/api/upload/run?filename=malware.exe",
            data=b"not-an-invoice",
            method="POST",
        )
        with self.assertRaises(HTTPError) as context:
            urlopen(request, timeout=2)
        self.assertEqual(context.exception.code, 400)


if __name__ == "__main__":
    unittest.main()
