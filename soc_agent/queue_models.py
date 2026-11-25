"""Data models for persistent task queue jobs."""

import re
from enum import Enum
from datetime import datetime
from typing import Dict, Optional

from pydantic import Field, field_validator

from soc_agent.task_models import (
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

    @property
    def terminal(self) -> bool:
        return self.state in TERMINAL_QUEUE_STATES
