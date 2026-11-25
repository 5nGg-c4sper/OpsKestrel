"""Execute queue jobs and persist their terminal states."""

import os
import socket
import threading
import uuid
from typing import Callable, List, Optional, Union

from soc_agent.queue_models import QueueJob, QueueState
from soc_agent.queue_store import QueueStoreError, SQLiteQueueStore
from soc_agent.task_models import TaskResult, TaskStatus, WorkflowResult


ExecutionResult = Union[TaskResult, WorkflowResult]


class QueueWorker:
    """Claim queued jobs sequentially and record their outcomes."""

    def __init__(
        self,
        store: SQLiteQueueStore,
        execute_job: Callable[[QueueJob], ExecutionResult],
        stale_after_seconds: float = 3600,
        max_attempts: int = 3,
        worker_id: Optional[str] = None,
        heartbeat_interval_seconds: Optional[float] = None,
    ):
        if stale_after_seconds <= 0:
            raise ValueError("stale_after_seconds must be greater than 0")
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        heartbeat_interval_seconds = (
            heartbeat_interval_seconds
            if heartbeat_interval_seconds is not None
            else max(0.1, stale_after_seconds / 3)
        )
        if heartbeat_interval_seconds <= 0:
            raise ValueError(
                "heartbeat_interval_seconds must be greater than 0"
            )

        self.store = store
        self.execute_job = execute_job
        self.stale_after_seconds = stale_after_seconds
        self.max_attempts = max_attempts
        self.worker_id = worker_id or (
            f"{socket.gethostname()}:{os.getpid()}:"
            f"{uuid.uuid4().hex[:8]}"
        )
        self.heartbeat_interval_seconds = heartbeat_interval_seconds

    def run_once(self) -> Optional[QueueJob]:
        self.store.recover_stale_jobs(
            stale_after_seconds=self.stale_after_seconds,
            max_attempts=self.max_attempts,
        )
        job = self.store.claim_next(self.worker_id)
        if job is None:
            return None

        stop_heartbeat = threading.Event()
        heartbeat_errors = []

        def heartbeat_loop():
            while not stop_heartbeat.wait(
                self.heartbeat_interval_seconds
            ):
                try:
                    self.store.heartbeat(
                        job.job_id,
                        worker_id=self.worker_id,
                    )
                except Exception as error:
                    heartbeat_errors.append(error)
                    return

        heartbeat_thread = threading.Thread(
            target=heartbeat_loop,
            daemon=True,
        )
        heartbeat_thread.start()
        try:
            result = self.execute_job(job)
        except Exception as error:
            result = None
            execution_error = error
        else:
            execution_error = None
        finally:
            stop_heartbeat.set()
            heartbeat_thread.join(timeout=2)

        try:
            if result is None:
                return self.store.complete(
                    job.job_id,
                    QueueState.FAILED,
                    error=(
                        "queue worker execution failed: "
                        f"{execution_error}"
                    ),
                    worker_id=self.worker_id,
                )

            return self.store.complete(
                job.job_id,
                self._queue_state(result.status),
                report_path=result.report_path,
                error=result.error,
                worker_id=self.worker_id,
            )
        except QueueStoreError as error:
            if heartbeat_errors:
                raise QueueStoreError(
                    f"queue worker lost job lease: {heartbeat_errors[0]}"
                ) from error
            raise

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
