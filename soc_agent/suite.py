"""Sequential execution of multiple task files."""

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, List, Optional

from soc_agent.task_models import TaskResult, TaskStatus


@dataclass
class SuiteResult:
    """Aggregated outcome for a task suite."""

    results: List[TaskResult]
    started_at: datetime
    finished_at: datetime
    duration_seconds: float
    stopped_early: bool = False
    report_path: Optional[str] = None

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def passed(self) -> int:
        return sum(
            result.status == TaskStatus.PASSED for result in self.results
        )

    @property
    def failed(self) -> int:
        return sum(
            result.status == TaskStatus.FAILED for result in self.results
        )

    @property
    def timed_out(self) -> int:
        return sum(
            result.status == TaskStatus.TIMED_OUT for result in self.results
        )

    @property
    def cancelled(self) -> int:
        return sum(
            result.status == TaskStatus.CANCELLED for result in self.results
        )

    @property
    def successful(self) -> bool:
        return self.passed == self.total


class SuiteRunner:
    """Run task files sequentially through an injected executor."""

    def __init__(
        self,
        execute_task: Callable[[Path], TaskResult],
        stop_on_failure: bool = False,
        clock: Optional[Callable[[], float]] = None,
    ):
        self.execute_task = execute_task
        self.stop_on_failure = stop_on_failure
        self._clock = clock or time.monotonic

    def run(self, suite_path) -> SuiteResult:
        tasks = self.discover_tasks(suite_path)
        started_at = datetime.now(timezone.utc)
        started_clock = self._clock()
        results = []
        stopped_early = False

        for task_path in tasks:
            try:
                result = self.execute_task(task_path)
            except Exception as error:
                now = datetime.now(timezone.utc)
                result = TaskResult(
                    task_name=task_path.stem,
                    status=TaskStatus.FAILED,
                    started_at=now,
                    finished_at=now,
                    duration_seconds=0.0,
                    error=str(error),
                )

            results.append(result)
            if self.stop_on_failure and result.status != TaskStatus.PASSED:
                stopped_early = True
                break

        finished_at = datetime.now(timezone.utc)

        return SuiteResult(
            results=results,
            started_at=started_at,
            finished_at=finished_at,
            duration_seconds=max(0.0, self._clock() - started_clock),
            stopped_early=stopped_early,
        )

    @staticmethod
    def discover_tasks(suite_path) -> List[Path]:
        path = Path(suite_path)
        if path.is_file():
            return [path]
        if not path.is_dir():
            raise FileNotFoundError(f"suite path does not exist: {suite_path}")

        tasks = sorted(path.glob("*.json"), key=lambda item: item.name)
        if not tasks:
            raise FileNotFoundError(f"no JSON tasks found in: {suite_path}")
        return tasks
