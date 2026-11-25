"""Tests for JSON task report writing."""

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from soc_agent.reporting.dataset_report import DatasetReportWriter
from soc_agent.reporting.report import ReportWriter
from soc_agent.reporting.suite_report import SuiteReportWriter
from soc_agent.reporting.workflow_report import WorkflowReportWriter
from soc_agent.suite import SuiteResult
from soc_agent.task_models import (
    ActionType,
    StepPhase,
    StepResult,
    StepStatus,
    TaskCaseResult,
    TaskDatasetResult,
    TaskResult,
    TaskStatus,
    WorkflowResult,
    WorkflowTaskResult,
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

    def test_copies_condition_screenshot_to_artifact_directory(self):
        source = self.root / "condition.png"
        source.write_bytes(b"condition-image")

        result = self.make_result()
        result.steps[0].condition_screenshot = str(source)
        writer = ReportWriter(self.output_dir)

        path = writer.write(result)
        payload = json.loads(path.read_text(encoding="utf-8"))
        relative_screenshot = payload["steps"][0]["condition_screenshot"]
        artifact_path = self.output_dir / relative_screenshot

        self.assertEqual(artifact_path.read_bytes(), b"condition-image")
        self.assertEqual(
            artifact_path.name,
            "condition-step-000.png",
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

    def test_all_non_passed_statuses_write_failure_logs(self):
        writer = ReportWriter(self.output_dir)

        for status in (
            TaskStatus.FAILED,
            TaskStatus.TIMED_OUT,
            TaskStatus.CANCELLED,
        ):
            with self.subTest(status=status):
                result = self.make_result(
                    status=status,
                    error=f"{status.value} diagnostic",
                )
                path = writer.write(result)
                log_path = (
                    self.output_dir
                    / "artifacts"
                    / path.stem
                    / "failure.log"
                )

                self.assertTrue(log_path.is_file())
                content = log_path.read_text(encoding="utf-8")
                self.assertIn(
                    f"Status: {status.value}",
                    content,
                )
                self.assertIn(
                    f"Error: {status.value} diagnostic",
                    content,
                )

    def test_failure_log_includes_condition_diagnostics(self):
        result = self.make_result(
            status=TaskStatus.FAILED,
            error="condition provider failed",
        )
        step = result.steps[0]
        step.condition_prompt = "结果是否正确？"
        step.condition_expected = True
        step.condition_actual = False
        step.condition_duration_seconds = 1.25
        step.condition_screenshot = "artifacts/condition-step-000.png"
        writer = ReportWriter(self.output_dir)

        path = writer.write(result)
        log_path = (
            self.output_dir
            / "artifacts"
            / path.stem
            / "failure.log"
        )
        content = log_path.read_text(encoding="utf-8")

        self.assertIn("prompt='结果是否正确？'", content)
        self.assertIn("expected=True", content)
        self.assertIn("actual=False", content)
        self.assertIn("duration=1.25s", content)
        self.assertIn(
            "condition screenshot: artifacts/condition-step-000.png",
            content,
        )


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

    def test_preserves_retry_and_stop_metadata(self):
        result = self.make_dataset_result()
        result.cases[0].attempts = 2
        result.stopped_early = True
        writer = DatasetReportWriter(self.output_dir)

        path = writer.write(result)
        payload = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(payload["cases"][0]["attempts"], 2)
        self.assertTrue(payload["stopped_early"])


class SuiteReportWriterTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        self.output_dir = self.root / "reports"
        self.timestamp = datetime(
            2026,
            11,
            24,
            8,
            30,
            0,
            tzinfo=timezone.utc,
        )

    def make_suite_result(self, suite_name="calculator_suite"):
        passed_task = TaskResult(
            task_name="calculator_parameterized",
            status=TaskStatus.PASSED,
            started_at=self.timestamp,
            finished_at=self.timestamp,
            duration_seconds=3.5,
            report_path="reports/default_17x23.json",
        )
        failed_task = TaskResult(
            task_name="calculator_failure",
            status=TaskStatus.FAILED,
            started_at=self.timestamp,
            finished_at=self.timestamp,
            duration_seconds=1.5,
            error="verification failed",
            report_path="reports/failure.json",
            failure_log=(
                "artifacts/20261124-083000-calculator_failure/"
                "failure.log"
            ),
        )
        return SuiteResult(
            results=[passed_task, failed_task],
            suite_name=suite_name,
            started_at=self.timestamp,
            finished_at=self.timestamp,
            duration_seconds=5.0,
        )

    def test_writes_suite_summary_report(self):
        result = self.make_suite_result()
        writer = SuiteReportWriter(self.output_dir)

        path = writer.write(result)

        self.assertTrue(path.is_file())
        self.assertEqual(result.report_path, str(path))
        payload = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(payload["suite_name"], "calculator_suite")
        self.assertEqual(payload["status"], "failed")
        self.assertEqual(payload["total"], 2)
        self.assertEqual(payload["passed"], 1)
        self.assertEqual(payload["failed"], 1)
        self.assertEqual(payload["duration_seconds"], 5.0)
        self.assertEqual(payload["report_path"], str(path))

    def test_preserves_nested_task_report_and_failure_paths(self):
        result = self.make_suite_result()
        writer = SuiteReportWriter(self.output_dir)

        path = writer.write(result)
        payload = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(
            payload["results"][0]["report_path"],
            "reports/default_17x23.json",
        )
        self.assertEqual(
            payload["results"][1]["report_path"],
            "reports/failure.json",
        )
        self.assertEqual(
            payload["results"][1]["failure_log"],
            result.results[1].failure_log,
        )

    def test_sanitizes_suite_name(self):
        result = self.make_suite_result("calculator / regression")
        writer = SuiteReportWriter(self.output_dir)

        path = writer.write(result)

        self.assertEqual(
            path.name,
            "20261124-083000-calculator-regression.json",
        )

    def test_avoids_overwriting_existing_report(self):
        result = self.make_suite_result()
        writer = SuiteReportWriter(self.output_dir)

        first_path = writer.write(result)
        second_path = writer.write(result)

        self.assertNotEqual(first_path, second_path)
        self.assertEqual(
            second_path.name,
            "20261124-083000-calculator_suite-1.json",
        )


class WorkflowReportWriterTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        self.output_dir = self.root / "reports"
        self.timestamp = datetime(
            2026,
            11,
            25,
            12,
            0,
            0,
            tzinfo=timezone.utc,
        )

    def make_task_result(self, name, status, error=None):
        return TaskResult(
            task_name=name,
            status=status,
            started_at=self.timestamp,
            finished_at=self.timestamp,
            duration_seconds=1.5,
            error=error,
            report_path=f"reports/{name}.json",
            failure_log=(
                f"artifacts/{name}/failure.log"
                if status != TaskStatus.PASSED
                else None
            ),
        )

    def make_workflow_task_result(
        self,
        name,
        status,
        phase=StepPhase.MAIN,
        error=None,
    ):
        task_result = self.make_task_result(name, status, error)
        return WorkflowTaskResult(
            task_name=name,
            task_path=f"/tmp/tasks/{name}.json",
            phase=phase,
            status=status,
            parameters={"customer_name": "张三"},
            started_at=self.timestamp,
            finished_at=self.timestamp,
            duration_seconds=1.5,
            error=error,
            task_result=task_result,
        )

    def make_workflow_result(self, workflow_name="customer_update"):
        return WorkflowResult(
            workflow_name=workflow_name,
            status=TaskStatus.FAILED,
            started_at=self.timestamp,
            finished_at=self.timestamp,
            duration_seconds=4.0,
            task_results=[
                self.make_workflow_task_result(
                    "login",
                    TaskStatus.PASSED,
                ),
                self.make_workflow_task_result(
                    "update_customer",
                    TaskStatus.FAILED,
                    error="update failed",
                ),
            ],
            cleanup_result=self.make_workflow_task_result(
                "logout",
                TaskStatus.PASSED,
                StepPhase.CLEANUP,
            ),
            stopped_early=True,
            error="update failed",
        )

    def test_writes_workflow_summary_report(self):
        result = self.make_workflow_result()
        writer = WorkflowReportWriter(self.output_dir)

        path = writer.write(result)

        self.assertTrue(path.is_file())
        self.assertEqual(result.report_path, str(path))
        payload = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(payload["workflow_name"], "customer_update")
        self.assertEqual(payload["status"], "failed")
        self.assertEqual(payload["duration_seconds"], 4.0)
        self.assertEqual(payload["report_path"], str(path))
        self.assertTrue(payload["stopped_early"])

    def test_preserves_nested_reports_and_cleanup(self):
        result = self.make_workflow_result()
        writer = WorkflowReportWriter(self.output_dir)

        path = writer.write(result)
        payload = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(
            payload["task_results"][0]["task_result"]["report_path"],
            "reports/login.json",
        )
        self.assertEqual(
            payload["task_results"][1]["task_result"]["failure_log"],
            "artifacts/update_customer/failure.log",
        )
        self.assertEqual(
            payload["cleanup_result"]["phase"],
            "cleanup",
        )
        self.assertEqual(
            payload["cleanup_result"]["task_result"]["report_path"],
            "reports/logout.json",
        )

    def test_sanitizes_workflow_name(self):
        result = self.make_workflow_result("customer / update")
        writer = WorkflowReportWriter(self.output_dir)

        path = writer.write(result)

        self.assertEqual(
            path.name,
            "20261125-120000-customer-update.json",
        )

    def test_avoids_overwriting_existing_workflow_report(self):
        result = self.make_workflow_result()
        writer = WorkflowReportWriter(self.output_dir)

        first_path = writer.write(result)
        second_path = writer.write(result)

        self.assertNotEqual(first_path, second_path)
        self.assertEqual(
            second_path.name,
            "20261125-120000-customer_update-1.json",
        )


if __name__ == "__main__":
    unittest.main()
