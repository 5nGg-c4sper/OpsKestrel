"""Tests for the task runner command-line interface."""

import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from soc_agent.actions.executor import ActionExecutor
from soc_agent.cli import (
    build_parser,
    exit_code_for_status,
    main,
    non_interactive_confirmation,
    parse_parameter_overrides,
    print_result,
    run_dataset,
    run_task,
    run_suite,
    run_workflow,
    terminal_confirmation_handler,
)
from soc_agent.reporting.report import ReportWriter
from soc_agent.queue_models import QueueState
from soc_agent.queue_store import SQLiteQueueStore
from soc_agent.task_models import (
    ActionType,
    DatasetTargetType,
    ExecutionPermissions,
    StepResult,
    StepStatus,
    TaskResult,
    TaskStatus,
    TaskStep,
    ValueConditionOperator,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class FakeEnvironment:
    def __init__(self):
        self.calls = []

    def open_app(self, app):
        self.calls.append(("open_app", app))

    def activate_app(self, app):
        self.calls.append(("activate_app", app))

    def close_document(self, app, save_changes=False):
        self.calls.append(
            ("close_document", app, save_changes)
        )

    def write(self, content):
        self.calls.append(("write", content))

    def press(self, keys):
        self.calls.append(("press", keys))

    def click(self, x, y):
        self.calls.append(("click", x, y))

    def click_element(self, app, element):
        self.calls.append(("click_element", app, element))

    def read_element(self, app, element, attribute="value"):
        self.calls.append(
            ("read_element", app, element, attribute)
        )
        return "391"

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

    def write_parameterized_suite(self):
        suite_path = self.root / "suite"
        suite_path.mkdir()

        for name, left in (("first", "17"), ("second", "125")):
            (suite_path / f"{name}.json").write_text(
                f"""
                {{
                  "name": "{name}",
                  "parameters": {{
                    "left": {{"default": "{left}"}},
                    "right": {{}}
                  }},
                  "steps": [
                    {{
                      "type": "write",
                      "content": "${{left}}*${{right}}"
                    }},
                    {{"type": "done", "summary": "finished"}}
                  ]
                }}
                """,
                encoding="utf-8",
            )

        return suite_path

    def write_workflow_fixture(self):
        tasks_dir = self.root / "tasks"
        workflows_dir = self.root / "workflows"
        tasks_dir.mkdir()
        workflows_dir.mkdir()

        for name, prefix in (("first", "A"), ("second", "B")):
            (tasks_dir / f"{name}.json").write_text(
                json.dumps(
                    {
                        "name": name,
                        "parameters": {"message": {}},
                        "steps": [
                            {
                                "type": "write",
                                "content": f"{prefix}:${{message}}",
                            },
                            {
                                "type": "done",
                                "summary": f"{name} finished",
                            },
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

        (tasks_dir / "cleanup.json").write_text(
            json.dumps(
                {
                    "name": "cleanup",
                    "steps": [
                        {
                            "type": "press",
                            "keys": ["command", "w"],
                        },
                        {
                            "type": "done",
                            "summary": "cleanup finished",
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )
        workflow_path = workflows_dir / "workflow.json"
        workflow_path.write_text(
            json.dumps(
                {
                    "name": "message_workflow",
                    "parameters": {"message": {}},
                    "task_files": [
                        "../tasks/first.json",
                        "../tasks/second.json",
                    ],
                    "cleanup_task": "../tasks/cleanup.json",
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return workflow_path

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

    def test_parser_supports_workflow_mode(self):
        args = build_parser().parse_args(
            [
                "workflow",
                "workflows/customer.json",
                "--param",
                "customer_name=张三",
                "--non-interactive",
            ]
        )

        self.assertEqual(args.command, "workflow")
        self.assertEqual(
            args.workflow_path,
            "workflows/customer.json",
        )
        self.assertEqual(args.param, ["customer_name=张三"])
        self.assertTrue(args.non_interactive)

    def test_parser_supports_queue_commands(self):
        enqueue_args = build_parser().parse_args(
            [
                "queue",
                "enqueue",
                "task",
                "tasks/example.json",
                "--param",
                "message=hello",
                "--priority",
                "5",
                "--allow-app",
                "计算器",
                "--allow-action",
                "open_app",
                "--allow-action",
                "write",
                "--require-label",
                "office-mac",
                "--parallel-safe",
            ]
        )
        run_args = build_parser().parse_args(
            [
                "queue",
                "run",
                "--drain",
                "--stale-after-seconds",
                "120",
                "--max-attempts",
                "4",
                "--worker-id",
                "worker-test",
                "--label",
                "office-mac",
                "--max-concurrency",
                "3",
                "--non-interactive",
            ]
        )
        workers_args = build_parser().parse_args(
            [
                "queue",
                "workers",
                "--online-within-seconds",
                "60",
            ]
        )
        worker_args = build_parser().parse_args(
            [
                "queue",
                "worker",
                "--worker-id",
                "daemon-worker",
                "--label",
                "office-mac",
                "--poll-interval",
                "0.5",
                "--max-concurrency",
                "2",
            ]
        )

        self.assertEqual(enqueue_args.queue_command, "enqueue")
        self.assertEqual(enqueue_args.target_type, "task")
        self.assertEqual(enqueue_args.param, ["message=hello"])
        self.assertEqual(enqueue_args.priority, 5)
        self.assertEqual(enqueue_args.allow_app, ["计算器"])
        self.assertEqual(
            enqueue_args.allow_action,
            ["open_app", "write"],
        )
        self.assertEqual(enqueue_args.require_label, ["office-mac"])
        self.assertTrue(enqueue_args.parallel_safe)
        self.assertEqual(run_args.queue_command, "run")
        self.assertTrue(run_args.drain)
        self.assertEqual(run_args.stale_after_seconds, 120)
        self.assertEqual(run_args.max_attempts, 4)
        self.assertEqual(run_args.worker_id, "worker-test")
        self.assertEqual(run_args.label, ["office-mac"])
        self.assertEqual(run_args.max_concurrency, 3)
        self.assertTrue(run_args.non_interactive)
        self.assertEqual(workers_args.queue_command, "workers")
        self.assertEqual(workers_args.online_within_seconds, 60)
        self.assertEqual(worker_args.queue_command, "worker")
        self.assertEqual(worker_args.worker_id, "daemon-worker")
        self.assertEqual(worker_args.label, ["office-mac"])
        self.assertEqual(worker_args.poll_interval, 0.5)
        self.assertEqual(worker_args.max_concurrency, 2)

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

    def test_parser_supports_dataset_mode(self):
        args = build_parser().parse_args(
            [
                "dataset",
                "datasets/calculator_cases.json",
                "--scale",
                "0.4",
                "--reports-dir",
                "dataset-reports",
                "--stop-on-failure",
                "--non-interactive",
            ]
        )

        self.assertEqual(args.command, "dataset")
        self.assertEqual(
            args.dataset_path,
            "datasets/calculator_cases.json",
        )
        self.assertEqual(args.scale, 0.4)
        self.assertEqual(args.reports_dir, "dataset-reports")
        self.assertTrue(args.stop_on_failure)
        self.assertTrue(args.non_interactive)
        self.assertFalse(hasattr(args, "param"))

    def test_parser_rejects_dataset_parameter_option(self):
        with (
            redirect_stderr(StringIO()),
            self.assertRaises(SystemExit),
        ):
            build_parser().parse_args(
                [
                    "dataset",
                    "datasets/calculator_cases.json",
                    "--param",
                    "right=23",
                ]
            )

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

    def test_print_result_includes_failure_log(self):
        timestamp = datetime.now(timezone.utc)
        result = TaskResult(
            task_name="failed_task",
            status=TaskStatus.FAILED,
            started_at=timestamp,
            finished_at=timestamp,
            error="action failed",
            report_path="reports/failed_task.json",
            failure_log="artifacts/report/failure.log",
        )
        output = StringIO()

        with redirect_stdout(output):
            print_result(result)

        self.assertIn(
            "Failure log: artifacts/report/failure.log",
            output.getvalue(),
        )

    def test_print_result_includes_condition_diagnostics(self):
        timestamp = datetime.now(timezone.utc)
        result = TaskResult(
            task_name="conditional_task",
            status=TaskStatus.PASSED,
            started_at=timestamp,
            finished_at=timestamp,
            steps=[
                StepResult(
                    index=0,
                    type=ActionType.WAIT,
                    status=StepStatus.SKIPPED,
                    started_at=timestamp,
                    finished_at=timestamp,
                    condition_prompt="结果是否为 999？",
                    condition_expected=True,
                    condition_actual=False,
                    condition_duration_seconds=1.25,
                    condition_screenshot="condition-step-000.png",
                )
            ],
        )
        output = StringIO()

        with redirect_stdout(output):
            print_result(result)

        printed = output.getvalue()
        self.assertIn("Condition [0] skipped", printed)
        self.assertIn("expected=True, actual=False", printed)
        self.assertIn("duration=1.25s", printed)
        self.assertIn("Prompt: 结果是否为 999？", printed)
        self.assertIn(
            "Screenshot: condition-step-000.png",
            printed,
        )

    def test_print_result_includes_value_condition_diagnostics(self):
        timestamp = datetime.now(timezone.utc)
        result = TaskResult(
            task_name="value_condition",
            status=TaskStatus.FAILED,
            started_at=timestamp,
            finished_at=timestamp,
            steps=[
                StepResult(
                    index=0,
                    type=ActionType.WAIT,
                    status=StepStatus.SKIPPED,
                    started_at=timestamp,
                    finished_at=timestamp,
                    condition_variable="display_value",
                    condition_operator=ValueConditionOperator.EQUALS,
                    condition_expected_value="391",
                    condition_actual_value=None,
                    condition_expected=True,
                    condition_actual=False,
                )
            ],
        )
        output = StringIO()

        with redirect_stdout(output):
            print_result(result)

        printed = output.getvalue()
        self.assertIn("Variable: display_value equals", printed)
        self.assertIn("Expected value: 391", printed)
        self.assertIn("Actual value: None", printed)

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

    def test_main_passes_cli_parameters_to_run_task(self):
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
        vision_provider = FakeVisionProvider()
        reporter = ReportWriter(self.root / "reports")

        def dependency_factory(args, config):
            self.assertEqual(args.param, ["right=23"])
            return environment, executor, vision_provider, reporter

        with (
            patch("soc_agent.cli.load_dotenv"),
            patch.dict(
                os.environ,
                {"OPENAI_API_KEY": "test-key"},
                clear=False,
            ),
            redirect_stdout(StringIO()),
        ):
            exit_code = main(
                [
                    "run",
                    str(task_path),
                    "--param",
                    "right=23",
                ],
                dependency_factory=dependency_factory,
            )

        self.assertEqual(exit_code, 0)
        self.assertIn(("write", "17*23"), environment.calls)

    def test_main_rejects_invalid_parameters_before_dependencies(self):
        dependency_calls = []

        def dependency_factory(args, config):
            dependency_calls.append((args, config))
            raise AssertionError("dependency factory must not be called")

        with redirect_stdout(StringIO()):
            exit_code = main(
                [
                    "run",
                    "unused-task.json",
                    "--param",
                    "invalid",
                ],
                dependency_factory=dependency_factory,
            )

        self.assertEqual(exit_code, 1)
        self.assertEqual(dependency_calls, [])

    def test_run_suite_applies_common_parameter_overrides(self):
        suite_path = self.write_parameterized_suite()
        environment = FakeEnvironment()
        executor = ActionExecutor(environment, settle_delay=0)

        with redirect_stdout(StringIO()):
            suite_result = run_suite(
                suite_path,
                environment,
                executor,
                FakeVisionProvider(),
                ReportWriter(self.root / "reports"),
                parameter_overrides={"right": "23"},
            )

        self.assertTrue(suite_result.successful)
        self.assertEqual(suite_result.total, 2)
        self.assertTrue(Path(suite_result.report_path).is_file())
        self.assertIn(("write", "17*23"), environment.calls)
        self.assertIn(("write", "125*23"), environment.calls)

        payload = json.loads(
            Path(suite_result.report_path).read_text(encoding="utf-8")
        )
        self.assertEqual(payload["suite_name"], suite_path.name)
        self.assertEqual(payload["status"], "passed")
        self.assertEqual(len(payload["results"]), 2)
        for task_payload in payload["results"]:
            self.assertTrue(Path(task_payload["report_path"]).is_file())

    def test_run_workflow_writes_task_and_summary_reports(self):
        workflow_path = self.write_workflow_fixture()
        environment = FakeEnvironment()
        executor = ActionExecutor(environment, settle_delay=0)
        reporter = ReportWriter(self.root / "reports")

        with redirect_stdout(StringIO()):
            result = run_workflow(
                workflow_path,
                environment,
                executor,
                FakeVisionProvider(),
                reporter,
                parameter_overrides={"message": "hello"},
            )

        self.assertEqual(result.status, TaskStatus.PASSED)
        self.assertTrue(result.successful)
        self.assertEqual(result.total, 2)
        self.assertEqual(result.passed, 2)
        self.assertIn(("write", "A:hello"), environment.calls)
        self.assertIn(("write", "B:hello"), environment.calls)
        self.assertIn(("press", ["command", "w"]), environment.calls)
        self.assertTrue(Path(result.report_path).is_file())
        self.assertEqual(
            result.cleanup_result.status,
            TaskStatus.PASSED,
        )

        for task in result.task_results:
            self.assertTrue(Path(task.task_result.report_path).is_file())
        self.assertTrue(
            Path(
                result.cleanup_result.task_result.report_path
            ).is_file()
        )

        payload = json.loads(
            Path(result.report_path).read_text(encoding="utf-8")
        )
        self.assertEqual(payload["workflow_name"], "message_workflow")
        self.assertEqual(len(payload["task_results"]), 2)
        self.assertEqual(payload["cleanup_result"]["status"], "passed")

    def test_main_runs_workflow_with_shared_parameters(self):
        workflow_path = self.write_workflow_fixture()
        environment = FakeEnvironment()
        executor = ActionExecutor(environment, settle_delay=0)
        vision_provider = FakeVisionProvider()
        reporter = ReportWriter(self.root / "reports")

        def dependency_factory(args, config):
            self.assertEqual(args.command, "workflow")
            self.assertEqual(args.param, ["message=hello"])
            return environment, executor, vision_provider, reporter

        output = StringIO()
        with (
            patch("soc_agent.cli.load_dotenv"),
            patch.dict(
                os.environ,
                {"OPENAI_API_KEY": "test-key"},
                clear=False,
            ),
            redirect_stdout(output),
        ):
            exit_code = main(
                [
                    "workflow",
                    str(workflow_path),
                    "--param",
                    "message=hello",
                ],
                dependency_factory=dependency_factory,
            )

        self.assertEqual(exit_code, 0)
        self.assertIn("Workflow: message_workflow", output.getvalue())
        self.assertIn("Status: PASSED", output.getvalue())
        self.assertIn("Tasks: 2", output.getvalue())
        self.assertIn("Cleanup: PASSED", output.getvalue())
        self.assertIn("Report:", output.getvalue())
        self.assertIn(("write", "A:hello"), environment.calls)
        self.assertIn(("write", "B:hello"), environment.calls)

    def test_run_workflow_passes_runtime_value_between_tasks(self):
        environment = FakeEnvironment()
        executor = ActionExecutor(environment, settle_delay=0)
        reporter = ReportWriter(self.root / "reports")

        with redirect_stdout(StringIO()):
            result = run_workflow(
                PROJECT_ROOT
                / "workflows"
                / "runtime_variable.json",
                environment,
                executor,
                FakeVisionProvider(),
                reporter,
            )

        self.assertEqual(result.status, TaskStatus.PASSED)
        self.assertIn(
            ("write", "工作流值：391"),
            environment.calls,
        )
        self.assertEqual(
            result.runtime_variables["display_value"].source_task,
            "workflow_read_value",
        )

    def test_main_enqueues_and_lists_job_without_api_key(self):
        task_path = self.root / "queued_task.json"
        task_path.write_text(
            json.dumps(
                {
                    "name": "queued_task",
                    "parameters": {"message": {}},
                    "steps": [
                        {
                            "type": "write",
                            "content": "${message}",
                        },
                        {"type": "done", "summary": "finished"},
                    ],
                }
            ),
            encoding="utf-8",
        )
        queue_db = self.root / "queue.db"
        output = StringIO()

        with (
            patch("soc_agent.cli.load_dotenv") as load_dotenv,
            redirect_stdout(output),
        ):
            enqueue_code = main(
                [
                    "queue",
                    "enqueue",
                    "task",
                    str(task_path),
                    "--param",
                    "message=hello",
                    "--job-id",
                    "job-1",
                    "--queue-db",
                    str(queue_db),
                ]
            )
            list_code = main(
                [
                    "queue",
                    "list",
                    "--queue-db",
                    str(queue_db),
                ]
            )

        self.assertEqual(enqueue_code, 0)
        self.assertEqual(list_code, 0)
        self.assertIn("Enqueued: job-1", output.getvalue())
        self.assertIn("job-1 pending task", output.getvalue())
        load_dotenv.assert_not_called()

    def test_main_lists_registered_workers_without_api_key(self):
        queue_db = self.root / "queue.db"
        SQLiteQueueStore(queue_db).register_worker(
            "worker-visible",
            "test-mac",
            999,
            labels=["office-mac"],
        )
        output = StringIO()

        with (
            patch("soc_agent.cli.load_dotenv") as load_dotenv,
            redirect_stdout(output),
        ):
            exit_code = main(
                [
                    "queue",
                    "workers",
                    "--queue-db",
                    str(queue_db),
                ]
            )

        self.assertEqual(exit_code, 0)
        self.assertIn("worker-visible idle test-mac:999", output.getvalue())
        self.assertIn("Labels: office-mac", output.getvalue())
        load_dotenv.assert_not_called()

    def test_main_runs_queued_task(self):
        task_path = self.root / "queued_task.json"
        task_path.write_text(
            json.dumps(
                {
                    "name": "queued_task",
                    "parameters": {"message": {}},
                    "steps": [
                        {
                            "type": "write",
                            "content": "queued:${message}",
                        },
                        {"type": "done", "summary": "finished"},
                    ],
                }
            ),
            encoding="utf-8",
        )
        queue_db = self.root / "queue.db"
        SQLiteQueueStore(queue_db).enqueue(
            DatasetTargetType.TASK,
            task_path,
            parameters={"message": "hello"},
            job_id="queued-task",
        )
        environment = FakeEnvironment()
        executor = ActionExecutor(environment, settle_delay=0)
        vision_provider = FakeVisionProvider()
        reporter = ReportWriter(self.root / "reports")

        def dependency_factory(args, config):
            return environment, executor, vision_provider, reporter

        output = StringIO()
        with (
            patch("soc_agent.cli.load_dotenv"),
            patch.dict(
                os.environ,
                {"OPENAI_API_KEY": "test-key"},
                clear=False,
            ),
            redirect_stdout(output),
        ):
            exit_code = main(
                [
                    "queue",
                    "run",
                    "--queue-db",
                    str(queue_db),
                ],
                dependency_factory=dependency_factory,
            )

        self.assertEqual(exit_code, 0)
        self.assertIn(("write", "queued:hello"), environment.calls)
        self.assertIn("Queue job: queued-task", output.getvalue())
        self.assertEqual(
            SQLiteQueueStore(queue_db).get("queued-task").state,
            QueueState.PASSED,
        )

    def test_main_runs_queued_workflow_until_drained(self):
        workflow_path = self.write_workflow_fixture()
        queue_db = self.root / "queue.db"
        store = SQLiteQueueStore(queue_db)
        store.enqueue(
            DatasetTargetType.WORKFLOW,
            workflow_path,
            parameters={"message": "drained"},
            job_id="workflow-job",
        )
        environment = FakeEnvironment()
        executor = ActionExecutor(environment, settle_delay=0)
        vision_provider = FakeVisionProvider()
        reporter = ReportWriter(self.root / "reports")

        def dependency_factory(args, config):
            self.assertTrue(args.drain)
            return environment, executor, vision_provider, reporter

        output = StringIO()
        with (
            patch("soc_agent.cli.load_dotenv"),
            patch.dict(
                os.environ,
                {"OPENAI_API_KEY": "test-key"},
                clear=False,
            ),
            redirect_stdout(output),
        ):
            exit_code = main(
                [
                    "queue",
                    "run",
                    "--drain",
                    "--queue-db",
                    str(queue_db),
                ],
                dependency_factory=dependency_factory,
            )

        self.assertEqual(exit_code, 0)
        self.assertIn(("write", "A:drained"), environment.calls)
        self.assertIn(("write", "B:drained"), environment.calls)
        self.assertEqual(
            store.get("workflow-job").state,
            QueueState.PASSED,
        )

    def test_queued_job_permissions_block_unapproved_app(self):
        task_path = self.root / "restricted_task.json"
        task_path.write_text(
            json.dumps(
                {
                    "name": "restricted_task",
                    "steps": [
                        {"type": "open_app", "app": "Safari"},
                        {"type": "done", "summary": "finished"},
                    ],
                }
            ),
            encoding="utf-8",
        )
        queue_db = self.root / "queue.db"
        SQLiteQueueStore(queue_db).enqueue(
            DatasetTargetType.TASK,
            task_path,
            permissions=ExecutionPermissions(
                allowed_apps=["计算器"],
                allowed_actions=[
                    ActionType.OPEN_APP,
                    ActionType.DONE,
                ],
            ),
            job_id="restricted-job",
        )
        environment = FakeEnvironment()
        executor = ActionExecutor(environment, settle_delay=0)
        reporter = ReportWriter(self.root / "reports")

        def dependency_factory(args, config):
            return (
                environment,
                executor,
                FakeVisionProvider(),
                reporter,
            )

        with (
            patch("soc_agent.cli.load_dotenv"),
            patch.dict(
                os.environ,
                {"OPENAI_API_KEY": "test-key"},
                clear=False,
            ),
            redirect_stdout(StringIO()),
        ):
            exit_code = main(
                [
                    "queue",
                    "run",
                    "--queue-db",
                    str(queue_db),
                ],
                dependency_factory=dependency_factory,
            )

        self.assertEqual(exit_code, 1)
        self.assertEqual(environment.calls, [])
        self.assertEqual(
            SQLiteQueueStore(queue_db).get("restricted-job").state,
            QueueState.CANCELLED,
        )

    def test_queue_worker_label_routing_controls_claim(self):
        task_path = self.root / "labeled_task.json"
        task_path.write_text(
            json.dumps(
                {
                    "name": "labeled_task",
                    "steps": [
                        {
                            "type": "write",
                            "content": "labeled task",
                        },
                        {"type": "done", "summary": "finished"},
                    ],
                }
            ),
            encoding="utf-8",
        )
        queue_db = self.root / "queue.db"
        store = SQLiteQueueStore(queue_db)
        store.enqueue(
            DatasetTargetType.TASK,
            task_path,
            required_labels=["office-mac"],
            job_id="labeled-job",
        )
        environment = FakeEnvironment()
        executor = ActionExecutor(environment, settle_delay=0)
        reporter = ReportWriter(self.root / "reports")

        def dependency_factory(args, config):
            return (
                environment,
                executor,
                FakeVisionProvider(),
                reporter,
            )

        first_output = StringIO()
        second_output = StringIO()
        with (
            patch("soc_agent.cli.load_dotenv"),
            patch.dict(
                os.environ,
                {"OPENAI_API_KEY": "test-key"},
                clear=False,
            ),
        ):
            with redirect_stdout(first_output):
                first_code = main(
                    [
                        "queue",
                        "run",
                        "--queue-db",
                        str(queue_db),
                    ],
                    dependency_factory=dependency_factory,
                )
            self.assertEqual(
                store.get("labeled-job").state,
                QueueState.PENDING,
            )

            with redirect_stdout(second_output):
                second_code = main(
                    [
                        "queue",
                        "run",
                        "--queue-db",
                        str(queue_db),
                        "--label",
                        "office-mac",
                    ],
                    dependency_factory=dependency_factory,
                )

        self.assertEqual(first_code, 0)
        self.assertIn(
            "No queued jobs were run.",
            first_output.getvalue(),
        )
        self.assertEqual(second_code, 0)
        self.assertIn(("write", "labeled task"), environment.calls)
        self.assertEqual(
            store.get("labeled-job").state,
            QueueState.PASSED,
        )

    def test_main_passes_cli_parameters_to_suite(self):
        suite_path = self.write_parameterized_suite()
        environment = FakeEnvironment()
        executor = ActionExecutor(environment, settle_delay=0)
        vision_provider = FakeVisionProvider()
        reporter = ReportWriter(self.root / "reports")

        def dependency_factory(args, config):
            self.assertEqual(args.command, "suite")
            self.assertEqual(args.param, ["right=23"])
            return environment, executor, vision_provider, reporter

        output = StringIO()
        with (
            patch("soc_agent.cli.load_dotenv"),
            patch.dict(
                os.environ,
                {"OPENAI_API_KEY": "test-key"},
                clear=False,
            ),
            redirect_stdout(output),
        ):
            exit_code = main(
                [
                    "suite",
                    str(suite_path),
                    "--param",
                    "right=23",
                ],
                dependency_factory=dependency_factory,
            )

        self.assertEqual(exit_code, 0)
        self.assertIn("Suite: suite", output.getvalue())
        self.assertIn("Report:", output.getvalue())
        self.assertIn(("write", "17*23"), environment.calls)
        self.assertIn(("write", "125*23"), environment.calls)

    def test_run_dataset_writes_task_and_summary_reports(self):
        environment = FakeEnvironment()
        executor = ActionExecutor(environment, settle_delay=0)
        reporter = ReportWriter(self.root / "reports")

        result = run_dataset(
            PROJECT_ROOT / "datasets" / "calculator_cases.json",
            environment,
            executor,
            FakeVisionProvider(),
            reporter,
        )

        self.assertEqual(result.status, TaskStatus.PASSED)
        self.assertEqual(
            [case.name for case in result.cases],
            ["default_17x23", "custom_3x4"],
        )
        self.assertIn(("write", "17*23"), environment.calls)
        self.assertIn(("write", "3*4"), environment.calls)

        for case in result.cases:
            self.assertTrue(Path(case.task_result.report_path).is_file())

        self.assertTrue(Path(result.report_path).is_file())
        payload = json.loads(
            Path(result.report_path).read_text(encoding="utf-8")
        )
        self.assertEqual(payload["dataset_name"], "calculator_regression")
        self.assertEqual(len(payload["cases"]), 2)

    def test_run_dataset_loads_cases_from_csv(self):
        environment = FakeEnvironment()
        executor = ActionExecutor(environment, settle_delay=0)
        reporter = ReportWriter(self.root / "reports")

        result = run_dataset(
            PROJECT_ROOT / "datasets" / "calculator_csv.json",
            environment,
            executor,
            FakeVisionProvider(),
            reporter,
        )

        self.assertEqual(result.status, TaskStatus.PASSED)
        self.assertEqual(result.total, 3)
        self.assertEqual(
            [case.name for case in result.cases],
            ["case_17x23", "case_125_div_5", "case_3x4"],
        )
        self.assertIn(("write", "17*23"), environment.calls)
        self.assertIn(("write", "125/5"), environment.calls)
        self.assertIn(("write", "3*4"), environment.calls)

        for case in result.cases:
            self.assertTrue(Path(case.task_result.report_path).is_file())

        payload = json.loads(
            Path(result.report_path).read_text(encoding="utf-8")
        )
        self.assertEqual(payload["dataset_name"], "calculator_csv_regression")
        self.assertEqual(len(payload["cases"]), 3)

    def test_run_dataset_loads_text_entries_from_csv(self):
        environment = FakeEnvironment()
        executor = ActionExecutor(environment, settle_delay=0)
        reporter = ReportWriter(self.root / "reports")

        result = run_dataset(
            PROJECT_ROOT / "datasets" / "textedit_csv.json",
            environment,
            executor,
            FakeVisionProvider(),
            reporter,
        )

        self.assertEqual(result.status, TaskStatus.PASSED)
        self.assertEqual(
            [case.name for case in result.cases],
            ["record_01", "record_02", "record_03"],
        )
        self.assertIn(("write", "客户：张三"), environment.calls)
        self.assertIn(("write", "备注：首次联系"), environment.calls)
        self.assertIn(("write", "客户：李四"), environment.calls)
        self.assertIn(("write", "备注：等待回访"), environment.calls)
        self.assertIn(("write", "客户：王五"), environment.calls)
        self.assertIn(("write", "备注：资料已确认"), environment.calls)
        self.assertIn(
            ("close_document", "文本编辑", False),
            environment.calls,
        )

        payload = json.loads(
            Path(result.report_path).read_text(encoding="utf-8")
        )
        self.assertEqual(payload["dataset_name"], "textedit_csv_workflow")
        self.assertEqual(len(payload["cases"]), 3)

    def test_run_dataset_executes_workflow_cases_from_csv(self):
        environment = FakeEnvironment()
        executor = ActionExecutor(environment, settle_delay=0)
        reporter = ReportWriter(self.root / "reports")

        result = run_dataset(
            PROJECT_ROOT
            / "datasets"
            / "textedit_workflow_csv.json",
            environment,
            executor,
            FakeVisionProvider(),
            reporter,
        )

        self.assertEqual(result.status, TaskStatus.PASSED)
        self.assertEqual(result.total, 2)
        self.assertEqual(
            [case.name for case in result.cases],
            ["customer_zhang", "customer_li"],
        )
        for case in result.cases:
            self.assertIsNone(case.task_result)
            self.assertIsNotNone(case.workflow_result)
            self.assertEqual(
                case.workflow_result.status,
                TaskStatus.PASSED,
            )
            self.assertTrue(Path(case.report_path).is_file())
            for task in case.workflow_result.task_results:
                self.assertTrue(
                    Path(task.task_result.report_path).is_file()
                )

        self.assertIn(("write", "客户：张三"), environment.calls)
        self.assertIn(("write", "备注：首次联系"), environment.calls)
        self.assertIn(("write", "客户：李四"), environment.calls)
        self.assertIn(("write", "备注：等待回访"), environment.calls)
        self.assertEqual(
            environment.calls.count(("write", "17*23")),
            2,
        )

        payload = json.loads(
            Path(result.report_path).read_text(encoding="utf-8")
        )
        self.assertEqual(
            payload["dataset_name"],
            "textedit_workflow_batch",
        )
        self.assertEqual(len(payload["cases"]), 2)
        self.assertIsNone(payload["cases"][0]["task_result"])
        self.assertEqual(
            payload["cases"][0]["workflow_result"]["status"],
            "passed",
        )

    def test_main_runs_dataset_command(self):
        environment = FakeEnvironment()
        executor = ActionExecutor(environment, settle_delay=0)
        vision_provider = FakeVisionProvider()
        reporter = ReportWriter(self.root / "reports")

        def dependency_factory(args, config):
            self.assertEqual(args.command, "dataset")
            self.assertFalse(hasattr(args, "param"))
            return environment, executor, vision_provider, reporter

        output = StringIO()
        with (
            patch("soc_agent.cli.load_dotenv"),
            patch.dict(
                os.environ,
                {"OPENAI_API_KEY": "test-key"},
                clear=False,
            ),
            redirect_stdout(output),
        ):
            exit_code = main(
                [
                    "dataset",
                    str(
                        PROJECT_ROOT
                        / "datasets"
                        / "calculator_cases.json"
                    ),
                ],
                dependency_factory=dependency_factory,
            )

        self.assertEqual(exit_code, 0)
        self.assertIn(("write", "17*23"), environment.calls)
        self.assertIn(("write", "3*4"), environment.calls)
        self.assertIn("Dataset: calculator_regression", output.getvalue())
        self.assertIn("Cases: 2", output.getvalue())
        self.assertIn("Passed: 2", output.getvalue())
        self.assertIn("Failed: 0", output.getvalue())
        self.assertIn("Timed out: 0", output.getvalue())
        self.assertIn("Cancelled: 0", output.getvalue())
        self.assertIn("Status: PASSED", output.getvalue())

    def test_main_dataset_stops_after_failed_case(self):
        environment = FakeEnvironment()
        executor = ActionExecutor(environment, settle_delay=0)
        vision_provider = FakeVisionProvider(response=False)
        reporter = ReportWriter(self.root / "reports")

        def dependency_factory(args, config):
            return environment, executor, vision_provider, reporter

        output = StringIO()
        with (
            patch("soc_agent.cli.load_dotenv"),
            patch.dict(
                os.environ,
                {"OPENAI_API_KEY": "test-key"},
                clear=False,
            ),
            redirect_stdout(output),
        ):
            exit_code = main(
                [
                    "dataset",
                    str(
                        PROJECT_ROOT
                        / "datasets"
                        / "calculator_cases.json"
                    ),
                    "--stop-on-failure",
                ],
                dependency_factory=dependency_factory,
            )

        self.assertEqual(exit_code, 1)
        self.assertIn(("write", "17*23"), environment.calls)
        self.assertNotIn(("write", "3*4"), environment.calls)
        self.assertIn("Cases: 1", output.getvalue())
        self.assertIn("Passed: 0", output.getvalue())
        self.assertIn("Failed: 1", output.getvalue())
        self.assertIn("Stopped early: yes", output.getvalue())
        self.assertIn("Status: FAILED", output.getvalue())
        self.assertIn("Case: default_17x23", output.getvalue())
        self.assertIn("Attempts: 1", output.getvalue())
        self.assertIn("Task report:", output.getvalue())
        self.assertIn("Failure log:", output.getvalue())

    def test_run_dataset_archives_failure_diagnostics(self):
        environment = FakeEnvironment()
        executor = ActionExecutor(environment, settle_delay=0)
        reporter = ReportWriter(self.root / "reports")

        result = run_dataset(
            PROJECT_ROOT
            / "datasets"
            / "calculator_failure_case.json",
            environment,
            executor,
            FakeVisionProvider(response=False),
            reporter,
        )

        self.assertEqual(result.status, TaskStatus.FAILED)
        self.assertEqual(len(result.cases), 1)
        case = result.cases[0]
        self.assertEqual(case.status, TaskStatus.FAILED)
        self.assertIsNotNone(case.task_result.failure_log)
        failure_log_path = (
            reporter.output_dir / case.task_result.failure_log
        )
        self.assertTrue(failure_log_path.is_file())
        self.assertIn(
            "vision verification failed",
            failure_log_path.read_text(encoding="utf-8"),
        )

        self.assertTrue(Path(result.report_path).is_file())
        payload = json.loads(
            Path(result.report_path).read_text(encoding="utf-8")
        )
        self.assertEqual(
            payload["cases"][0]["task_result"]["failure_log"],
            case.task_result.failure_log,
        )

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
