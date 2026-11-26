"""Command-line interface for running task files."""

import argparse
import json
import signal
import sys
import tempfile
import threading
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from dotenv import load_dotenv

from soc_agent.actions.executor import ActionExecutor
from soc_agent.config import AgentConfig
from soc_agent.dataset_runner import DatasetRunner
from soc_agent.datasets import load_dataset
from soc_agent.diagnostics import DiagnosticsRunner
from soc_agent.environments.macos import MacOSEnvironment
from soc_agent.providers.qwen import QwenVisionProvider
from soc_agent.privacy import capture_screenshot
from soc_agent.queue_backend import create_queue_store
from soc_agent.queue_models import QueueJob, QueueState
from soc_agent.queue_worker import QueueWorker
from soc_agent.reporting.dataset_report import DatasetReportWriter
from soc_agent.reporting.report import ReportWriter
from soc_agent.reporting.suite_report import SuiteReportWriter
from soc_agent.reporting.workflow_report import WorkflowReportWriter
from soc_agent.runner import TaskRunner
from soc_agent.safety.policy import SafetyPolicy
from soc_agent.scenarios import load_scenario
from soc_agent.suite import SuiteResult, SuiteRunner
from soc_agent.task_models import (
    ActionType,
    DatasetTargetType,
    StepStatus,
    TaskDatasetResult,
    ExecutionPermissions,
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

    queue_parser = subparsers.add_parser(
        "queue",
        help="Manage and run the persistent task queue",
    )
    queue_commands = queue_parser.add_subparsers(
        dest="queue_command",
        required=True,
    )

    queue_enqueue = queue_commands.add_parser(
        "enqueue",
        help="Add a task or workflow to the queue",
    )
    queue_enqueue.add_argument(
        "target_type",
        choices=("task", "workflow"),
    )
    queue_enqueue.add_argument(
        "target_path",
        help="Path to a task or workflow JSON file",
    )
    queue_enqueue.add_argument(
        "--param",
        action="append",
        default=None,
        metavar="KEY=VALUE",
        help="Queue job parameter; may be repeated",
    )
    queue_enqueue.add_argument(
        "--priority",
        type=int,
        default=0,
        help="Higher priority jobs run first",
    )
    queue_enqueue.add_argument(
        "--allow-app",
        action="append",
        default=None,
        help="Allowed application name; may be repeated",
    )
    queue_enqueue.add_argument(
        "--allow-action",
        action="append",
        default=None,
        choices=tuple(action.value for action in ActionType),
        help="Allowed action type; may be repeated",
    )
    queue_enqueue.add_argument(
        "--require-label",
        action="append",
        default=None,
        help="Worker label required by this job; may be repeated",
    )
    queue_enqueue.add_argument(
        "--parallel-safe",
        action="store_true",
        help="Allow this job to run alongside other parallel-safe jobs",
    )
    queue_enqueue.add_argument(
        "--job-id",
        default=None,
        help="Optional caller-supplied job ID",
    )
    queue_enqueue.add_argument(
        "--queue-db",
        default="reports/queue.db",
        help="Path to the queue SQLite database",
    )

    queue_list = queue_commands.add_parser(
        "list",
        help="List queued jobs",
    )
    queue_list.add_argument(
        "--state",
        choices=tuple(state.value for state in QueueState),
        default=None,
    )
    queue_list.add_argument(
        "--queue-db",
        default="reports/queue.db",
        help="Path to the queue SQLite database",
    )

    queue_cancel = queue_commands.add_parser(
        "cancel",
        help="Cancel a pending queue job",
    )
    queue_cancel.add_argument("job_id")
    queue_cancel.add_argument(
        "--queue-db",
        default="reports/queue.db",
        help="Path to the queue SQLite database",
    )

    queue_retry = queue_commands.add_parser(
        "retry",
        help="Requeue a terminal failed or cancelled job",
    )
    queue_retry.add_argument("job_id")
    queue_retry.add_argument(
        "--queue-db",
        default="reports/queue.db",
        help="Path to the queue SQLite database",
    )

    queue_workers = queue_commands.add_parser(
        "workers",
        help="List registered queue workers",
    )
    queue_workers.add_argument(
        "--queue-db",
        default="reports/queue.db",
        help="Path to the queue SQLite database",
    )
    queue_workers.add_argument(
        "--online-within-seconds",
        type=float,
        default=300.0,
        help="Only show workers with a recent heartbeat",
    )

    queue_run = queue_commands.add_parser(
        "run",
        help="Run queued jobs",
    )
    queue_run.add_argument(
        "--queue-db",
        default="reports/queue.db",
        help="Path to the queue SQLite database",
    )
    queue_limit = queue_run.add_mutually_exclusive_group()
    queue_limit.add_argument(
        "--drain",
        action="store_true",
        help="Run until no pending jobs remain",
    )
    queue_limit.add_argument(
        "--max-jobs",
        type=int,
        default=1,
        help="Maximum jobs to run",
    )
    queue_run.add_argument(
        "--stale-after-seconds",
        type=float,
        default=3600.0,
        help="Recover running jobs after this lease duration",
    )
    queue_run.add_argument(
        "--max-attempts",
        type=int,
        default=3,
        help="Fail stale jobs after this many attempts",
    )
    queue_run.add_argument(
        "--worker-id",
        default=None,
        help="Optional stable worker ID",
    )
    queue_run.add_argument(
        "--label",
        action="append",
        default=None,
        help="Worker capability label; may be repeated",
    )
    queue_run.add_argument(
        "--max-concurrency",
        type=int,
        default=1,
        help="Maximum parallel jobs; GUI jobs remain globally serialized",
    )
    add_execution_options(
        queue_run,
        include_parameters=False,
    )

    queue_worker = queue_commands.add_parser(
        "worker",
        help="Run a long-lived polling queue worker",
    )
    queue_worker.add_argument(
        "--queue-db",
        default="reports/queue.db",
        help="Path to the queue SQLite database",
    )
    queue_worker.add_argument(
        "--poll-interval",
        type=float,
        default=2.0,
        help="Seconds to wait when the queue is empty",
    )
    queue_worker.add_argument(
        "--stale-after-seconds",
        type=float,
        default=3600.0,
        help="Recover running jobs after this lease duration",
    )
    queue_worker.add_argument(
        "--max-attempts",
        type=int,
        default=3,
        help="Fail stale jobs after this many attempts",
    )
    queue_worker.add_argument(
        "--worker-id",
        default=None,
        help="Optional stable worker ID",
    )
    queue_worker.add_argument(
        "--label",
        action="append",
        default=None,
        help="Worker capability label; may be repeated",
    )
    queue_worker.add_argument(
        "--max-concurrency",
        type=int,
        default=1,
        help="Maximum parallel jobs; GUI jobs remain globally serialized",
    )
    add_execution_options(
        queue_worker,
        include_parameters=False,
    )

    doctor_parser = subparsers.add_parser(
        "doctor",
        help="Check runtime configuration and Worker readiness",
    )
    doctor_parser.add_argument(
        "--queue-db",
        default="reports/queue.db",
        help="Queue database path or backend URL",
    )
    doctor_parser.add_argument(
        "--reports-dir",
        default=None,
        help="Report directory override",
    )
    doctor_parser.add_argument(
        "--worker-id",
        default=None,
        help="Require a specific Worker to be online",
    )
    doctor_parser.add_argument(
        "--online-within-seconds",
        type=float,
        default=300.0,
        help="Worker heartbeat window",
    )
    doctor_parser.add_argument(
        "--json",
        action="store_true",
        help="Render diagnostics as JSON",
    )

    scenario_parser = subparsers.add_parser(
        "scenario",
        help="Validate or run a packaged business scenario",
    )
    scenario_commands = scenario_parser.add_subparsers(
        dest="scenario_command",
        required=True,
    )
    scenario_validate = scenario_commands.add_parser(
        "validate",
        help="Validate a scenario package",
    )
    scenario_validate.add_argument("scenario_path")
    scenario_run = scenario_commands.add_parser(
        "run",
        help="Run the dataset contained in a scenario package",
    )
    scenario_run.add_argument("scenario_path")
    add_execution_options(
        scenario_run,
        include_parameters=False,
    )
    scenario_run.add_argument(
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
    runtime_values: Optional[Dict[str, str]] = None,
) -> TaskResult:
    task = TaskRunner.load_task(
        task_path,
        parameter_overrides,
        runtime_values=runtime_values,
    )
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
    result = runner.run(
        task,
        initial_runtime_values=runtime_values,
    )
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
        "element",
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

    if args.command == "queue":
        if args.queue_command == "enqueue":
            return enqueue_queue_job(
                args,
                parameter_overrides,
            )
        if args.queue_command == "list":
            return list_queue_jobs(args)
        if args.queue_command == "cancel":
            return cancel_queue_job(args)
        if args.queue_command == "retry":
            return retry_queue_job(args)
        if args.queue_command == "workers":
            return list_queue_workers(args)

    if args.command == "scenario":
        if args.scenario_command == "validate":
            return validate_scenario(args)

    load_dotenv()
    if args.command == "doctor":
        return run_doctor(args)

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
        elif args.command == "scenario":
            scenario = load_scenario(args.scenario_path)
            dataset_result = run_dataset(
                scenario.dataset.dataset_path,
                environment,
                executor,
                vision_provider,
                reporter,
                confirmation_handler=confirmation_handler,
                stop_on_failure=args.stop_on_failure,
            )
            print_dataset_result(dataset_result)
            return exit_code_for_status(dataset_result.status)
        elif args.command == "queue":
            if args.queue_command == "worker":
                completed_jobs = run_queue_daemon(
                    args.queue_db,
                    environment,
                    executor,
                    vision_provider,
                    reporter,
                    confirmation_handler=confirmation_handler,
                    poll_interval_seconds=args.poll_interval,
                    stale_after_seconds=args.stale_after_seconds,
                    max_attempts=args.max_attempts,
                    worker_id=args.worker_id,
                    worker_labels=args.label,
                    max_concurrency=args.max_concurrency,
                )
            else:
                completed_jobs = run_queue(
                    args.queue_db,
                    environment,
                    executor,
                    vision_provider,
                    reporter,
                    confirmation_handler=confirmation_handler,
                    max_jobs=None if args.drain else args.max_jobs,
                    stale_after_seconds=args.stale_after_seconds,
                    max_attempts=args.max_attempts,
                    worker_id=args.worker_id,
                    worker_labels=args.label,
                    max_concurrency=args.max_concurrency,
                )
            print_queue_jobs(completed_jobs)
            return (
                0
                if all(
                    job.state == QueueState.PASSED
                    for job in completed_jobs
                )
                else 1
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
                parameter_overrides=parameter_overrides,
            )
            print_suite_result(suite_result)
            return 0 if suite_result.successful else 1
    except Exception as error:
        print(f"Task execution failed: {error}")
        return 1

    print_result(result)
    return exit_code_for_status(result.status)


def run_doctor(args) -> int:
    try:
        report = DiagnosticsRunner().run(
            queue_db=args.queue_db,
            reports_dir=args.reports_dir,
            worker_id=args.worker_id,
            online_within_seconds=args.online_within_seconds,
        )
    except Exception as error:
        print(f"Diagnostics failed: {error}")
        return 1

    if args.json:
        print(
            json.dumps(
                report.to_dict(),
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        for check in report.checks:
            print(
                f"[{check.status.value.upper()}] "
                f"{check.name}: {check.message}"
            )
        print(
            "Runtime diagnostics: "
            f"{'PASSED' if report.healthy else 'FAILED'}"
        )
    return 0 if report.healthy else 1


def validate_scenario(args) -> int:
    try:
        scenario = load_scenario(args.scenario_path)
    except Exception as error:
        print(f"Scenario validation failed: {error}")
        return 1

    definition = scenario.definition
    print(f"Scenario: {definition.name}")
    print(f"Description: {definition.description}")
    print(f"Dataset: {scenario.dataset.dataset_path}")
    print(f"Workflow: {scenario.dataset.workflow_path}")
    print(f"Cases: {len(scenario.dataset.definition.cases)}")
    if definition.required_apps:
        print(f"Apps: {', '.join(definition.required_apps)}")
    print("Validation: PASSED")
    return 0


def enqueue_queue_job(args, parameters: Dict[str, str]) -> int:
    target_path = Path(args.target_path).expanduser().resolve()
    if not target_path.is_file():
        print(f"Queue enqueue failed: file not found: {target_path}")
        return 1

    try:
        store = create_queue_store(args.queue_db)
        job = store.enqueue(
            DatasetTargetType(args.target_type),
            target_path,
            parameters=parameters,
            permissions=ExecutionPermissions(
                allowed_apps=args.allow_app,
                allowed_actions=[
                    ActionType(value)
                    for value in args.allow_action or []
                ] or None,
            ),
            required_labels=args.require_label,
            parallel_safe=args.parallel_safe,
            priority=args.priority,
            job_id=args.job_id,
        )
    except Exception as error:
        print(f"Queue enqueue failed: {error}")
        return 1

    print(f"Enqueued: {job.job_id}")
    print(f"Target: {job.target_type.value} {job.target_path}")
    print(f"Priority: {job.priority}")
    return 0


def list_queue_jobs(args) -> int:
    try:
        store = create_queue_store(args.queue_db)
        state = QueueState(args.state) if args.state else None
        jobs = store.list_jobs(state)
    except Exception as error:
        print(f"Queue list failed: {error}")
        return 1

    if not jobs:
        print("No queue jobs.")
        return 0

    for job in jobs:
        print(
            f"{job.job_id} {job.state.value} "
            f"{job.target_type.value} {job.target_path}"
        )
        if job.report_path:
            print(f"  Report: {job.report_path}")
        if job.error:
            print(f"  Error: {job.error}")
        if job.worker_id:
            print(f"  Worker: {job.worker_id}")
        if job.permissions.allowed_apps is not None:
            print(
                "  Allowed apps: "
                + ", ".join(job.permissions.allowed_apps)
            )
        if job.permissions.allowed_actions is not None:
            print(
                "  Allowed actions: "
                + ", ".join(
                    action.value
                    for action in job.permissions.allowed_actions
                )
            )
        if job.required_labels:
            print(
                "  Required labels: "
                + ", ".join(job.required_labels)
            )
        if job.parallel_safe:
            print("  Parallel-safe: yes")
    return 0


def cancel_queue_job(args) -> int:
    try:
        job = create_queue_store(args.queue_db).cancel(args.job_id)
    except Exception as error:
        print(f"Queue cancel failed: {error}")
        return 1

    print(f"Cancelled: {job.job_id}")
    return 0


def retry_queue_job(args) -> int:
    try:
        job = create_queue_store(args.queue_db).retry(args.job_id)
    except Exception as error:
        print(f"Queue retry failed: {error}")
        return 1

    print(f"Retried: {job.job_id}")
    print(f"State: {job.state.value}")
    print("Attempts reset: 0")
    return 0


def run_queue(
    queue_db,
    environment,
    executor,
    vision_provider,
    reporter,
    confirmation_handler=None,
    max_jobs: Optional[int] = 1,
    stale_after_seconds: float = 3600,
    max_attempts: int = 3,
    worker_id: Optional[str] = None,
    worker_labels: Optional[List[str]] = None,
    max_concurrency: int = 1,
) -> list:
    store = create_queue_store(queue_db)
    execute_job = make_queue_job_executor(
        environment,
        executor,
        vision_provider,
        reporter,
        confirmation_handler=confirmation_handler,
    )

    return QueueWorker(
        store,
        execute_job,
        stale_after_seconds=stale_after_seconds,
        max_attempts=max_attempts,
        worker_id=worker_id,
        labels=worker_labels,
        max_concurrency=max_concurrency,
    ).run_until_empty(max_jobs=max_jobs)


def run_queue_daemon(
    queue_db,
    environment,
    executor,
    vision_provider,
    reporter,
    confirmation_handler=None,
    poll_interval_seconds: float = 2.0,
    stale_after_seconds: float = 3600,
    max_attempts: int = 3,
    worker_id: Optional[str] = None,
    worker_labels: Optional[List[str]] = None,
    max_concurrency: int = 1,
    stop_event: Optional[threading.Event] = None,
) -> list:
    store = create_queue_store(queue_db)
    execute_job = make_queue_job_executor(
        environment,
        executor,
        vision_provider,
        reporter,
        confirmation_handler=confirmation_handler,
    )
    worker = QueueWorker(
        store,
        execute_job,
        stale_after_seconds=stale_after_seconds,
        max_attempts=max_attempts,
        worker_id=worker_id,
        labels=worker_labels,
        max_concurrency=max_concurrency,
    )

    owns_stop_event = stop_event is None
    stop_event = stop_event or threading.Event()
    previous_handlers = {}
    if owns_stop_event:
        def request_stop(signum, frame):
            stop_event.set()

        for signal_number in (signal.SIGINT, signal.SIGTERM):
            previous_handlers[signal_number] = signal.getsignal(
                signal_number
            )
            signal.signal(signal_number, request_stop)

    try:
        return worker.run_forever(
            poll_interval_seconds=poll_interval_seconds,
            stop_event=stop_event,
        )
    finally:
        for signal_number, handler in previous_handlers.items():
            signal.signal(signal_number, handler)


def make_queue_job_executor(
    environment,
    executor,
    vision_provider,
    reporter,
    confirmation_handler=None,
):
    def execute_job(job: QueueJob):
        policy = SafetyPolicy(
            allowed_apps=job.permissions.allowed_apps,
            allowed_actions=job.permissions.allowed_actions,
        )
        if job.target_type == DatasetTargetType.WORKFLOW:
            return run_workflow(
                job.target_path,
                environment,
                executor,
                vision_provider,
                reporter,
                confirmation_handler=confirmation_handler,
                parameter_overrides=job.parameters,
                policy=policy,
            )
        return run_task(
            job.target_path,
            environment,
            executor,
            vision_provider,
            reporter,
            confirmation_handler=confirmation_handler,
            parameter_overrides=job.parameters,
            policy=policy,
        )

    return execute_job


def list_queue_workers(args) -> int:
    try:
        store = create_queue_store(args.queue_db)
        workers = store.list_workers(
            online_within_seconds=args.online_within_seconds
        )
    except Exception as error:
        print(f"Queue workers failed: {error}")
        return 1

    if not workers:
        print("No online queue workers.")
        return 0

    for worker in workers:
        print(
            f"{worker.worker_id} {worker.state.value} "
            f"{worker.hostname}:{worker.pid}"
        )
        print(f"  Last heartbeat: {worker.last_heartbeat.isoformat()}")
        if worker.current_job_id:
            print(f"  Current job: {worker.current_job_id}")
        if worker.labels:
            print(f"  Labels: {', '.join(worker.labels)}")
    return 0


def print_queue_jobs(jobs) -> None:
    if not jobs:
        print("No queued jobs were run.")
        return
    for job in jobs:
        print(f"Queue job: {job.job_id}")
        print(f"Status: {job.state.value.upper()}")
        if job.report_path:
            print(f"Report: {job.report_path}")
        if job.error:
            print(f"Error: {job.error}")


def run_workflow(
    workflow_path,
    environment,
    executor,
    vision_provider,
    reporter,
    confirmation_handler=None,
    parameter_overrides: Optional[Dict[str, str]] = None,
    policy=None,
) -> WorkflowResult:
    loaded_workflow = load_workflow(
        workflow_path,
        parameter_overrides,
    )

    def execute_task(task_path, parameters, runtime_values):
        print(f"Running: {task_path.name}")
        result = run_task(
            task_path,
            environment,
            executor,
            vision_provider,
            reporter,
            confirmation_handler=confirmation_handler,
            parameter_overrides=parameters,
            policy=policy,
            runtime_values=runtime_values,
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
        if (
            step.condition_prompt is None
            and step.condition_variable is None
        ):
            continue
        print(
            f"Condition [{step.index}] {step.status.value}: "
            f"expected={step.condition_expected}, "
            f"actual={step.condition_actual}, "
            f"duration={step.condition_duration_seconds or 0.0:.2f}s"
        )
        if step.condition_variable is not None:
            print(
                f"  Variable: {step.condition_variable} "
                f"{step.condition_operator.value if step.condition_operator else ''}"
            )
            print(f"  Expected value: {step.condition_expected_value}")
            print(f"  Actual value: {step.condition_actual_value}")
        if step.condition_prompt is not None:
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
