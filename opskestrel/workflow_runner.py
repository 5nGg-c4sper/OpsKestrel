"""Sequential execution of workflow tasks."""

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional

from opskestrel.runner import TaskRunner
from opskestrel.task_models import (
    StepPhase,
    TaskDefinition,
    TaskResult,
    TaskStatus,
    RuntimeVariableRecord,
    WorkflowResult,
    WorkflowTaskResult,
)
from opskestrel.workflows import LoadedWorkflow


class WorkflowRunnerError(RuntimeError):
    """Raised when a workflow cannot be prepared for execution."""


@dataclass(frozen=True)
class _PreparedTask:
    path: Path
    name: str
    parameters: Dict[str, str]
    runtime_outputs: List[str]


class WorkflowRunner:
    """Run loaded workflow tasks in order through an injected executor."""

    def __init__(
        self,
        execute_task: Callable[
            [Path, Dict[str, str], Dict[str, str]],
            TaskResult,
        ],
        task_loader: Optional[
            Callable[[Path], TaskDefinition]
        ] = None,
        clock: Optional[Callable[[], float]] = None,
    ):
        self.execute_task = execute_task
        self.task_loader = task_loader or TaskRunner.load_definition
        self._clock = clock or time.monotonic

    def run(self, loaded_workflow: LoadedWorkflow) -> WorkflowResult:
        runtime_names = set()
        prepared_tasks = []
        for path in loaded_workflow.task_paths:
            prepared = self._prepare_task(
                path,
                loaded_workflow.parameters,
                runtime_names,
            )
            prepared_tasks.append(prepared)
            runtime_names.update(prepared.runtime_outputs)
        cleanup_task = None
        if loaded_workflow.cleanup_task_path is not None:
            cleanup_task = self._prepare_task(
                loaded_workflow.cleanup_task_path,
                loaded_workflow.parameters,
                runtime_names,
            )

        started_at = datetime.now(timezone.utc)
        start_time = self._clock()
        runtime_values = {}
        runtime_variables = {}
        task_results = []
        stopped_early = False
        main_error = None

        for position, prepared_task in enumerate(prepared_tasks):
            result = self._execute(
                prepared_task,
                StepPhase.MAIN,
                runtime_values,
            )
            task_results.append(result)
            self._merge_runtime_values(
                result.task_result,
                runtime_values,
                runtime_variables,
            )
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
                runtime_values,
            )
            self._merge_runtime_values(
                cleanup_result.task_result,
                runtime_values,
                runtime_variables,
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
            runtime_variables=runtime_variables,
        )

    def _prepare_task(
        self,
        task_path: Path,
        workflow_parameters: Dict[str, str],
        runtime_names,
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
        runtime_outputs = [
            step.output
            for step in (
                definition.setup_steps
                + definition.steps
                + definition.cleanup_steps
            )
            if step.output is not None
        ]
        try:
            resolved = definition.resolve_parameters(parameters)
            definition.render_parameters(
                resolved,
                preserve_placeholders=(
                    set(runtime_names) | set(runtime_outputs)
                ),
            )
        except ValueError as error:
            raise WorkflowRunnerError(
                f"invalid parameters for workflow task "
                f"{definition.name!r}: {error}"
            ) from error

        conflicts = sorted(
            set(runtime_outputs) & set(workflow_parameters)
        )
        if conflicts:
            raise WorkflowRunnerError(
                "workflow task runtime outputs conflict with workflow "
                f"parameters: {', '.join(conflicts)}"
            )

        return _PreparedTask(
            path=task_path,
            name=definition.name,
            parameters=parameters,
            runtime_outputs=runtime_outputs,
        )

    def _execute(
        self,
        prepared_task: _PreparedTask,
        phase: StepPhase,
        runtime_values: Dict[str, str],
    ) -> WorkflowTaskResult:
        started_at = datetime.now(timezone.utc)
        start_time = self._clock()

        try:
            task_result = self.execute_task(
                prepared_task.path,
                dict(prepared_task.parameters),
                dict(runtime_values),
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
    def _merge_runtime_values(
        task_result: TaskResult,
        runtime_values: Dict[str, str],
        runtime_variables: Dict[str, RuntimeVariableRecord],
    ) -> None:
        runtime_values.update(task_result.runtime_values)
        runtime_variables.update(task_result.runtime_variables)

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
