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
        clock: Optional[Callable[[], float]] = None,
    ):
        self.execute_case = execute_case
        self._clock = clock or time.monotonic

    def run(self, loaded_dataset: LoadedTaskDataset) -> TaskDatasetResult:
        started_at = datetime.now(timezone.utc)
        start_time = self._clock()
        case_results = []

        for case in loaded_dataset.definition.cases:
            case_start_time = self._clock()
            task_result = self.execute_case(
                loaded_dataset.task_path,
                case,
            )
            case_duration = max(
                0.0,
                self._clock() - case_start_time,
            )
            case_results.append(
                TaskCaseResult(
                    name=case.name,
                    parameters=case.parameters,
                    status=task_result.status,
                    duration_seconds=case_duration,
                    task_result=task_result,
                    error=task_result.error,
                )
            )

        status = (
            TaskStatus.PASSED
            if all(
                result.status == TaskStatus.PASSED
                for result in case_results
            )
            else TaskStatus.FAILED
        )

        return TaskDatasetResult(
            dataset_name=loaded_dataset.definition.name,
            status=status,
            started_at=started_at,
            finished_at=datetime.now(timezone.utc),
            duration_seconds=max(0.0, self._clock() - start_time),
            cases=case_results,
        )
