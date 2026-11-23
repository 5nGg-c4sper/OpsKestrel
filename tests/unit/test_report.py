"""Tests for JSON task report writing."""

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from soc_agent.reporting.dataset_report import DatasetReportWriter
from soc_agent.reporting.report import ReportWriter
from soc_agent.task_models import (
    ActionType,
    StepResult,
    StepStatus,
    TaskCaseResult,
    TaskDatasetResult,
    TaskResult,
    TaskStatus,
)


class ReportWriterTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        self.output_dir = self.root / "reports"

    def make_result(
        self,
        task_name="calculator_17x23",
        status=TaskStatus.PASSED,
        error=None,
    ):
        timestamp = datetime(2026, 11, 19, 10, 30, 0, tzinfo=timezone.utc)
        return TaskResult(
            task_name=task_name,
            status=status,
            started_at=timestamp,
            finished_at=timestamp,
            duration_seconds=1.5,
            error=error,
            steps=[
                StepResult(
                    index=0,
                    type=ActionType.OPEN_APP,
                    status=(
                        StepStatus.PASSED
                        if status == TaskStatus.PASSED
                        else StepStatus.FAILED
                    ),
                    started_at=timestamp,
                    finished_at=timestamp,
                    duration_seconds=0.5,
                    error=error,
                )
            ],
        )

    def test_copies_screenshot_to_artifact_directory(self):
        source = self.root / "verification.png"
        source.write_bytes(b"fake-image")

        result = self.make_result()
        result.steps[0].screenshot = str(source)
        writer = ReportWriter(self.output_dir)

        path = writer.write(result)
        payload = json.loads(path.read_text(encoding="utf-8"))
        relative_screenshot = payload["steps"][0]["screenshot"]
        artifact_path = self.output_dir / relative_screenshot

        self.assertTrue(artifact_path.is_file())
        self.assertEqual(artifact_path.read_bytes(), b"fake-image")
        self.assertTrue(
            relative_screenshot.startswith("artifacts/")
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
        self.assertIsNone(payload["failure_log"])

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

    def test_writes_failure_log_to_artifact_directory(self):
        result = self.make_result(
            status=TaskStatus.FAILED,
            error="action failed",
        )
        timestamp = result.started_at
        result.steps.append(
            StepResult(
                index=1,
                type=ActionType.WRITE,
                status=StepStatus.SKIPPED,
                started_at=timestamp,
                finished_at=timestamp,
                error="task stopped after failure",
            )
        )
        writer = ReportWriter(self.output_dir)

        path = writer.write(result)
        log_path = (
            self.output_dir
            / "artifacts"
            / path.stem
            / "failure.log"
        )

        self.assertTrue(log_path.is_file())
        self.assertEqual(
            result.failure_log,
            str(log_path.relative_to(self.output_dir)),
        )
        content = log_path.read_text(encoding="utf-8")
        self.assertIn("Task: calculator_17x23", content)
        self.assertIn("Status: failed", content)
        self.assertIn("Error: action failed", content)
        self.assertIn("[0] open_app failed", content)
        self.assertIn("[1] write skipped", content)
        self.assertIn("task stopped after failure", content)
        payload = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(payload["failure_log"], result.failure_log)

    def test_successful_task_does_not_write_failure_log(self):
        result = self.make_result()
        writer = ReportWriter(self.output_dir)

        path = writer.write(result)
        log_path = (
            self.output_dir
            / "artifacts"
            / path.stem
            / "failure.log"
        )

        self.assertFalse(log_path.exists())
        self.assertIsNone(result.failure_log)


class DatasetReportWriterTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        self.output_dir = self.root / "reports"

    def make_dataset_result(self, dataset_name="calculator_regression"):
        timestamp = datetime(2026, 11, 20, 12, 0, 0, tzinfo=timezone.utc)
        task_result = TaskResult(
            task_name="calculator_parameterized",
            status=TaskStatus.PASSED,
            started_at=timestamp,
            finished_at=timestamp,
            duration_seconds=3.5,
            report_path="reports/default_17x23.json",
        )
        case_result = TaskCaseResult(
            name="default_17x23",
            parameters={"right": "23"},
            status=TaskStatus.PASSED,
            duration_seconds=3.5,
            task_result=task_result,
        )
        return TaskDatasetResult(
            dataset_name=dataset_name,
            status=TaskStatus.PASSED,
            started_at=timestamp,
            finished_at=timestamp,
            duration_seconds=3.5,
            cases=[case_result],
        )

    def test_writes_dataset_summary_report(self):
        result = self.make_dataset_result()
        writer = DatasetReportWriter(self.output_dir)

        path = writer.write(result)

        self.assertTrue(path.is_file())
        self.assertEqual(result.report_path, str(path))
        payload = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(payload["dataset_name"], "calculator_regression")
        self.assertEqual(payload["status"], "passed")
        self.assertEqual(payload["duration_seconds"], 3.5)

    def test_preserves_nested_case_fields(self):
        result = self.make_dataset_result()
        writer = DatasetReportWriter(self.output_dir)

        path = writer.write(result)
        payload = json.loads(path.read_text(encoding="utf-8"))
        case_payload = payload["cases"][0]

        self.assertEqual(case_payload["name"], "default_17x23")
        self.assertEqual(case_payload["parameters"], {"right": "23"})
        self.assertEqual(case_payload["status"], "passed")
        self.assertEqual(
            case_payload["task_result"]["task_name"],
            "calculator_parameterized",
        )
        self.assertEqual(
            case_payload["task_result"]["report_path"],
            "reports/default_17x23.json",
        )

    def test_sanitizes_dataset_name(self):
        result = self.make_dataset_result("calculator / regression")
        writer = DatasetReportWriter(self.output_dir)

        path = writer.write(result)

        self.assertEqual(
            path.name,
            "20261120-120000-calculator-regression.json",
        )

    def test_avoids_overwriting_existing_report(self):
        result = self.make_dataset_result()
        writer = DatasetReportWriter(self.output_dir)

        first_path = writer.write(result)
        second_path = writer.write(result)

        self.assertNotEqual(first_path, second_path)
        self.assertEqual(
            second_path.name,
            "20261120-120000-calculator_regression-1.json",
        )

    def test_preserves_nested_task_failure_log(self):
        result = self.make_dataset_result()
        result.cases[0].task_result.failure_log = (
            "artifacts/20261120-120000-calculator_parameterized/"
            "failure.log"
        )
        writer = DatasetReportWriter(self.output_dir)

        path = writer.write(result)
        payload = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(
            payload["cases"][0]["task_result"]["failure_log"],
            result.cases[0].task_result.failure_log,
        )


if __name__ == "__main__":
    unittest.main()
