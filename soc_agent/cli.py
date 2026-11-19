"""Command-line interface for running task files."""

import argparse
import sys
import tempfile
from pathlib import Path
from typing import Dict, Optional, Sequence

from dotenv import load_dotenv

from soc_agent.actions.executor import ActionExecutor
from soc_agent.config import AgentConfig
from soc_agent.environments.macos import MacOSEnvironment
from soc_agent.providers.qwen import QwenVisionProvider
from soc_agent.reporting.report import ReportWriter
from soc_agent.runner import TaskRunner
from soc_agent.safety.policy import SafetyPolicy
from soc_agent.suite import SuiteResult, SuiteRunner
from soc_agent.task_models import (
    ActionType,
    StepStatus,
    TaskResult,
    TaskStatus,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="soc-agent",
        description="Run deterministic macOS desktop tasks.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Run a task JSON file")
    run_parser.add_argument("task", help="Path to the task JSON file")
    add_execution_options(run_parser)

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
    return parser


def add_execution_options(parser: argparse.ArgumentParser) -> None:
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

        environment.screenshot(current_path)
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
            environment.screenshot(failure_path)
            return str(failure_path)

        return None

    runner = TaskRunner(
        executor,
        vision_verifier=verify_vision,
        artifact_provider=artifact_provider,
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
            )
        else:
            suite_result = run_suite(
                args.suite_path,
                environment,
                executor,
                vision_provider,
                reporter,
                confirmation_handler=confirmation_handler,
                stop_on_failure=args.stop_on_failure,
            )
            print_suite_result(suite_result)
            return 0 if suite_result.successful else 1
    except Exception as error:
        print(f"Task execution failed: {error}")
        return 1

    print_result(result)
    return exit_code_for_status(result.status)


def run_suite(
    suite_path,
    environment,
    executor,
    vision_provider,
    reporter,
    confirmation_handler=None,
    stop_on_failure=False,
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
        )
        print(f"Status: {result.status.value.upper()}")
        return result

    return SuiteRunner(
        execute_task,
        stop_on_failure=stop_on_failure,
    ).run(suite_path)


def print_result(result: TaskResult) -> None:
    print(f"Task: {result.task_name}")
    print(f"Status: {result.status.value.upper()}")
    print(f"Duration: {result.duration_seconds:.2f} seconds")
    if result.report_path:
        print(f"Report: {result.report_path}")
    if result.error:
        print(f"Error: {result.error}")


def print_suite_result(result: SuiteResult) -> None:
    print(f"Total: {result.total}")
    print(f"Passed: {result.passed}")
    print(f"Failed: {result.failed}")
    print(f"Timed out: {result.timed_out}")
    print(f"Cancelled: {result.cancelled}")
    print(f"Duration: {result.duration_seconds:.2f} seconds")
    if result.stopped_early:
        print("Stopped early: yes")


if __name__ == "__main__":
    raise SystemExit(main())
