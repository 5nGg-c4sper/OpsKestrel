"""Sequential execution of task dataset cases."""

import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from soc_agent.datasets import LoadedTaskDataset
from soc_agent.task_models import (
    TaskCaseDefinition,
    TaskCaseResult,
    TaskDatasetResult,
    TaskResult,
    TaskStatus,
)


class DatasetRunner:
    """Run every dataset case sequentially through an injected executor."""

    def __init__(
        self,
        execute_case: Callable[
            [Path, TaskCaseDefinition],
            TaskResult,
        ],
        stop_on_failure: bool = False,
        clock: Optional[Callable[[], float]] = None,
        sleep: Optional[Callable[[float], None]] = None,
    ):
        self.execute_case = execute_case
        self.stop_on_failure = stop_on_failure
        self._clock = clock or time.monotonic
        self._sleep = sleep or time.sleep

    def run(self, loaded_dataset: LoadedTaskDataset) -> TaskDatasetResult:
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
                    task_result = self.execute_case(
                        loaded_dataset.task_path,
                        case,
                    )
                except Exception as error:
                    case_finished_at = datetime.now(timezone.utc)
                    task_result = TaskResult(
                        task_name=loaded_dataset.task_path.stem,
                        status=TaskStatus.FAILED,
                        started_at=case_started_at,
                        finished_at=case_finished_at,
                        duration_seconds=0.0,
                        error=str(error),
                    )

                if (
                    task_result.status != TaskStatus.FAILED
                    or attempt == case.attempts
                ):
                    break
                self._sleep(case.retry_delay_seconds)

            case_duration = max(
                0.0,
                self._clock() - case_start_time,
            )

            case_results.append(
                TaskCaseResult(
                    name=case.name,
                    parameters=case.parameters,
                    attempts=attempts_used,
                    status=task_result.status,
                    duration_seconds=case_duration,
                    task_result=task_result,
                    error=task_result.error,
                )
            )

            if (
                self.stop_on_failure
                and task_result.status != TaskStatus.PASSED
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
