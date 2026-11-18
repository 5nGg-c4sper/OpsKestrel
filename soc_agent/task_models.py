"""Data models for task definitions, steps, and execution results."""

import math
from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    """Base model that rejects unknown fields."""

    model_config = ConfigDict(extra="forbid")


class ActionType(str, Enum):
    OPEN_APP = "open_app"
    WRITE = "write"
    PRESS = "press"
    CLICK = "click"
    WAIT = "wait"
    VERIFY_VISION = "verify_vision"
    DONE = "done"


class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"


class TaskStatus(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"


class TaskStep(StrictModel):
    type: ActionType

    app: Optional[str] = None
    content: Optional[str] = None
    keys: Optional[List[str]] = None

    x: Optional[float] = None
    y: Optional[float] = None

    prompt: Optional[str] = None
    summary: Optional[str] = None

    seconds: Optional[float] = Field(default=None, gt=0)
    timeout_seconds: float = Field(default=30.0, gt=0, le=300)

    requires_confirmation: bool = False

    @field_validator("app", "content", "prompt")
    @classmethod
    def validate_non_empty_text(cls, value):
        if value is not None and not value.strip():
            raise ValueError("must not be empty")
        return value

    @field_validator("keys")
    @classmethod
    def validate_keys(cls, value):
        if value is not None:
            if not value:
                raise ValueError("must contain at least one key")
            if any(not key.strip() for key in value):
                raise ValueError("keys must not contain empty values")
        return value

    @field_validator("x", "y")
    @classmethod
    def validate_coordinate(cls, value):
        if value is None:
            return value
        if not math.isfinite(value):
            raise ValueError("must be a finite number")
        if not 0 <= value <= 1:
            raise ValueError("must be between 0 and 1")
        return value

    @model_validator(mode="after")
    def validate_action_fields(self):
        if self.type == ActionType.OPEN_APP and not self.app:
            raise ValueError("open_app requires app")

        if self.type == ActionType.WRITE and self.content is None:
            raise ValueError("write requires content")

        if self.type == ActionType.PRESS and not self.keys:
            raise ValueError("press requires keys")

        if self.type == ActionType.CLICK:
            if self.x is None or self.y is None:
                raise ValueError("click requires x and y")

        if self.type == ActionType.WAIT and self.seconds is None:
            raise ValueError("wait requires seconds")

        if self.type == ActionType.VERIFY_VISION and not self.prompt:
            raise ValueError("verify_vision requires prompt")

        return self


class TaskDefinition(StrictModel):
    schema_version: int = Field(default=1, ge=1)
    name: str
    description: str = ""
    app: Optional[str] = None

    max_steps: int = Field(default=20, ge=1, le=100)
    max_duration_seconds: float = Field(default=120.0, gt=0, le=3600)
    steps: List[TaskStep] = Field(min_length=1)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value):
        if not value.strip():
            raise ValueError("must not be empty")
        return value

    @model_validator(mode="after")
    def validate_step_count(self):
        if len(self.steps) > self.max_steps:
            raise ValueError(
                f"task has {len(self.steps)} steps, "
                f"but max_steps is {self.max_steps}"
            )
        return self


class StepResult(StrictModel):
    index: int = Field(ge=0)
    type: ActionType
    status: StepStatus

    started_at: datetime
    finished_at: Optional[datetime] = None
    duration_seconds: float = Field(default=0.0, ge=0)

    error: Optional[str] = None
    screenshot: Optional[str] = None


class TaskResult(StrictModel):
    task_name: str
    status: TaskStatus

    started_at: datetime
    finished_at: Optional[datetime] = None
    duration_seconds: float = Field(default=0.0, ge=0)

    steps: List[StepResult] = Field(default_factory=list)
    error: Optional[str] = None
    report_path: Optional[str] = None
