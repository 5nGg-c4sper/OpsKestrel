"""Command-line interface for running task files."""

import argparse
import sys
import tempfile
from pathlib import Path
from typing import Dict, Optional, Sequence

from dotenv import load_dotenv

from soc_agent.actions.executor import ActionExecutor
from soc_agent.config import AgentConfig
from soc_agent.dataset_runner import DatasetRunner
from soc_agent.datasets import load_dataset
from soc_agent.environments.macos import MacOSEnvironment
from soc_agent.providers.qwen import QwenVisionProvider
from soc_agent.privacy import capture_screenshot
from soc_agent.reporting.dataset_report import DatasetReportWriter
from soc_agent.reporting.report import ReportWriter
from soc_agent.reporting.suite_report import SuiteReportWriter
from soc_agent.reporting.workflow_report import WorkflowReportWriter
from soc_agent.runner import TaskRunner
from soc_agent.safety.policy import SafetyPolicy
from soc_agent.suite import SuiteResult, SuiteRunner
from soc_agent.task_models import (
    ActionType,
    DatasetTargetType,
    StepStatus,
    TaskDatasetResult,
    TaskResult,
    TaskStatus,
    WorkflowResult,
)
from soc_agent.workflow_runner import WorkflowRunner
from soc_agent.workflows import load_workflow


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="soc-agent",
        description="Run deterministic macOS desktop tasks.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Run a task JSON file")
    run_parser.add_argument("task", help="Path to the task JSON file")
    add_execution_options(run_parser)

    workflow_parser = subparsers.add_parser(
        "workflow",
        help="Run an ordered workflow JSON file",
    )
    workflow_parser.add_argument(
        "workflow_path",
        help="Path to the workflow JSON file",
    )
    add_execution_options(workflow_parser)

    suite_parser = subparsers.add_parser(
        "suite",
        help="Run all JSON tasks in a directory",
    )
    suite_parser.add_argument(
        "suite_path",
        help="Directory or JSON file containing tasks",
    )
    add_execution_options(suite_parser)
    suite_parser.add_argument(
        "--stop-on-failure",
        action="store_true",
        help="Stop after the first unsuccessful task",
    )

    dataset_parser = subparsers.add_parser(
        "dataset",
        help="Run all cases in a task dataset",
    )
    dataset_parser.add_argument(
        "dataset_path",
        help="Path to the dataset JSON file",
    )
    add_execution_options(
        dataset_parser,
        include_parameters=False,
    )
    dataset_parser.add_argument(
        "--stop-on-failure",
        action="store_true",
        help="Stop after the first unsuccessful case",
    )
    return parser


def add_execution_options(
    parser: argparse.ArgumentParser,
    include_parameters: bool = True,
) -> None:
    parser.add_argument(
        "--reports-dir",
        default=None,
        help="Directory for JSON execution reports",
    )
    parser.add_argument(
        "--scale",
        type=float,
        default=None,
        help="Screenshot scale passed to the macOS environment",
    )
    parser.add_argument(
        "--settle-delay",
        type=float,
        default=None,
        help="Delay after application, key, and click actions",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Override the Qwen vision model name",
    )
    if include_parameters:
        parser.add_argument(
            "--param",
            action="append",
            default=None,
            metavar="KEY=VALUE",
            help="Override a task parameter; may be repeated",
        )
    parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="Cancel steps that require manual confirmation",
    )


def parse_parameter_overrides(
    raw_values: Optional[Sequence[str]],
) -> Dict[str, str]:
    """Parse repeated ``KEY=VALUE`` task parameter overrides."""
    overrides = {}
    for raw_value in raw_values or []:
        name, separator, value = raw_value.partition("=")
        if not separator or not name:
            raise ValueError(
                f"invalid task parameter override {raw_value!r}; "
                "expected KEY=VALUE"
            )
        if name in overrides:
            raise ValueError(f"duplicate task parameter override: {name}")
        overrides[name] = value
    return overrides


def run_task(
    task_path,
    environment,
    executor,
    vision_provider,
    reporter,
    screenshot_path=None,
    policy=None,
    confirmation_handler=None,
    parameter_overrides: Optional[Dict[str, str]] = None,
) -> TaskResult:
    task = TaskRunner.load_task(task_path, parameter_overrides)
    screenshot_path = Path(
        screenshot_path
        or Path(tempfile.gettempdir()) / f"soc-{task.name}-verify.png"
    )
    pending_verification_screenshots = []
    verification_count = 0

    def verify_vision(statement: str) -> bool:
        nonlocal verification_count
        current_path = screenshot_path
        if verification_count:
            current_path = screenshot_path.with_name(
                f"{screenshot_path.stem}-{verification_count}"
                f"{screenshot_path.suffix}"
            )
        verification_count += 1

        capture_screenshot(
            environment,
            current_path,
            task.redaction_regions,
        )
        pending_verification_screenshots.append(str(current_path))
        return vision_provider.verify(str(current_path), statement)

    def artifact_provider(index, step, status):
        if (
            step.type == ActionType.VERIFY_VISION
            and pending_verification_screenshots
        ):
            return pending_verification_screenshots.pop(0)

        if status == StepStatus.FAILED:
            failure_path = screenshot_path.with_name(
                f"{screenshot_path.stem}-step-{index:03d}"
                f"{screenshot_path.suffix}"
            )
            capture_screenshot(
                environment,
                failure_path,
                task.redaction_regions,
            )
            return str(failure_path)

        return None

    def condition_artifact_provider(index, step):
        if pending_verification_screenshots:
            return pending_verification_screenshots.pop(0)
        return None

    runner = TaskRunner(
        executor,
        vision_verifier=verify_vision,
        artifact_provider=artifact_provider,
        condition_artifact_provider=condition_artifact_provider,
        policy=policy or SafetyPolicy(),
        confirmation_handler=confirmation_handler,
    )
    result = runner.run(task)
    reporter.write(result)
    return result


def exit_code_for_status(status: TaskStatus) -> int:
    return 0 if status == TaskStatus.PASSED else 1


def non_interactive_confirmation(step) -> bool:
    """Reject steps that require confirmation without prompting."""
    return False


def terminal_confirmation_handler(step, input_fn=input, output=None) -> bool:
    """Prompt the user before a step marked as requiring confirmation."""
    output = output or sys.stdout
    print("Confirmation required:", file=output)
    print(f"Action: {step.type.value}", file=output)

    for field_name in (
        "app",
        "content",
        "keys",
        "x",
        "y",
        "prompt",
        "summary",
    ):
        value = getattr(step, field_name)
        if value is not None:
            print(f"{field_name}: {value}", file=output)

    try:
        answer = input_fn("Proceed? [y/N]: ")
    except EOFError:
        return False

    return answer.strip().lower() in {"y", "yes"}


def main(
    argv: Optional[Sequence[str]] = None,
    dependency_factory=None,
) -> int:
    args = build_parser().parse_args(argv)
    try:
        parameter_overrides = parse_parameter_overrides(
            getattr(args, "param", None)
        )
    except ValueError as error:
        print(f"Task execution failed: {error}")
        return 1

    load_dotenv()
    config = AgentConfig.from_env().with_overrides(
        screenshot_scale=args.scale,
        settle_delay=args.settle_delay,
        reports_dir=args.reports_dir,
        model=args.model,
    )
    confirmation_handler = (
        non_interactive_confirmation
        if args.non_interactive
        else terminal_confirmation_handler
    )

    if dependency_factory is None:
        environment = MacOSEnvironment(scale=config.screenshot_scale)
        executor = ActionExecutor(
            environment,
            settle_delay=config.settle_delay,
        )
        vision_provider = QwenVisionProvider(
            api_key=config.api_key,
            base_url=config.base_url,
            model=config.model,
            timeout=config.qwen_timeout,
        )
        reporter = ReportWriter(config.reports_dir)
    else:
        environment, executor, vision_provider, reporter = (
            dependency_factory(args, config)
        )

    try:
        if args.command == "run":
            result = run_task(
                args.task,
                environment,
                executor,
                vision_provider,
                reporter,
                confirmation_handler=confirmation_handler,
                parameter_overrides=parameter_overrides,
            )
        elif args.command == "workflow":
            workflow_result = run_workflow(
                args.workflow_path,
                environment,
                executor,
                vision_provider,
                reporter,
                confirmation_handler=confirmation_handler,
                parameter_overrides=parameter_overrides,
            )
            print_workflow_result(workflow_result)
            return exit_code_for_status(workflow_result.status)
        elif args.command == "dataset":
            dataset_result = run_dataset(
                args.dataset_path,
                environment,
                executor,
                vision_provider,
                reporter,
                confirmation_handler=confirmation_handler,
                stop_on_failure=args.stop_on_failure,
            )
            print_dataset_result(dataset_result)
            return exit_code_for_status(dataset_result.status)
        else:
            suite_result = run_suite(
                args.suite_path,
                environment,
                executor,
                vision_provider,
                reporter,
                confirmation_handler=confirmation_handler,
                stop_on_failure=args.stop_on_failure,
                parameter_overrides=parameter_overrides,
            )
            print_suite_result(suite_result)
            return 0 if suite_result.successful else 1
    except Exception as error:
        print(f"Task execution failed: {error}")
        return 1

    print_result(result)
    return exit_code_for_status(result.status)


def run_workflow(
    workflow_path,
    environment,
    executor,
    vision_provider,
    reporter,
    confirmation_handler=None,
    parameter_overrides: Optional[Dict[str, str]] = None,
) -> WorkflowResult:
    loaded_workflow = load_workflow(
        workflow_path,
        parameter_overrides,
    )

    def execute_task(task_path, parameters):
        print(f"Running: {task_path.name}")
        result = run_task(
            task_path,
            environment,
            executor,
            vision_provider,
            reporter,
            confirmation_handler=confirmation_handler,
            parameter_overrides=parameters,
        )
        print(f"Status: {result.status.value.upper()}")
        return result

    result = WorkflowRunner(execute_task).run(loaded_workflow)
    WorkflowReportWriter(reporter.output_dir).write(result)
    return result


def run_suite(
    suite_path,
    environment,
    executor,
    vision_provider,
    reporter,
    confirmation_handler=None,
    stop_on_failure=False,
    parameter_overrides: Optional[Dict[str, str]] = None,
) -> SuiteResult:
    def execute_task(task_path):
        print(f"Running: {task_path.name}")
        result = run_task(
            task_path,
            environment,
            executor,
            vision_provider,
            reporter,
            confirmation_handler=confirmation_handler,
            parameter_overrides=parameter_overrides,
        )
        print(f"Status: {result.status.value.upper()}")
        return result

    result = SuiteRunner(
        execute_task,
        stop_on_failure=stop_on_failure,
    ).run(suite_path)
    SuiteReportWriter(reporter.output_dir).write(result)
    return result


def run_dataset(
    dataset_path,
    environment,
    executor,
    vision_provider,
    reporter,
    confirmation_handler=None,
    stop_on_failure=False,
) -> TaskDatasetResult:
    loaded_dataset = load_dataset(dataset_path)

    def execute_case(target_path, case):
        if loaded_dataset.target_type == DatasetTargetType.WORKFLOW:
            return run_workflow(
                target_path,
                environment,
                executor,
                vision_provider,
                reporter,
                confirmation_handler=confirmation_handler,
                parameter_overrides=case.parameters,
            )
        return run_task(
            target_path,
            environment,
            executor,
            vision_provider,
            reporter,
            confirmation_handler=confirmation_handler,
            parameter_overrides=case.parameters,
        )

    result = DatasetRunner(
        execute_case,
        stop_on_failure=stop_on_failure,
    ).run(loaded_dataset)
    DatasetReportWriter(reporter.output_dir).write(result)
    return result


def print_result(result: TaskResult) -> None:
    print(f"Task: {result.task_name}")
    print(f"Status: {result.status.value.upper()}")
    print(f"Duration: {result.duration_seconds:.2f} seconds")
    if result.report_path:
        print(f"Report: {result.report_path}")
    if result.error:
        print(f"Error: {result.error}")
    if result.failure_log:
        print(f"Failure log: {result.failure_log}")
    print_condition_diagnostics(result)


def print_condition_diagnostics(result: TaskResult) -> None:
    for step in result.steps:
        if step.condition_prompt is None:
            continue
        print(
            f"Condition [{step.index}] {step.status.value}: "
            f"expected={step.condition_expected}, "
            f"actual={step.condition_actual}, "
            f"duration={step.condition_duration_seconds or 0.0:.2f}s"
        )
        print(f"  Prompt: {step.condition_prompt}")
        if step.condition_screenshot:
            print(
                f"  Screenshot: {step.condition_screenshot}"
            )


def print_suite_result(result: SuiteResult) -> None:
    print(f"Suite: {result.suite_name}")
    print(f"Total: {result.total}")
    print(f"Passed: {result.passed}")
    print(f"Failed: {result.failed}")
    print(f"Timed out: {result.timed_out}")
    print(f"Cancelled: {result.cancelled}")
    print(f"Duration: {result.duration_seconds:.2f} seconds")
    if result.report_path:
        print(f"Report: {result.report_path}")
    if result.stopped_early:
        print("Stopped early: yes")


def print_workflow_result(result: WorkflowResult) -> None:
    print(f"Workflow: {result.workflow_name}")
    print(f"Status: {result.status.value.upper()}")
    print(f"Tasks: {result.total}")
    print(f"Passed: {result.passed}")
    print(f"Failed: {result.failed}")
    print(f"Timed out: {result.timed_out}")
    print(f"Cancelled: {result.cancelled}")
    print(f"Duration: {result.duration_seconds:.2f} seconds")
    if result.report_path:
        print(f"Report: {result.report_path}")
    if result.stopped_early:
        print("Stopped early: yes")
    if result.error:
        print(f"Error: {result.error}")

    for task in result.task_results:
        if task.status == TaskStatus.PASSED:
            continue
        print(f"Task: {task.task_name}")
        print(f"  Status: {task.status.value.upper()}")
        if task.error:
            print(f"  Error: {task.error}")
        if task.task_result.report_path:
            print(f"  Task report: {task.task_result.report_path}")
        if task.task_result.failure_log:
            print(f"  Failure log: {task.task_result.failure_log}")

    if result.cleanup_result is not None:
        cleanup = result.cleanup_result
        print(f"Cleanup: {cleanup.status.value.upper()}")
        if cleanup.error:
            print(f"  Error: {cleanup.error}")
        if cleanup.task_result.report_path:
            print(f"  Task report: {cleanup.task_result.report_path}")
        if cleanup.task_result.failure_log:
            print(f"  Failure log: {cleanup.task_result.failure_log}")


def print_dataset_result(result: TaskDatasetResult) -> None:
    print(f"Dataset: {result.dataset_name}")
    print(f"Status: {result.status.value.upper()}")
    print(f"Cases: {result.total}")
    print(f"Passed: {result.passed}")
    print(f"Failed: {result.failed}")
    print(f"Timed out: {result.timed_out}")
    print(f"Cancelled: {result.cancelled}")
    print(f"Duration: {result.duration_seconds:.2f} seconds")
    if result.report_path:
        print(f"Report: {result.report_path}")
    if result.stopped_early:
        print("Stopped early: yes")

    for case in result.cases:
        if case.status == TaskStatus.PASSED:
            continue
        print(f"Case: {case.name}")
        print(f"  Status: {case.status.value.upper()}")
        print(f"  Attempts: {case.attempts}")
        if case.error:
            print(f"  Error: {case.error}")
        if case.target_type == DatasetTargetType.WORKFLOW:
            report_label = "Workflow report"
        else:
            report_label = "Task report"
        if case.report_path:
            print(f"  {report_label}: {case.report_path}")
        if case.failure_log:
            print(f"  Failure log: {case.failure_log}")


if __name__ == "__main__":
    raise SystemExit(main())
