"""Queue storage interfaces and backend factory."""

from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional, Union

from soc_agent.queue_models import (
    QueueJob,
    QueueState,
    QueueWorkerRecord,
    WorkerState,
)
from soc_agent.task_models import DatasetTargetType, ExecutionPermissions


class QueueStoreError(RuntimeError):
    """Raised when a queue operation cannot be completed."""


class QueueStoreBackendError(ValueError):
    """Raised when a queue backend URL cannot be configured."""


class QueueStore(ABC):
    """Storage interface used by queue commands and workers."""

    @abstractmethod
    def enqueue(
        self,
        target_type: DatasetTargetType,
        target_path: Union[str, Path],
        parameters: Optional[Dict[str, str]] = None,
        permissions: Optional[ExecutionPermissions] = None,
        required_labels: Optional[List[str]] = None,
        parallel_safe: bool = False,
        priority: int = 0,
        job_id: Optional[str] = None,
    ) -> QueueJob:
        raise NotImplementedError

    @abstractmethod
    def get(self, job_id: str) -> QueueJob:
        raise NotImplementedError

    @abstractmethod
    def list_jobs(
        self,
        state: Optional[QueueState] = None,
    ) -> List[QueueJob]:
        raise NotImplementedError

    @abstractmethod
    def claim_next(
        self,
        worker_id: str = "local",
        worker_labels: Optional[List[str]] = None,
    ) -> Optional[QueueJob]:
        raise NotImplementedError

    @abstractmethod
    def heartbeat(
        self,
        job_id: str,
        worker_id: Optional[str] = None,
    ) -> QueueJob:
        raise NotImplementedError

    @abstractmethod
    def recover_stale_jobs(
        self,
        stale_after_seconds: float,
        max_attempts: int = 3,
    ) -> List[QueueJob]:
        raise NotImplementedError

    @abstractmethod
    def complete(
        self,
        job_id: str,
        state: QueueState,
        report_path: Optional[str] = None,
        error: Optional[str] = None,
        worker_id: Optional[str] = None,
    ) -> QueueJob:
        raise NotImplementedError

    @abstractmethod
    def register_worker(
        self,
        worker_id: str,
        hostname: str,
        pid: int,
        labels: Optional[List[str]] = None,
        max_concurrency: int = 1,
    ) -> QueueWorkerRecord:
        raise NotImplementedError

    @abstractmethod
    def heartbeat_worker(
        self,
        worker_id: str,
        state: WorkerState,
        current_job_id: Optional[str] = None,
    ) -> QueueWorkerRecord:
        raise NotImplementedError

    @abstractmethod
    def mark_worker_offline(
        self,
        worker_id: str,
    ) -> QueueWorkerRecord:
        raise NotImplementedError

    @abstractmethod
    def get_worker(self, worker_id: str) -> QueueWorkerRecord:
        raise NotImplementedError

    @abstractmethod
    def list_workers(
        self,
        online_within_seconds: Optional[float] = None,
    ) -> List[QueueWorkerRecord]:
        raise NotImplementedError


def create_queue_store(
    location: Union[str, Path] = "reports/queue.db",
    clock: Optional[Callable[[], datetime]] = None,
) -> QueueStore:
    """Create a queue backend from a path or supported URL."""
    backend = str(location)
    if backend.startswith("sqlite:///"):
        backend = backend[len("sqlite:///"):]
    elif backend.startswith(("postgresql://", "postgres://")):
        from soc_agent.postgres_queue_store import PostgreSQLQueueStore

        return PostgreSQLQueueStore(backend, clock=clock)
    elif "://" in backend:
        scheme = backend.split("://", 1)[0]
        raise QueueStoreBackendError(
            f"unsupported queue backend: {scheme}"
        )

    from soc_agent.queue_store import SQLiteQueueStore

    return SQLiteQueueStore(backend, clock=clock)
