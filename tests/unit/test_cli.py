"""Tests for the task runner command-line interface."""

import tempfile
import unittest
from io import StringIO
from pathlib import Path

from soc_agent.actions.executor import ActionExecutor
from soc_agent.cli import (
    build_parser,
    exit_code_for_status,
    non_interactive_confirmation,
    parse_parameter_overrides,
    run_task,
    terminal_confirmation_handler,
)
from soc_agent.reporting.report import ReportWriter
from soc_agent.task_models import TaskStatus, TaskStep


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
        self.assertIsNone(args.param)
        self.assertFalse(args.non_interactive)

    def test_parser_supports_repeated_run_parameters(self):
        args = build_parser().parse_args(
            [
                "run",
                "tasks/calculator_17x23.json",
                "--param",
                "left=3",
                "--param",
                "right=4",
            ]
        )

        self.assertEqual(args.param, ["left=3", "right=4"])

    def test_parser_supports_non_interactive_mode(self):
        args = build_parser().parse_args(
            [
                "run",
                "tasks/calculator_17x23.json",
                "--non-interactive",
            ]
        )

        self.assertTrue(args.non_interactive)

    def test_parser_supports_suite_mode(self):
        args = build_parser().parse_args(
            [
                "suite",
                "tasks",
                "--stop-on-failure",
                "--non-interactive",
            ]
        )

        self.assertEqual(args.command, "suite")
        self.assertEqual(args.suite_path, "tasks")
        self.assertIsNone(args.param)
        self.assertTrue(args.stop_on_failure)
        self.assertTrue(args.non_interactive)

    def test_parser_supports_repeated_suite_parameters(self):
        args = build_parser().parse_args(
            [
                "suite",
                "tasks",
                "--param",
                "left=3",
                "--param",
                "right=4",
            ]
        )

        self.assertEqual(args.param, ["left=3", "right=4"])

    def test_parse_parameter_overrides_returns_empty_for_none(self):
        self.assertEqual(parse_parameter_overrides(None), {})

    def test_parse_parameter_overrides_parses_repeated_values(self):
        overrides = parse_parameter_overrides(
            [
                "left=3",
                "right=4",
                "formula=a=b",
                "empty=",
            ]
        )

        self.assertEqual(
            overrides,
            {
                "left": "3",
                "right": "4",
                "formula": "a=b",
                "empty": "",
            },
        )

    def test_parse_parameter_overrides_rejects_malformed_values(self):
        for raw_value in ("left", "=3", ""):
            with self.subTest(raw_value=raw_value):
                with self.assertRaisesRegex(
                    ValueError,
                    "expected KEY=VALUE",
                ):
                    parse_parameter_overrides([raw_value])

    def test_parse_parameter_overrides_rejects_duplicate_names(self):
        with self.assertRaisesRegex(
            ValueError,
            "duplicate task parameter override: left",
        ):
            parse_parameter_overrides(["left=3", "left=4"])

    def test_exit_code_for_status(self):
        self.assertEqual(exit_code_for_status(TaskStatus.PASSED), 0)
        self.assertEqual(exit_code_for_status(TaskStatus.FAILED), 1)
        self.assertEqual(exit_code_for_status(TaskStatus.TIMED_OUT), 1)
        self.assertEqual(exit_code_for_status(TaskStatus.CANCELLED), 1)

    def test_terminal_confirmation_accepts_yes(self):
        output = StringIO()
        step = TaskStep(type="write", content="sensitive")

        confirmed = terminal_confirmation_handler(
            step,
            input_fn=lambda prompt: "yes",
            output=output,
        )

        self.assertTrue(confirmed)
        self.assertIn("write", output.getvalue())
        self.assertIn("sensitive", output.getvalue())

    def test_terminal_confirmation_rejects_other_answers(self):
        output = StringIO()
        step = TaskStep(type="press", keys=["enter"])

        for answer in ("", "n", "no", "continue"):
            confirmed = terminal_confirmation_handler(
                step,
                input_fn=lambda prompt, value=answer: value,
                output=output,
            )
            self.assertFalse(confirmed)

    def test_terminal_confirmation_handles_end_of_input(self):
        def raise_eof(prompt):
            raise EOFError

        confirmed = terminal_confirmation_handler(
            TaskStep(type="write", content="sensitive"),
            input_fn=raise_eof,
            output=StringIO(),
        )

        self.assertFalse(confirmed)

    def test_non_interactive_confirmation_always_rejects(self):
        step = TaskStep(type="write", content="sensitive")

        self.assertFalse(non_interactive_confirmation(step))

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
        self.assertIsNotNone(result.steps[3].screenshot)
        self.assertTrue(
            (self.root / "reports" / result.steps[3].screenshot).is_file()
        )

    def test_run_task_applies_parameter_overrides(self):
        task_path = self.root / "parameterized.json"
        task_path.write_text(
            """
            {
              "name": "parameterized_task",
              "parameters": {
                "left": {"default": "17"},
                "right": {}
              },
              "steps": [
                {"type": "write", "content": "${left}*${right}"},
                {"type": "done", "summary": "finished"}
              ]
            }
            """,
            encoding="utf-8",
        )
        environment = FakeEnvironment()
        executor = ActionExecutor(environment, settle_delay=0)

        result = run_task(
            task_path,
            environment,
            executor,
            FakeVisionProvider(),
            ReportWriter(self.root / "reports"),
            parameter_overrides={"right": "23"},
        )

        self.assertEqual(result.status, TaskStatus.PASSED)
        self.assertIn(("write", "17*23"), environment.calls)
        self.assertTrue(Path(result.report_path).is_file())

    def test_run_task_accepts_confirmed_step(self):
        task_path = self.root / "confirmation.json"
        task_path.write_text(
            """
            {
              "name": "confirmation_task",
              "steps": [
                {
                  "type": "write",
                  "content": "confirmed",
                  "requires_confirmation": true
                },
                {"type": "done", "summary": "finished"}
              ]
            }
            """,
            encoding="utf-8",
        )
        environment = FakeEnvironment()
        executor = ActionExecutor(environment, settle_delay=0)

        result = run_task(
            task_path,
            environment,
            executor,
            FakeVisionProvider(),
            ReportWriter(self.root / "reports"),
            confirmation_handler=lambda step: True,
        )

        self.assertEqual(result.status, TaskStatus.PASSED)
        self.assertIn(("write", "confirmed"), environment.calls)

    def test_run_task_cancels_rejected_step(self):
        task_path = self.root / "confirmation.json"
        task_path.write_text(
            """
            {
              "name": "confirmation_task",
              "steps": [
                {
                  "type": "write",
                  "content": "rejected",
                  "requires_confirmation": true
                }
              ]
            }
            """,
            encoding="utf-8",
        )
        environment = FakeEnvironment()
        executor = ActionExecutor(environment, settle_delay=0)

        result = run_task(
            task_path,
            environment,
            executor,
            FakeVisionProvider(),
            ReportWriter(self.root / "reports"),
            confirmation_handler=lambda step: False,
        )

        self.assertEqual(result.status, TaskStatus.CANCELLED)
        self.assertEqual(environment.calls, [])

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
        self.assertIsNotNone(result.steps[3].screenshot)


if __name__ == "__main__":
    unittest.main()
