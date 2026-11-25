"""Execute queue jobs and persist their terminal states."""

from typing import Callable, List, Optional, Union

from soc_agent.queue_models import QueueJob, QueueState
from soc_agent.queue_store import SQLiteQueueStore
from soc_agent.task_models import TaskResult, TaskStatus, WorkflowResult


ExecutionResult = Union[TaskResult, WorkflowResult]


class QueueWorker:
    """Claim queued jobs sequentially and record their outcomes."""

    def __init__(
        self,
        store: SQLiteQueueStore,
        execute_job: Callable[[QueueJob], ExecutionResult],
    ):
        self.store = store
        self.execute_job = execute_job

    def run_once(self) -> Optional[QueueJob]:
        job = self.store.claim_next()
        if job is None:
            return None

        try:
            result = self.execute_job(job)
        except Exception as error:
            return self.store.complete(
                job.job_id,
                QueueState.FAILED,
                error=f"queue worker execution failed: {error}",
            )

        return self.store.complete(
            job.job_id,
            self._queue_state(result.status),
            report_path=result.report_path,
            error=result.error,
        )

    def run_until_empty(
        self,
        max_jobs: Optional[int] = None,
    ) -> List[QueueJob]:
        if max_jobs is not None and max_jobs < 1:
            raise ValueError("max_jobs must be at least 1")

        completed_jobs = []
        while max_jobs is None or len(completed_jobs) < max_jobs:
            completed = self.run_once()
            if completed is None:
                break
            completed_jobs.append(completed)
        return completed_jobs

    @staticmethod
    def _queue_state(status: TaskStatus) -> QueueState:
        return {
            TaskStatus.PASSED: QueueState.PASSED,
            TaskStatus.FAILED: QueueState.FAILED,
            TaskStatus.TIMED_OUT: QueueState.TIMED_OUT,
            TaskStatus.CANCELLED: QueueState.CANCELLED,
        }[status]
