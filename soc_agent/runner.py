"""Task execution orchestration."""

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, Optional

from soc_agent.actions.executor import ActionExecutor, StepOutcome
from soc_agent.safety.policy import SafetyPolicy, SafetyViolation
from soc_agent.task_models import (
    ActionType,
    StepResult,
    StepStatus,
    TaskDefinition,
    TaskResult,
    TaskStep,
    TaskStatus,
)


class TaskRunnerError(RuntimeError):
    """Raised when task execution cannot continue."""


class ConfirmationRejected(TaskRunnerError):
    """Raised when a user rejects a required confirmation."""


class TaskRunner:
    """Execute task steps and record their outcomes."""

    def __init__(
        self,
        executor: ActionExecutor,
        vision_verifier: Optional[Callable[[str], bool]] = None,
        confirmation_handler: Optional[Callable[[object], bool]] = None,
        artifact_provider: Optional[
            Callable[[int, TaskStep, StepStatus], Optional[str]]
        ] = None,
        policy: Optional[SafetyPolicy] = None,
        clock: Optional[Callable[[], float]] = None,
    ):
        self.executor = executor
        self.vision_verifier = vision_verifier
        self.confirmation_handler = confirmation_handler
        self.artifact_provider = artifact_provider
        self.policy = policy
        self._clock = clock or time.monotonic

    @staticmethod
    def load_task(
        task_path,
        parameter_overrides: Optional[Dict[str, str]] = None,
    ) -> TaskDefinition:
        path = Path(task_path)
        payload = json.loads(path.read_text(encoding="utf-8"))
        task = TaskDefinition.model_validate(payload)
        resolved = task.resolve_parameters(parameter_overrides)
        return task.render_parameters(resolved)

    def run(self, task: TaskDefinition) -> TaskResult:
        started_at = datetime.now(timezone.utc)
        start_time = self._clock()
        step_results = []

        status = TaskStatus.PASSED
        task_error = None

        for index, step in enumerate(task.steps):
            if self._clock() - start_time > task.max_duration_seconds:
                status = TaskStatus.TIMED_OUT
                task_error = (
                    f"task exceeded {task.max_duration_seconds} seconds"
                )
                self._append_skipped(
                    step_results,
                    task,
                    index,
                    task_error,
                )
                break

            if self.policy is not None:
                try:
                    self.policy.validate(step)
                except SafetyViolation as error:
                    status = TaskStatus.CANCELLED
                    task_error = (
                        f"safety policy blocked step {index}: {error}"
                    )
                    self._append_skipped(
                        step_results,
                        task,
                        index,
                        task_error,
                    )
                    break

            if step.requires_confirmation:
                if self.confirmation_handler is None:
                    status = TaskStatus.FAILED
                    task_error = (
                        f"step {index} requires confirmation, "
                        "but no confirmation handler is configured"
                    )
                    self._append_skipped(
                        step_results,
                        task,
                        index,
                        task_error,
                    )
                    break

                try:
                    confirmed = self.confirmation_handler(step)
                except ConfirmationRejected as error:
                    status = TaskStatus.CANCELLED
                    task_error = str(error)
                    self._append_skipped(
                        step_results,
                        task,
                        index,
                        task_error,
                    )
                    break

                if not confirmed:
                    status = TaskStatus.CANCELLED
                    task_error = f"step {index} was rejected"
                    self._append_skipped(
                        step_results,
                        task,
                        index,
                        task_error,
                    )
                    break

            step_started_at = datetime.now(timezone.utc)
            step_start_time = self._clock()

            try:
                if step.type == ActionType.VERIFY_VISION:
                    if self.vision_verifier is None:
                        raise TaskRunnerError(
                            "verify_vision requires a vision verifier"
                        )
                    if not self.vision_verifier(step.prompt):
                        raise TaskRunnerError(
                            f"vision verification failed: {step.prompt}"
                        )
                    outcome = StepOutcome.CONTINUE
                else:
                    outcome = self.executor.execute(step)
            except Exception as error:
                status = TaskStatus.FAILED
                task_error = str(error)
                step_results.append(
                    StepResult(
                        index=index,
                        type=step.type,
                        status=StepStatus.FAILED,
                        started_at=step_started_at,
                        finished_at=datetime.now(timezone.utc),
                        duration_seconds=max(
                            0.0,
                            self._clock() - step_start_time,
                        ),
                        error=task_error,
                        screenshot=self._get_artifact(
                            index,
                            step,
                            StepStatus.FAILED,
                        ),
                    )
                )
                break

            step_results.append(
                StepResult(
                    index=index,
                    type=step.type,
                    status=StepStatus.PASSED,
                    started_at=step_started_at,
                    finished_at=datetime.now(timezone.utc),
                    duration_seconds=max(
                        0.0,
                        self._clock() - step_start_time,
                    ),
                    screenshot=self._get_artifact(
                        index,
                        step,
                        StepStatus.PASSED,
                    ),
                )
            )

            if outcome == StepOutcome.DONE:
                self._append_skipped(
                    step_results,
                    task,
                    index + 1,
                    "task already completed",
                )
                break

        finished_at = datetime.now(timezone.utc)

        return TaskResult(
            task_name=task.name,
            status=status,
            started_at=started_at,
            finished_at=finished_at,
            duration_seconds=max(0.0, self._clock() - start_time),
            steps=step_results,
            error=task_error,
        )

    def _get_artifact(
        self,
        index: int,
        step: TaskStep,
        status: StepStatus,
    ) -> Optional[str]:
        if self.artifact_provider is None:
            return None

        try:
            artifact = self.artifact_provider(index, step, status)
        except Exception:
            return None

        return str(artifact) if artifact else None

    @staticmethod
    def _append_skipped(
        step_results,
        task: TaskDefinition,
        start_index: int,
        reason: str,
    ) -> None:
        for index in range(start_index, len(task.steps)):
            step = task.steps[index]
            skipped_at = datetime.now(timezone.utc)
            step_results.append(
                StepResult(
                    index=index,
                    type=step.type,
                    status=StepStatus.SKIPPED,
                    started_at=skipped_at,
                    finished_at=skipped_at,
                    duration_seconds=0.0,
                    error=reason,
                )
            )
