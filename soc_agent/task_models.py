"""Data models for task definitions, steps, and execution results."""

import math
import re
from datetime import datetime
from enum import Enum
from typing import Dict, List, Literal, Optional, Set

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    """Base model that rejects unknown fields."""

    model_config = ConfigDict(extra="forbid")


class ActionType(str, Enum):
    OPEN_APP = "open_app"
    ACTIVATE_APP = "activate_app"
    CLOSE_DOCUMENT = "close_document"
    APPROVAL = "approval"
    WRITE = "write"
    PRESS = "press"
    CLICK = "click"
    CLICK_ELEMENT = "click_element"
    READ_ELEMENT = "read_element"
    WAIT = "wait"
    VERIFY_VISION = "verify_vision"
    DONE = "done"


class ConditionType(str, Enum):
    VISION = "vision"


class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"


class StepPhase(str, Enum):
    SETUP = "setup"
    MAIN = "main"
    CLEANUP = "cleanup"


class TaskStatus(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"


class DatasetTargetType(str, Enum):
    TASK = "task"
    WORKFLOW = "workflow"


class UIElementLocator(StrictModel):
    role: Optional[str] = None
    text: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    value: Optional[str] = None
    match_index: int = Field(default=0, ge=0)

    @field_validator("role", "text", "title", "description", "value")
    @classmethod
    def validate_non_empty_text(cls, value):
        if value is not None and not value.strip():
            raise ValueError("must not be empty")
        return value

    @model_validator(mode="after")
    def validate_has_criterion(self):
        if all(
            value is None
            for value in (
                self.role,
                self.text,
                self.title,
                self.description,
                self.value,
            )
        ):
            raise ValueError(
                "UI element locator requires at least one criterion"
            )
        return self


class TaskStep(StrictModel):
    type: ActionType

    app: Optional[str] = None
    content: Optional[str] = None
    keys: Optional[List[str]] = None

    x: Optional[float] = None
    y: Optional[float] = None
    element: Optional[UIElementLocator] = None
    output: Optional[str] = None
    read_attribute: Literal["title", "description", "value"] = "value"
    sensitive_output: bool = False

    prompt: Optional[str] = None
    summary: Optional[str] = None
    expected_vision_result: bool = True
    condition: Optional["TaskCondition"] = None
    loop: Optional["TaskLoop"] = None

    seconds: Optional[float] = Field(default=None, gt=0)
    timeout_seconds: float = Field(default=30.0, gt=0, le=300)
    verification_attempts: int = Field(default=1, ge=1, le=5)
    verification_retry_delay_seconds: float = Field(
        default=0.5,
        ge=0,
        le=10,
    )

    requires_confirmation: bool = False
    save_changes: bool = False

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

        if self.type == ActionType.ACTIVATE_APP and not self.app:
            raise ValueError("activate_app requires app")

        if self.type == ActionType.CLOSE_DOCUMENT and not self.app:
            raise ValueError("close_document requires app")

        if self.type == ActionType.APPROVAL and not self.prompt:
            raise ValueError("approval requires prompt")

        if self.type == ActionType.WRITE and self.content is None:
            raise ValueError("write requires content")

        if self.type == ActionType.PRESS and not self.keys:
            raise ValueError("press requires keys")

        if self.type == ActionType.CLICK:
            if self.x is None or self.y is None:
                raise ValueError("click requires x and y")

        if self.type == ActionType.CLICK_ELEMENT:
            if not self.app:
                raise ValueError("click_element requires app")
            if self.element is None:
                raise ValueError("click_element requires element")

        if self.type == ActionType.READ_ELEMENT:
            if not self.app:
                raise ValueError("read_element requires app")
            if self.element is None:
                raise ValueError("read_element requires element")
            if self.output is not None and not re.fullmatch(
                r"[A-Za-z_][A-Za-z0-9_]*",
                self.output,
            ):
                raise ValueError("read_element output has an invalid name")

        if self.type == ActionType.WAIT and self.seconds is None:
            raise ValueError("wait requires seconds")

        if self.type == ActionType.VERIFY_VISION and not self.prompt:
            raise ValueError("verify_vision requires prompt")

        if self.loop is not None and self.type in {
            ActionType.VERIFY_VISION,
            ActionType.DONE,
        }:
            raise ValueError(
                f"loop is not supported for {self.type.value}"
            )

        return self


class TaskParameterDefinition(StrictModel):
    description: str = ""
    default: Optional[str] = None


class ExecutionPermissions(StrictModel):
    allowed_apps: Optional[List[str]] = None
    allowed_actions: Optional[List[ActionType]] = None

    @field_validator("allowed_apps")
    @classmethod
    def validate_allowed_apps(cls, value):
        if value is not None and any(not app.strip() for app in value):
            raise ValueError("allowed apps must not be empty")
        return value

    @field_validator("allowed_actions")
    @classmethod
    def validate_allowed_actions(cls, value):
        if value is not None and len(set(value)) != len(value):
            raise ValueError("allowed actions must be unique")
        return value


class TaskCondition(StrictModel):
    type: ConditionType
    prompt: str

    expected: bool = True
    attempts: int = Field(default=1, ge=1, le=5)
    retry_delay_seconds: float = Field(default=0.5, ge=0, le=10)

    @field_validator("prompt")
    @classmethod
    def validate_prompt(cls, value):
        if not value.strip():
            raise ValueError("must not be empty")
        return value


class TaskLoop(StrictModel):
    count: int = Field(ge=1, le=20)
    delay_seconds: float = Field(default=0.0, ge=0, le=10)


class RedactionRegion(StrictModel):
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    width: float = Field(gt=0, le=1)
    height: float = Field(gt=0, le=1)

    @model_validator(mode="after")
    def validate_bounds(self):
        if self.x + self.width > 1:
            raise ValueError("redaction region exceeds image width")
        if self.y + self.height > 1:
            raise ValueError("redaction region exceeds image height")
        return self


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
    setup_steps: List[TaskStep] = Field(default_factory=list)
    steps: List[TaskStep] = Field(min_length=1)
    cleanup_steps: List[TaskStep] = Field(default_factory=list)
    redaction_regions: List[RedactionRegion] = Field(
        default_factory=list
    )

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
        preserve_placeholders: Optional[Set[str]] = None,
    ) -> "TaskDefinition":
        """Return a copy with task parameter placeholders substituted."""
        values = dict(values)
        preserve_placeholders = set(preserve_placeholders or set())
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
                    if match.group(1) not in preserve_placeholders
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

        all_steps = (
            data["setup_steps"]
            + data["steps"]
            + data["cleanup_steps"]
        )
        for step in all_steps:
            for field_name in ("app", "content", "prompt", "summary"):
                if step[field_name] is not None:
                    step[field_name] = render_text(step[field_name])

            if step["keys"] is not None:
                step["keys"] = [
                    render_text(key)
                    for key in step["keys"]
                ]

            condition = step["condition"]
            if condition is not None:
                condition["prompt"] = render_text(condition["prompt"])

            element = step["element"]
            if element is not None:
                for field_name in (
                    "role",
                    "text",
                    "title",
                    "description",
                    "value",
                ):
                    if element[field_name] is not None:
                        element[field_name] = render_text(
                            element[field_name]
                        )

        return TaskDefinition.model_validate(data)

    @model_validator(mode="after")
    def validate_step_count(self):
        total_steps = (
            len(self.setup_steps)
            + len(self.steps)
            + len(self.cleanup_steps)
        )
        if total_steps > self.max_steps:
            raise ValueError(
                f"task has {total_steps} steps, "
                f"but max_steps is {self.max_steps}"
            )
        if any(
            step.type == ActionType.DONE
            for step in self.setup_steps + self.cleanup_steps
        ):
            raise ValueError(
                "done is only supported in main steps"
            )

        runtime_outputs = [
            step.output
            for step in (
                self.setup_steps + self.steps + self.cleanup_steps
            )
            if step.output is not None
        ]
        duplicate_outputs = sorted(
            {
                name
                for name in runtime_outputs
                if runtime_outputs.count(name) > 1
            }
        )
        if duplicate_outputs:
            raise ValueError(
                "duplicate runtime outputs: "
                f"{', '.join(duplicate_outputs)}"
            )
        conflicting_outputs = sorted(
            set(runtime_outputs) & set(self.parameters)
        )
        if conflicting_outputs:
            raise ValueError(
                "runtime outputs conflict with task parameters: "
                f"{', '.join(conflicting_outputs)}"
            )
        return self


class TaskCaseDefinition(StrictModel):
    name: str
    parameters: Dict[str, str] = Field(default_factory=dict)
    attempts: int = Field(default=1, ge=1, le=3)
    retry_delay_seconds: float = Field(default=0.5, ge=0, le=10)

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


class TaskDatasetCSVSource(StrictModel):
    type: Literal["csv"] = "csv"
    path: str
    case_name_column: str = "case_id"
    parameters: Dict[str, str] = Field(default_factory=dict)
    attempts: int = Field(default=1, ge=1, le=3)
    retry_delay_seconds: float = Field(default=0.5, ge=0, le=10)

    @field_validator("path", "case_name_column")
    @classmethod
    def validate_non_empty_text(cls, value):
        if not value.strip():
            raise ValueError("must not be empty")
        return value

    @field_validator("parameters")
    @classmethod
    def validate_parameter_mapping(cls, value):
        invalid_names = [
            name
            for name in value
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name)
        ]
        if invalid_names:
            raise ValueError(
                f"invalid parameter names: {', '.join(invalid_names)}"
            )
        if any(not column.strip() for column in value.values()):
            raise ValueError("CSV column names must not be empty")
        return value


class TaskDatasetDefinition(StrictModel):
    name: str
    task: Optional[str] = None
    workflow: Optional[str] = None
    data_source: Optional[TaskDatasetCSVSource] = None
    cases: List[TaskCaseDefinition] = Field(default_factory=list)

    @field_validator("name", "task", "workflow")
    @classmethod
    def validate_non_empty_text(cls, value):
        if value is not None and not value.strip():
            raise ValueError("must not be empty")
        return value

    @model_validator(mode="after")
    def validate_unique_case_names(self):
        has_task = self.task is not None
        has_workflow = self.workflow is not None
        if has_task == has_workflow:
            raise ValueError(
                "dataset must define exactly one of task or workflow"
            )

        has_cases = bool(self.cases)
        has_data_source = self.data_source is not None
        if has_cases == has_data_source:
            raise ValueError(
                "dataset must define exactly one of cases or data_source"
            )

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


class WorkflowDefinition(StrictModel):
    schema_version: int = Field(default=1, ge=1)
    name: str
    description: str = ""
    parameters: Dict[str, TaskParameterDefinition] = Field(
        default_factory=dict
    )
    task_files: List[str] = Field(min_length=1)
    cleanup_task: Optional[str] = None

    @field_validator("name", "cleanup_task")
    @classmethod
    def validate_non_empty_text(cls, value):
        if value is not None and not value.strip():
            raise ValueError("must not be empty")
        return value

    @field_validator("task_files")
    @classmethod
    def validate_task_files(cls, value):
        if any(not task_file.strip() for task_file in value):
            raise ValueError("task files must not be empty")
        if len(set(value)) != len(value):
            raise ValueError("task files must be unique")
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
        """Apply workflow defaults and validate parameter overrides."""
        overrides = dict(overrides or {})

        unknown_names = sorted(set(overrides) - set(self.parameters))
        if unknown_names:
            raise ValueError(
                f"unknown workflow parameters: {', '.join(unknown_names)}"
            )

        invalid_values = sorted(
            name
            for name, value in overrides.items()
            if not isinstance(value, str)
        )
        if invalid_values:
            raise ValueError(
                "workflow parameter overrides must be strings: "
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
                f"missing workflow parameters: {', '.join(missing_names)}"
            )

        return resolved


class StepResult(StrictModel):
    index: int = Field(ge=0)
    type: ActionType
    status: StepStatus
    phase: StepPhase = StepPhase.MAIN

    started_at: datetime
    finished_at: Optional[datetime] = None
    duration_seconds: float = Field(default=0.0, ge=0)

    error: Optional[str] = None
    screenshot: Optional[str] = None
    approval_prompt: Optional[str] = None
    approval_result: Optional[bool] = None
    output: Optional[str] = None
    extracted_value: Optional[str] = None
    condition_prompt: Optional[str] = None
    condition_expected: Optional[bool] = None
    condition_actual: Optional[bool] = None
    condition_duration_seconds: Optional[float] = Field(
        default=None,
        ge=0,
    )
    condition_screenshot: Optional[str] = None

    loop_count: Optional[int] = Field(default=None, ge=1)
    loop_iterations_completed: int = Field(default=1, ge=0)
    loop_delay_seconds: Optional[float] = Field(default=None, ge=0)


class TaskResult(StrictModel):
    task_name: str
    status: TaskStatus

    started_at: datetime
    finished_at: Optional[datetime] = None
    duration_seconds: float = Field(default=0.0, ge=0)

    steps: List[StepResult] = Field(default_factory=list)
    error: Optional[str] = None
    report_path: Optional[str] = None
    failure_log: Optional[str] = None


class WorkflowTaskResult(StrictModel):
    task_name: str
    task_path: str
    phase: StepPhase
    status: TaskStatus
    parameters: Dict[str, str] = Field(default_factory=dict)

    started_at: datetime
    finished_at: datetime
    duration_seconds: float = Field(default=0.0, ge=0)

    error: Optional[str] = None
    task_result: TaskResult

    @field_validator("task_name", "task_path")
    @classmethod
    def validate_non_empty_text(cls, value):
        if not value.strip():
            raise ValueError("must not be empty")
        return value


class WorkflowResult(StrictModel):
    workflow_name: str
    status: TaskStatus

    started_at: datetime
    finished_at: datetime
    duration_seconds: float = Field(default=0.0, ge=0)

    task_results: List[WorkflowTaskResult] = Field(default_factory=list)
    cleanup_result: Optional[WorkflowTaskResult] = None
    stopped_early: bool = False
    error: Optional[str] = None
    report_path: Optional[str] = None

    @field_validator("workflow_name")
    @classmethod
    def validate_workflow_name(cls, value):
        if not value.strip():
            raise ValueError("must not be empty")
        return value

    @property
    def total(self) -> int:
        return len(self.task_results)

    @property
    def passed(self) -> int:
        return sum(
            result.status == TaskStatus.PASSED
            for result in self.task_results
        )

    @property
    def failed(self) -> int:
        return sum(
            result.status == TaskStatus.FAILED
            for result in self.task_results
        )

    @property
    def timed_out(self) -> int:
        return sum(
            result.status == TaskStatus.TIMED_OUT
            for result in self.task_results
        )

    @property
    def cancelled(self) -> int:
        return sum(
            result.status == TaskStatus.CANCELLED
            for result in self.task_results
        )

    @property
    def successful(self) -> bool:
        cleanup_passed = (
            self.cleanup_result is None
            or self.cleanup_result.status == TaskStatus.PASSED
        )
        return (
            self.total > 0
            and self.passed == self.total
            and cleanup_passed
        )


class TaskCaseResult(StrictModel):
    name: str
    parameters: Dict[str, str] = Field(default_factory=dict)
    attempts: int = Field(default=1, ge=1)
    status: TaskStatus
    duration_seconds: float = Field(default=0.0, ge=0)
    task_result: Optional[TaskResult] = None
    workflow_result: Optional[WorkflowResult] = None
    error: Optional[str] = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, value):
        if not value.strip():
            raise ValueError("must not be empty")
        return value

    @model_validator(mode="after")
    def validate_result_target(self):
        if (self.task_result is None) == (self.workflow_result is None):
            raise ValueError(
                "case must define exactly one of task_result "
                "or workflow_result"
            )
        return self

    @property
    def target_type(self) -> DatasetTargetType:
        if self.task_result is not None:
            return DatasetTargetType.TASK
        return DatasetTargetType.WORKFLOW

    @property
    def report_path(self) -> Optional[str]:
        if self.task_result is not None:
            return self.task_result.report_path
        return self.workflow_result.report_path

    @property
    def failure_log(self) -> Optional[str]:
        if self.task_result is None:
            return None
        return self.task_result.failure_log


class TaskDatasetResult(StrictModel):
    dataset_name: str
    status: TaskStatus

    started_at: datetime
    finished_at: Optional[datetime] = None
    duration_seconds: float = Field(default=0.0, ge=0)

    cases: List[TaskCaseResult] = Field(min_length=1)
    stopped_early: bool = False
    report_path: Optional[str] = None

    @field_validator("dataset_name")
    @classmethod
    def validate_dataset_name(cls, value):
        if not value.strip():
            raise ValueError("must not be empty")
        return value

    @property
    def total(self) -> int:
        return len(self.cases)

    @property
    def passed(self) -> int:
        return sum(
            case.status == TaskStatus.PASSED for case in self.cases
        )

    @property
    def failed(self) -> int:
        return sum(
            case.status == TaskStatus.FAILED for case in self.cases
        )

    @property
    def timed_out(self) -> int:
        return sum(
            case.status == TaskStatus.TIMED_OUT for case in self.cases
        )

    @property
    def cancelled(self) -> int:
        return sum(
            case.status == TaskStatus.CANCELLED for case in self.cases
        )

    @property
    def successful(self) -> bool:
        return self.passed == self.total
