"""Tests for runtime deployment diagnostics."""

import unittest
from datetime import datetime, timezone
from subprocess import CompletedProcess

from soc_agent.diagnostics import (
    DiagnosticCheck,
    DiagnosticReport,
    DiagnosticStatus,
    DiagnosticsRunner,
)
from soc_agent.queue_models import QueueWorkerRecord, WorkerState


class FakeQueueStore:
    def __init__(self, workers=None):
        self.workers = list(workers or [])
        self.worker_window = None

    def list_jobs(self, state=None):
        return []

    def list_workers(self, online_within_seconds=None):
        self.worker_window = online_within_seconds
        return self.workers


class DiagnosticsRunnerTests(unittest.TestCase):
    def setUp(self):
        now = datetime(2026, 11, 26, tzinfo=timezone.utc)
        self.worker = QueueWorkerRecord(
            worker_id="office-mac-1",
            hostname="macbook",
            pid=123,
            state=WorkerState.IDLE,
            labels=["office-mac"],
            started_at=now,
            last_heartbeat=now,
        )
        self.env = {
            "OPENAI_API_KEY": "secret",
            "OPENAI_BASE_URL": "https://example.invalid/v1",
            "MODEL": "Qwen/Qwen3-VL-8B-Instruct",
        }

    def make_runner(self, workers=None, permissions=(True, True)):
        self.store = FakeQueueStore(
            [self.worker] if workers is None else workers
        )
        self.report_paths = []
        return DiagnosticsRunner(
            env=self.env,
            platform_name="Darwin",
            macos_permission_probe=lambda: permissions,
            command_runner=lambda *args, **kwargs: CompletedProcess(
                args[0],
                0,
                stdout="gui session",
                stderr="",
            ),
            queue_store_factory=lambda location: self.store,
            report_directory_probe=self.report_paths.append,
            uid=501,
        )

    def check(self, report, name):
        return next(
            check for check in report.checks if check.name == name
        )

    def test_healthy_runtime_passes_all_checks(self):
        report = self.make_runner().run(
            queue_db="reports/queue.db",
            reports_dir="reports",
            worker_id="office-mac-1",
            online_within_seconds=120,
        )

        self.assertTrue(report.healthy)
        self.assertTrue(
            all(
                check.status == DiagnosticStatus.PASS
                for check in report.checks
            )
        )
        self.assertEqual(self.report_paths, ["reports"])
        self.assertEqual(self.store.worker_window, 120)
        self.assertIn("office-mac-1", self.check(report, "worker").message)

    def test_missing_configuration_reports_failure_without_secrets(self):
        runner = DiagnosticsRunner(
            env={},
            platform_name="Darwin",
            macos_permission_probe=lambda: (True, True),
            command_runner=lambda *args, **kwargs: CompletedProcess(
                args[0],
                0,
                stdout="",
                stderr="",
            ),
            queue_store_factory=lambda location: FakeQueueStore(),
            report_directory_probe=lambda path: None,
            uid=501,
        )

        report = runner.run()
        config_check = self.check(report, "configuration")

        self.assertFalse(report.healthy)
        self.assertEqual(config_check.status, DiagnosticStatus.FAIL)
        self.assertNotIn("secret", config_check.message)

    def test_permission_failures_are_explicit(self):
        report = self.make_runner(
            permissions=(False, False)
        ).run()

        self.assertEqual(
            self.check(report, "accessibility").status,
            DiagnosticStatus.FAIL,
        )
        self.assertEqual(
            self.check(report, "screen_recording").status,
            DiagnosticStatus.FAIL,
        )

    def test_requested_missing_worker_is_a_failure(self):
        report = self.make_runner(workers=[]).run(
            worker_id="missing-worker"
        )

        worker_check = self.check(report, "worker")
        self.assertEqual(worker_check.status, DiagnosticStatus.FAIL)
        self.assertIn("missing-worker", worker_check.message)

    def test_no_workers_is_a_warning_but_runtime_is_healthy(self):
        report = self.make_runner(workers=[]).run()

        self.assertTrue(report.healthy)
        self.assertEqual(
            self.check(report, "worker").status,
            DiagnosticStatus.WARN,
        )

    def test_report_serializes_to_json_compatible_dict(self):
        report = DiagnosticReport(
            [
                DiagnosticCheck(
                    "python",
                    DiagnosticStatus.PASS,
                    "Python 3.9",
                )
            ]
        )

        self.assertEqual(
            report.to_dict(),
            {
                "status": "pass",
                "checks": [
                    {
                        "name": "python",
                        "status": "pass",
                        "message": "Python 3.9",
                    }
                ],
            },
        )
