"""Sequential execution of workflow tasks."""

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional

from soc_agent.runner import TaskRunner
from soc_agent.task_models import (
    StepPhase,
    TaskDefinition,
    TaskResult,
    TaskStatus,
    WorkflowResult,
    WorkflowTaskResult,
)
from soc_agent.workflows import LoadedWorkflow


class WorkflowRunnerError(RuntimeError):
    """Raised when a workflow cannot be prepared for execution."""


@dataclass(frozen=True)
class _PreparedTask:
    path: Path
    name: str
    parameters: Dict[str, str]


class WorkflowRunner:
    """Run loaded workflow tasks in order through an injected executor."""

    def __init__(
        self,
        execute_task: Callable[[Path, Dict[str, str]], TaskResult],
        task_loader: Optional[
            Callable[[Path], TaskDefinition]
        ] = None,
        clock: Optional[Callable[[], float]] = None,
    ):
        self.execute_task = execute_task
        self.task_loader = task_loader or TaskRunner.load_definition
        self._clock = clock or time.monotonic

    def run(self, loaded_workflow: LoadedWorkflow) -> WorkflowResult:
        prepared_tasks = [
            self._prepare_task(path, loaded_workflow.parameters)
            for path in loaded_workflow.task_paths
        ]
        cleanup_task = None
        if loaded_workflow.cleanup_task_path is not None:
            cleanup_task = self._prepare_task(
                loaded_workflow.cleanup_task_path,
                loaded_workflow.parameters,
            )

        started_at = datetime.now(timezone.utc)
        start_time = self._clock()
        task_results = []
        stopped_early = False
        main_error = None

        for position, prepared_task in enumerate(prepared_tasks):
            result = self._execute(prepared_task, StepPhase.MAIN)
            task_results.append(result)
            if result.status != TaskStatus.PASSED:
                stopped_early = position + 1 < len(prepared_tasks)
                main_error = result.error
                break

        cleanup_result = None
        cleanup_error = None
        if cleanup_task is not None:
            cleanup_result = self._execute(
                cleanup_task,
                StepPhase.CLEANUP,
            )
            if cleanup_result.status != TaskStatus.PASSED:
                cleanup_error = cleanup_result.error

        status = self._aggregate_status(task_results)
        error = main_error
        if (
            cleanup_result is not None
            and cleanup_result.status != TaskStatus.PASSED
            and status == TaskStatus.PASSED
        ):
            status = cleanup_result.status
            error = cleanup_error

        return WorkflowResult(
            workflow_name=loaded_workflow.definition.name,
            status=status,
            started_at=started_at,
            finished_at=datetime.now(timezone.utc),
            duration_seconds=max(0.0, self._clock() - start_time),
            task_results=task_results,
            cleanup_result=cleanup_result,
            stopped_early=stopped_early,
            error=error,
        )

    def _prepare_task(
        self,
        task_path: Path,
        workflow_parameters: Dict[str, str],
    ) -> _PreparedTask:
        definition = self.task_loader(task_path)
        task_parameter_names = set(definition.parameters)

        missing_parameters = sorted(
            name
            for name, parameter in definition.parameters.items()
            if parameter.default is None
            and name not in workflow_parameters
        )
        if missing_parameters:
            raise WorkflowRunnerError(
                "workflow task "
                f"{definition.name!r} requires parameters not provided by "
                f"the workflow: {', '.join(missing_parameters)}"
            )

        parameters = {
            name: value
            for name, value in workflow_parameters.items()
            if name in task_parameter_names
        }
        try:
            resolved = definition.resolve_parameters(parameters)
            definition.render_parameters(resolved)
        except ValueError as error:
            raise WorkflowRunnerError(
                f"invalid parameters for workflow task "
                f"{definition.name!r}: {error}"
            ) from error

        return _PreparedTask(
            path=task_path,
            name=definition.name,
            parameters=parameters,
        )

    def _execute(
        self,
        prepared_task: _PreparedTask,
        phase: StepPhase,
    ) -> WorkflowTaskResult:
        started_at = datetime.now(timezone.utc)
        start_time = self._clock()

        try:
            task_result = self.execute_task(
                prepared_task.path,
                dict(prepared_task.parameters),
            )
        except Exception as error:
            finished_at = datetime.now(timezone.utc)
            task_result = TaskResult(
                task_name=prepared_task.name,
                status=TaskStatus.FAILED,
                started_at=started_at,
                finished_at=finished_at,
                duration_seconds=max(
                    0.0,
                    self._clock() - start_time,
                ),
                error=str(error),
            )

        finished_at = datetime.now(timezone.utc)
        return WorkflowTaskResult(
            task_name=prepared_task.name,
            task_path=str(prepared_task.path),
            phase=phase,
            status=task_result.status,
            parameters=dict(prepared_task.parameters),
            started_at=started_at,
            finished_at=finished_at,
            duration_seconds=max(0.0, self._clock() - start_time),
            error=task_result.error,
            task_result=task_result,
        )

    @staticmethod
    def _aggregate_status(
        task_results: List[WorkflowTaskResult],
    ) -> TaskStatus:
        statuses = {result.status for result in task_results}
        for status in (
            TaskStatus.FAILED,
            TaskStatus.TIMED_OUT,
            TaskStatus.CANCELLED,
        ):
            if status in statuses:
                return status
        return TaskStatus.PASSED
