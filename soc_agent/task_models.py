"""Data models for task definitions, steps, and execution results."""

import math
import re
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional

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


class TaskParameterDefinition(StrictModel):
    description: str = ""
    default: Optional[str] = None


class TaskDefinition(StrictModel):
    schema_version: int = Field(default=1, ge=1)
    name: str
    description: str = ""
    app: Optional[str] = None
    parameters: Dict[str, TaskParameterDefinition] = Field(
        default_factory=dict
    )

    max_steps: int = Field(default=20, ge=1, le=100)
    max_duration_seconds: float = Field(default=120.0, gt=0, le=3600)
    steps: List[TaskStep] = Field(min_length=1)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value):
        if not value.strip():
            raise ValueError("must not be empty")
        return value

    @field_validator("parameters")
    @classmethod
    def validate_parameter_names(cls, value):
        invalid_names = [
            name
            for name in value
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name)
        ]
        if invalid_names:
            raise ValueError(
                f"invalid parameter names: {', '.join(invalid_names)}"
            )
        return value

    def resolve_parameters(
        self,
        overrides: Optional[Dict[str, str]] = None,
    ) -> Dict[str, str]:
        """Apply defaults and validate task parameter overrides."""
        overrides = dict(overrides or {})

        unknown_names = sorted(set(overrides) - set(self.parameters))
        if unknown_names:
            raise ValueError(
                f"unknown task parameters: {', '.join(unknown_names)}"
            )

        invalid_values = sorted(
            name
            for name, value in overrides.items()
            if not isinstance(value, str)
        )
        if invalid_values:
            raise ValueError(
                "task parameter overrides must be strings: "
                f"{', '.join(invalid_values)}"
            )

        resolved = {
            name: definition.default
            for name, definition in self.parameters.items()
            if definition.default is not None
        }
        resolved.update(overrides)

        missing_names = [
            name
            for name, definition in self.parameters.items()
            if definition.default is None and name not in resolved
        ]
        if missing_names:
            raise ValueError(
                f"missing task parameters: {', '.join(missing_names)}"
            )

        return resolved

    def render_parameters(
        self,
        values: Dict[str, str],
    ) -> "TaskDefinition":
        """Return a copy with task parameter placeholders substituted."""
        values = dict(values)
        invalid_values = sorted(
            name
            for name, value in values.items()
            if not isinstance(value, str)
        )
        if invalid_values:
            raise ValueError(
                "task parameter values must be strings: "
                f"{', '.join(invalid_values)}"
            )

        placeholder_pattern = re.compile(r"\$\{([^{}]*)\}")

        def render_text(text: str) -> str:
            rendered = placeholder_pattern.sub(
                lambda match: values.get(match.group(1), match.group(0)),
                text,
            )
            unresolved_names = sorted(
                {
                    match.group(1) or "<empty>"
                    for match in placeholder_pattern.finditer(rendered)
                }
            )
            if unresolved_names:
                raise ValueError(
                    "unresolved task parameters: "
                    f"{', '.join(unresolved_names)}"
                )
            return rendered

        data = self.model_dump()
        if data["app"] is not None:
            data["app"] = render_text(data["app"])

        for step in data["steps"]:
            for field_name in ("app", "content", "prompt", "summary"):
                if step[field_name] is not None:
                    step[field_name] = render_text(step[field_name])

            if step["keys"] is not None:
                step["keys"] = [
                    render_text(key)
                    for key in step["keys"]
                ]

        return TaskDefinition.model_validate(data)

    @model_validator(mode="after")
    def validate_step_count(self):
        if len(self.steps) > self.max_steps:
            raise ValueError(
                f"task has {len(self.steps)} steps, "
                f"but max_steps is {self.max_steps}"
            )
        return self


class TaskCaseDefinition(StrictModel):
    name: str
    parameters: Dict[str, str] = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value):
        if not value.strip():
            raise ValueError("must not be empty")
        return value

    @field_validator("parameters")
    @classmethod
    def validate_parameter_names(cls, value):
        invalid_names = [
            name
            for name in value
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name)
        ]
        if invalid_names:
            raise ValueError(
                f"invalid parameter names: {', '.join(invalid_names)}"
            )
        return value


class TaskDatasetDefinition(StrictModel):
    name: str
    task: str
    cases: List[TaskCaseDefinition] = Field(min_length=1)

    @field_validator("name", "task")
    @classmethod
    def validate_non_empty_text(cls, value):
        if not value.strip():
            raise ValueError("must not be empty")
        return value

    @model_validator(mode="after")
    def validate_unique_case_names(self):
        seen_names = set()
        duplicate_names = []
        for case in self.cases:
            if case.name in seen_names and case.name not in duplicate_names:
                duplicate_names.append(case.name)
            seen_names.add(case.name)

        if duplicate_names:
            raise ValueError(
                f"duplicate case names: {', '.join(duplicate_names)}"
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
