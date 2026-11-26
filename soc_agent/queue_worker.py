"""Execute queue jobs and persist their terminal states."""

import os
import socket
import threading
import uuid
from concurrent.futures import (
    FIRST_COMPLETED,
    ThreadPoolExecutor,
    wait,
)
from typing import Callable, List, Optional, Union

from soc_agent.queue_backend import QueueStore, QueueStoreError
from soc_agent.queue_models import QueueJob, QueueState, WorkerState
from soc_agent.task_models import TaskResult, TaskStatus, WorkflowResult


ExecutionResult = Union[TaskResult, WorkflowResult]


class QueueWorker:
    """Claim queued jobs sequentially and record their outcomes."""

    def __init__(
        self,
        store: QueueStore,
        execute_job: Callable[[QueueJob], ExecutionResult],
        stale_after_seconds: float = 3600,
        max_attempts: int = 3,
        worker_id: Optional[str] = None,
        labels: Optional[List[str]] = None,
        heartbeat_interval_seconds: Optional[float] = None,
        max_concurrency: int = 1,
    ):
        if stale_after_seconds <= 0:
            raise ValueError("stale_after_seconds must be greater than 0")
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be at least 1")
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
        self.hostname = socket.gethostname()
        self.pid = os.getpid()
        self.labels = [
            label.strip() for label in (labels or [])
        ]
        if any(not label for label in self.labels):
            raise ValueError("worker labels must not be empty")
        self.heartbeat_interval_seconds = heartbeat_interval_seconds
        self.max_concurrency = max_concurrency

    def run_once(self) -> Optional[QueueJob]:
        self.store.register_worker(
            self.worker_id,
            self.hostname,
            self.pid,
            labels=self.labels,
            max_concurrency=self.max_concurrency,
        )
        self.store.recover_stale_jobs(
            stale_after_seconds=self.stale_after_seconds,
            max_attempts=self.max_attempts,
        )
        job = self.store.claim_next(
            self.worker_id,
            worker_labels=self.labels,
        )
        if job is None:
            self.store.mark_worker_offline(self.worker_id)
            return None

        return self._execute_claimed(job, self.worker_id)

    def _execute_claimed(
        self,
        job: QueueJob,
        worker_id: str,
        keep_worker_online: bool = False,
    ) -> QueueJob:
        self.store.heartbeat_worker(
            worker_id,
            QueueState.RUNNING,
            current_job_id=job.job_id,
        )

        stop_heartbeat = threading.Event()
        heartbeat_errors = []

        def heartbeat_loop():
            while not stop_heartbeat.wait(
                self.heartbeat_interval_seconds
            ):
                try:
                    self.store.heartbeat(
                        job.job_id,
                        worker_id=worker_id,
                    )
                    self.store.heartbeat_worker(
                        worker_id,
                        QueueState.RUNNING,
                        current_job_id=job.job_id,
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
                completed = self.store.complete(
                    job.job_id,
                    QueueState.FAILED,
                    error=(
                        "queue worker execution failed: "
                        f"{execution_error}"
                    ),
                    worker_id=worker_id,
                )
            else:
                completed = self.store.complete(
                    job.job_id,
                    self._queue_state(result.status),
                    report_path=result.report_path,
                    error=result.error,
                    worker_id=worker_id,
                )
        except QueueStoreError as error:
            if heartbeat_errors:
                raise QueueStoreError(
                    f"queue worker lost job lease: {heartbeat_errors[0]}"
                ) from error
            raise
        finally:
            if keep_worker_online:
                self.store.heartbeat_worker(
                    worker_id,
                    WorkerState.IDLE,
                )
            else:
                self.store.mark_worker_offline(worker_id)

        return completed

    def run_until_empty(
        self,
        max_jobs: Optional[int] = None,
    ) -> List[QueueJob]:
        if max_jobs is not None and max_jobs < 1:
            raise ValueError("max_jobs must be at least 1")
        if self.max_concurrency > 1:
            return self._run_until_empty_concurrent(max_jobs)

        completed_jobs = []
        while max_jobs is None or len(completed_jobs) < max_jobs:
            completed = self.run_once()
            if completed is None:
                break
            completed_jobs.append(completed)
        return completed_jobs

    def run_forever(
        self,
        poll_interval_seconds: float = 2.0,
        stop_event: Optional[threading.Event] = None,
    ) -> List[QueueJob]:
        if poll_interval_seconds <= 0:
            raise ValueError(
                "poll_interval_seconds must be greater than 0"
            )
        stop_event = stop_event or threading.Event()
        completed_jobs = []
        self.store.register_worker(
            self.worker_id,
            self.hostname,
            self.pid,
            labels=self.labels,
            max_concurrency=self.max_concurrency,
        )

        try:
            while not stop_event.is_set():
                self.store.recover_stale_jobs(
                    stale_after_seconds=self.stale_after_seconds,
                    max_attempts=self.max_attempts,
                )

                if self.max_concurrency > 1:
                    batch = self._run_until_empty_concurrent(
                        max_jobs=self.max_concurrency
                    )
                    completed_jobs.extend(batch)
                    had_jobs = bool(batch)
                else:
                    job = self.store.claim_next(
                        self.worker_id,
                        worker_labels=self.labels,
                    )
                    if job is not None:
                        completed_jobs.append(
                            self._execute_claimed(
                                job,
                                self.worker_id,
                                keep_worker_online=True,
                            )
                        )
                        had_jobs = True
                    else:
                        had_jobs = False

                if stop_event.is_set():
                    break
                if not had_jobs:
                    self.store.heartbeat_worker(
                        self.worker_id,
                        WorkerState.IDLE,
                    )
                    stop_event.wait(poll_interval_seconds)
        finally:
            self.store.mark_worker_offline(self.worker_id)

        return completed_jobs

    def _run_until_empty_concurrent(
        self,
        max_jobs: Optional[int],
    ) -> List[QueueJob]:
        self.store.recover_stale_jobs(
            stale_after_seconds=self.stale_after_seconds,
            max_attempts=self.max_attempts,
        )
        completed_jobs = []
        active = {}
        slot_index = 0

        with ThreadPoolExecutor(
            max_workers=self.max_concurrency
        ) as executor:
            while max_jobs is None or len(completed_jobs) < max_jobs:
                while (
                    (
                        max_jobs is None
                        or len(active) + len(completed_jobs) < max_jobs
                    )
                    and len(active) < self.max_concurrency
                ):
                    slot_index += 1
                    slot_id = f"{self.worker_id}#slot-{slot_index}"
                    self.store.register_worker(
                        slot_id,
                        self.hostname,
                        self.pid,
                        labels=self.labels,
                        max_concurrency=1,
                    )
                    job = self.store.claim_next(
                        slot_id,
                        worker_labels=self.labels,
                    )
                    if job is None:
                        self.store.mark_worker_offline(slot_id)
                        break
                    future = executor.submit(
                        self._execute_claimed,
                        job,
                        slot_id,
                    )
                    active[future] = job.job_id

                if not active:
                    break

                done, _ = wait(
                    active,
                    return_when=FIRST_COMPLETED,
                )
                for future in done:
                    active.pop(future)
                    completed_jobs.append(future.result())
                    if (
                        max_jobs is not None
                        and len(completed_jobs) >= max_jobs
                    ):
                        break
                if (
                    max_jobs is not None
                    and len(completed_jobs) >= max_jobs
                ):
                    break

        return completed_jobs

    @staticmethod
    def _queue_state(status: TaskStatus) -> QueueState:
        return {
            TaskStatus.PASSED: QueueState.PASSED,
            TaskStatus.FAILED: QueueState.FAILED,
            TaskStatus.TIMED_OUT: QueueState.TIMED_OUT,
            TaskStatus.CANCELLED: QueueState.CANCELLED,
        }[status]
