"""Tests for JSON task report writing."""

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from soc_agent.reporting.report import ReportWriter
from soc_agent.task_models import (
    ActionType,
    StepResult,
    StepStatus,
    TaskResult,
    TaskStatus,
)


class ReportWriterTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.output_dir = Path(self.temporary_directory.name) / "reports"

    def make_result(self, task_name="calculator_17x23"):
        timestamp = datetime(2026, 11, 19, 10, 30, 0, tzinfo=timezone.utc)
        return TaskResult(
            task_name=task_name,
            status=TaskStatus.PASSED,
            started_at=timestamp,
            finished_at=timestamp,
            duration_seconds=1.5,
            steps=[
                StepResult(
                    index=0,
                    type=ActionType.OPEN_APP,
                    status=StepStatus.PASSED,
                    started_at=timestamp,
                    finished_at=timestamp,
                    duration_seconds=0.5,
                )
            ],
        )

    def test_writes_json_report(self):
        result = self.make_result()
        writer = ReportWriter(self.output_dir)

        path = writer.write(result)

        self.assertTrue(path.exists())
        self.assertEqual(result.report_path, str(path))

        payload = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(payload["task_name"], "calculator_17x23")
        self.assertEqual(payload["status"], "passed")
        self.assertEqual(payload["duration_seconds"], 1.5)
        self.assertEqual(len(payload["steps"]), 1)
        self.assertEqual(payload["report_path"], str(path))

    def test_creates_output_directory(self):
        result = self.make_result()
        writer = ReportWriter(self.output_dir)

        self.assertFalse(self.output_dir.exists())
        path = writer.write(result)

        self.assertTrue(self.output_dir.is_dir())
        self.assertTrue(path.exists())

    def test_sanitizes_task_name(self):
        result = self.make_result("calculator / test")
        writer = ReportWriter(self.output_dir)

        path = writer.write(result)

        self.assertEqual(
            path.name,
            "20261119-103000-calculator-test.json",
        )

    def test_avoids_overwriting_existing_report(self):
        result = self.make_result()
        writer = ReportWriter(self.output_dir)

        first_path = writer.write(result)
        second_path = writer.write(result)

        self.assertNotEqual(first_path, second_path)
        self.assertEqual(
            second_path.name,
            "20261119-103000-calculator_17x23-1.json",
        )


if __name__ == "__main__":
    unittest.main()
