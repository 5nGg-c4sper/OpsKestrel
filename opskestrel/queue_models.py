"""Data models for persistent task queue jobs."""

import re
from enum import Enum
from datetime import datetime
from typing import Dict, List, Optional

from pydantic import Field, field_validator

from opskestrel.task_models import (
    DatasetTargetType,
    ExecutionPermissions,
    StrictModel,
)


class QueueState(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"


class WorkerState(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    OFFLINE = "offline"


TERMINAL_QUEUE_STATES = frozenset(
    {
        QueueState.PASSED,
        QueueState.FAILED,
        QueueState.TIMED_OUT,
        QueueState.CANCELLED,
    }
)


class QueueJob(StrictModel):
    job_id: str
    target_type: DatasetTargetType
    target_path: str
    parameters: Dict[str, str] = Field(default_factory=dict)
    state: QueueState = QueueState.PENDING
    priority: int = 0
    permissions: ExecutionPermissions = Field(
        default_factory=ExecutionPermissions
    )
    required_labels: List[str] = Field(default_factory=list)
    parallel_safe: bool = False

    created_at: datetime
    updated_at: datetime
    started_at: Optional[datetime] = None
    claimed_at: Optional[datetime] = None
    worker_id: Optional[str] = None
    finished_at: Optional[datetime] = None
    attempts: int = 0
    recovery_count: int = 0

    report_path: Optional[str] = None
    error: Optional[str] = None

    @field_validator("job_id", "target_path")
    @classmethod
    def validate_non_empty_text(cls, value):
        if not value.strip():
            raise ValueError("must not be empty")
        return value

    @field_validator("parameters")
    @classmethod
    def validate_parameters(cls, value):
        invalid_names = [
            name
            for name in value
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name)
        ]
        if invalid_names:
            raise ValueError(
                f"invalid parameter names: {', '.join(invalid_names)}"
            )
        if any(not isinstance(item, str) for item in value.values()):
            raise ValueError("queue parameter values must be strings")
        return value

    @field_validator("required_labels")
    @classmethod
    def validate_required_labels(cls, value):
        return _normalize_labels(value, "required labels")

    @property
    def terminal(self) -> bool:
        return self.state in TERMINAL_QUEUE_STATES


class QueueWorkerRecord(StrictModel):
    worker_id: str
    hostname: str
    pid: int = Field(ge=1)
    state: WorkerState = WorkerState.IDLE
    current_job_id: Optional[str] = None
    labels: List[str] = Field(default_factory=list)
    max_concurrency: int = Field(default=1, ge=1)

    started_at: datetime
    last_heartbeat: datetime
    stopped_at: Optional[datetime] = None

    @field_validator("worker_id", "hostname")
    @classmethod
    def validate_non_empty_text(cls, value):
        if not value.strip():
            raise ValueError("must not be empty")
        return value

    @field_validator("labels")
    @classmethod
    def validate_labels(cls, value):
        return _normalize_labels(value, "worker labels")


def _normalize_labels(values, label_name):
    labels = [value.strip() for value in (values or [])]
    if any(not label for label in labels):
        raise ValueError(f"{label_name} must not be empty")
    normalized = [label.casefold() for label in labels]
    if len(set(normalized)) != len(normalized):
        raise ValueError(f"{label_name} must be unique")
    return labels
