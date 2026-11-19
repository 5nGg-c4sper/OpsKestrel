"""Tests for the task runner command-line interface."""

import tempfile
import unittest
from pathlib import Path

from soc_agent.actions.executor import ActionExecutor
from soc_agent.cli import (
    build_parser,
    exit_code_for_status,
    run_task,
)
from soc_agent.reporting.report import ReportWriter
from soc_agent.task_models import TaskStatus


class FakeEnvironment:
    def __init__(self):
        self.calls = []

    def open_app(self, app):
        self.calls.append(("open_app", app))

    def write(self, content):
        self.calls.append(("write", content))

    def press(self, keys):
        self.calls.append(("press", keys))

    def click(self, x, y):
        self.calls.append(("click", x, y))

    def wait(self, seconds):
        self.calls.append(("wait", seconds))

    def screenshot(self, output_path):
        path = Path(output_path)
        path.write_bytes(b"fake-image")
        self.calls.append(("screenshot", str(path)))
        return path


class FakeVisionProvider:
    def __init__(self, response=True):
        self.response = response
        self.calls = []

    def verify(self, image_path, statement):
        self.calls.append((image_path, statement))
        return self.response


class CLITests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)

    def test_parser_supports_run_options(self):
        args = build_parser().parse_args(
            [
                "run",
                "tasks/calculator_17x23.json",
                "--scale",
                "0.4",
                "--settle-delay",
                "0.2",
                "--reports-dir",
                "custom-reports",
            ]
        )

        self.assertEqual(args.command, "run")
        self.assertEqual(args.task, "tasks/calculator_17x23.json")
        self.assertEqual(args.scale, 0.4)
        self.assertEqual(args.settle_delay, 0.2)
        self.assertEqual(args.reports_dir, "custom-reports")

    def test_exit_code_for_status(self):
        self.assertEqual(exit_code_for_status(TaskStatus.PASSED), 0)
        self.assertEqual(exit_code_for_status(TaskStatus.FAILED), 1)
        self.assertEqual(exit_code_for_status(TaskStatus.TIMED_OUT), 1)
        self.assertEqual(exit_code_for_status(TaskStatus.CANCELLED), 1)

    def test_run_task_wires_environment_vision_and_report(self):
        environment = FakeEnvironment()
        executor = ActionExecutor(environment, settle_delay=0)
        provider = FakeVisionProvider(response=True)
        reporter = ReportWriter(self.root / "reports")
        screenshot_path = self.root / "verification.png"

        result = run_task(
            "tasks/calculator_17x23.json",
            environment,
            executor,
            provider,
            reporter,
            screenshot_path=screenshot_path,
        )

        self.assertEqual(result.status, TaskStatus.PASSED)
        self.assertTrue(Path(result.report_path).is_file())
        self.assertEqual(
            provider.calls,
            [
                (
                    str(screenshot_path),
                    "计算器是否显示结果 391？只返回 true 或 false。",
                )
            ],
        )
        self.assertIn(("screenshot", str(screenshot_path)), environment.calls)

    def test_report_is_written_when_verification_fails(self):
        environment = FakeEnvironment()
        executor = ActionExecutor(environment, settle_delay=0)
        provider = FakeVisionProvider(response=False)
        reporter = ReportWriter(self.root / "reports")

        result = run_task(
            "tasks/calculator_17x23.json",
            environment,
            executor,
            provider,
            reporter,
            screenshot_path=self.root / "verification.png",
        )

        self.assertEqual(result.status, TaskStatus.FAILED)
        self.assertTrue(Path(result.report_path).is_file())


if __name__ == "__main__":
    unittest.main()
