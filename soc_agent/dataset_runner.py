"""Sequential execution of task dataset cases."""

import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional, Union

from soc_agent.datasets import LoadedDataset
from soc_agent.task_models import (
    DatasetTargetType,
    TaskCaseDefinition,
    TaskCaseResult,
    TaskDatasetResult,
    TaskResult,
    TaskStatus,
    WorkflowResult,
)


class DatasetRunner:
    """Run every dataset case sequentially through an injected executor."""

    def __init__(
        self,
        execute_case: Callable[
            [Path, TaskCaseDefinition],
            Union[TaskResult, WorkflowResult],
        ],
        stop_on_failure: bool = False,
        clock: Optional[Callable[[], float]] = None,
        sleep: Optional[Callable[[float], None]] = None,
    ):
        self.execute_case = execute_case
        self.stop_on_failure = stop_on_failure
        self._clock = clock or time.monotonic
        self._sleep = sleep or time.sleep

    def run(self, loaded_dataset: LoadedDataset) -> TaskDatasetResult:
        started_at = datetime.now(timezone.utc)
        start_time = self._clock()
        case_results = []
        stopped_early = False

        for case in loaded_dataset.definition.cases:
            case_start_time = self._clock()
            attempts_used = 0

            for attempt in range(1, case.attempts + 1):
                attempts_used = attempt
                case_started_at = datetime.now(timezone.utc)
                try:
                    execution_result = self.execute_case(
                        loaded_dataset.target_path,
                        case,
                    )
                except Exception as error:
                    execution_result = self._failed_result(
                        loaded_dataset,
                        case_started_at,
                        str(error),
                    )

                if (
                    execution_result.status != TaskStatus.FAILED
                    or attempt == case.attempts
                ):
                    break
                self._sleep(case.retry_delay_seconds)

            case_duration = max(
                0.0,
                self._clock() - case_start_time,
            )

            case_results.append(
                self._case_result(
                    case,
                    attempts_used,
                    execution_result,
                    case_duration,
                )
            )

            if (
                self.stop_on_failure
                and execution_result.status != TaskStatus.PASSED
            ):
                stopped_early = True
                break

        return TaskDatasetResult(
            dataset_name=loaded_dataset.definition.name,
            status=self._aggregate_status(case_results),
            started_at=started_at,
            finished_at=datetime.now(timezone.utc),
            duration_seconds=max(0.0, self._clock() - start_time),
            cases=case_results,
            stopped_early=stopped_early,
        )

    @staticmethod
    def _aggregate_status(
        case_results,
    ) -> TaskStatus:
        statuses = {result.status for result in case_results}
        for status in (
            TaskStatus.FAILED,
            TaskStatus.TIMED_OUT,
            TaskStatus.CANCELLED,
        ):
            if status in statuses:
                return status
        return TaskStatus.PASSED

    @staticmethod
    def _case_result(
        case: TaskCaseDefinition,
        attempts_used: int,
        execution_result: Union[TaskResult, WorkflowResult],
        duration_seconds: float,
    ) -> TaskCaseResult:
        values = {
            "name": case.name,
            "parameters": case.parameters,
            "attempts": attempts_used,
            "status": execution_result.status,
            "duration_seconds": duration_seconds,
            "error": execution_result.error,
        }
        if isinstance(execution_result, WorkflowResult):
            return TaskCaseResult(
                workflow_result=execution_result,
                **values,
            )
        return TaskCaseResult(
            task_result=execution_result,
            **values,
        )

    @staticmethod
    def _failed_result(
        loaded_dataset: LoadedDataset,
        started_at: datetime,
        error: str,
    ) -> Union[TaskResult, WorkflowResult]:
        finished_at = datetime.now(timezone.utc)
        if loaded_dataset.target_type == DatasetTargetType.WORKFLOW:
            return WorkflowResult(
                workflow_name=loaded_dataset.target_path.stem,
                status=TaskStatus.FAILED,
                started_at=started_at,
                finished_at=finished_at,
                duration_seconds=0.0,
                error=error,
            )
        return TaskResult(
            task_name=loaded_dataset.target_path.stem,
            status=TaskStatus.FAILED,
            started_at=started_at,
            finished_at=finished_at,
            duration_seconds=0.0,
            error=error,
        )
