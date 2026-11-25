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
    StepPhase,
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
        condition_artifact_provider: Optional[
            Callable[[int, TaskStep], Optional[str]]
        ] = None,
        policy: Optional[SafetyPolicy] = None,
        clock: Optional[Callable[[], float]] = None,
        sleep: Optional[Callable[[float], None]] = None,
    ):
        self.executor = executor
        self.vision_verifier = vision_verifier
        self.confirmation_handler = confirmation_handler
        self.artifact_provider = artifact_provider
        self.condition_artifact_provider = condition_artifact_provider
        self.policy = policy
        self._clock = clock or time.monotonic
        self._sleep = sleep or time.sleep

    @staticmethod
    def load_task(
        task_path,
        parameter_overrides: Optional[Dict[str, str]] = None,
    ) -> TaskDefinition:
        task = TaskRunner.load_definition(task_path)
        resolved = task.resolve_parameters(parameter_overrides)
        return task.render_parameters(resolved)

    @staticmethod
    def load_definition(task_path) -> TaskDefinition:
        path = Path(task_path)
        payload = json.loads(path.read_text(encoding="utf-8"))
        return TaskDefinition.model_validate(payload)

    def run(self, task: TaskDefinition) -> TaskResult:
        started_at = datetime.now(timezone.utc)
        start_time = self._clock()
        step_results = []

        status, task_error = self._run_sequence(
            task,
            task.setup_steps,
            StepPhase.SETUP,
            step_results,
            start_time,
        )
        if status == TaskStatus.PASSED:
            status, task_error = self._run_sequence(
                task,
                task.steps,
                StepPhase.MAIN,
                step_results,
                start_time,
            )
        else:
            self._append_skipped(
                step_results,
                task.steps,
                0,
                StepPhase.MAIN,
                "setup did not pass",
            )

        cleanup_status, cleanup_error = self._run_sequence(
            task,
            task.cleanup_steps,
            StepPhase.CLEANUP,
            step_results,
            start_time,
            enforce_timeout=False,
        )
        if cleanup_status != TaskStatus.PASSED and status == TaskStatus.PASSED:
            status = cleanup_status
            task_error = cleanup_error

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

    def _run_sequence(
        self,
        task: TaskDefinition,
        steps,
        phase: StepPhase,
        step_results,
        start_time: float,
        enforce_timeout: bool = True,
    ):
        status = TaskStatus.PASSED
        task_error = None

        for position, step in enumerate(steps):
            index = len(step_results)
            condition_prompt = None
            condition_expected = None
            condition_actual = None
            condition_duration = None
            condition_screenshot = None
            configured_loop_count = (
                step.loop.count if step.loop is not None else None
            )
            loop_delay_seconds = (
                step.loop.delay_seconds
                if step.loop is not None
                else None
            )
            iterations_completed = 0

            if (
                enforce_timeout
                and self._clock() - start_time
                > task.max_duration_seconds
            ):
                status = TaskStatus.TIMED_OUT
                task_error = (
                    f"task exceeded {task.max_duration_seconds} seconds"
                )
                self._append_skipped(
                    step_results,
                    steps,
                    position,
                    phase,
                    task_error,
                )
                break

            if step.condition is not None:
                condition_started_at = datetime.now(timezone.utc)
                condition_start_time = self._clock()
                try:
                    condition_result = self._check_vision(
                        step.condition.prompt,
                        step.condition.expected,
                        step.condition.attempts,
                        step.condition.retry_delay_seconds,
                    )
                except Exception as error:
                    condition_prompt = step.condition.prompt
                    condition_expected = step.condition.expected
                    condition_duration = max(
                        0.0,
                        self._clock() - condition_start_time,
                    )
                    condition_screenshot = (
                        self._get_condition_artifact(index, step)
                    )
                    status = TaskStatus.FAILED
                    task_error = str(error)
                    step_results.append(
                        StepResult(
                            index=index,
                            type=step.type,
                            status=StepStatus.FAILED,
                            phase=phase,
                            started_at=condition_started_at,
                            finished_at=datetime.now(timezone.utc),
                            duration_seconds=condition_duration,
                            error=task_error,
                            screenshot=self._get_artifact(
                                index,
                                step,
                                StepStatus.FAILED,
                            ),
                            condition_prompt=condition_prompt,
                            condition_expected=condition_expected,
                            condition_actual=None,
                            condition_duration_seconds=condition_duration,
                            condition_screenshot=condition_screenshot,
                            loop_count=configured_loop_count,
                            loop_iterations_completed=0,
                            loop_delay_seconds=loop_delay_seconds,
                        )
                    )
                    break

                condition_prompt = step.condition.prompt
                condition_expected = step.condition.expected
                condition_actual = condition_result
                condition_duration = max(
                    0.0,
                    self._clock() - condition_start_time,
                )
                condition_screenshot = self._get_condition_artifact(
                    index,
                    step,
                )

                if condition_result != step.condition.expected:
                    skipped_at = datetime.now(timezone.utc)
                    step_results.append(
                        StepResult(
                            index=index,
                            type=step.type,
                            status=StepStatus.SKIPPED,
                            phase=phase,
                            started_at=condition_started_at,
                            finished_at=skipped_at,
                            duration_seconds=condition_duration,
                            error=(
                                "condition not met: "
                                f"expected {step.condition.expected}, "
                                f"got {condition_result}"
                            ),
                            condition_prompt=condition_prompt,
                            condition_expected=condition_expected,
                            condition_actual=condition_actual,
                            condition_duration_seconds=condition_duration,
                            condition_screenshot=condition_screenshot,
                            loop_count=configured_loop_count,
                            loop_iterations_completed=0,
                            loop_delay_seconds=loop_delay_seconds,
                        )
                    )
                    continue

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
                        steps,
                        position,
                        phase,
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
                        steps,
                        position,
                        phase,
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
                        steps,
                        position,
                        phase,
                        task_error,
                    )
                    break

                if not confirmed:
                    status = TaskStatus.CANCELLED
                    task_error = f"step {index} was rejected"
                    self._append_skipped(
                        step_results,
                        steps,
                        position,
                        phase,
                        task_error,
                    )
                    break

            step_started_at = datetime.now(timezone.utc)
            step_start_time = self._clock()

            try:
                if step.type == ActionType.VERIFY_VISION:
                    verification_result = self._check_vision(
                        step.prompt,
                        step.expected_vision_result,
                        step.verification_attempts,
                        step.verification_retry_delay_seconds,
                    )
                    if (
                        verification_result
                        != step.expected_vision_result
                    ):
                        raise TaskRunnerError(
                            "vision verification failed after "
                            f"{step.verification_attempts} attempt(s): "
                            f"expected {step.expected_vision_result}, "
                            f"got {verification_result}: {step.prompt}"
                        )
                    iterations_completed = 1
                    outcome = StepOutcome.CONTINUE
                else:
                    loop_count = configured_loop_count or 1
                    for iteration in range(loop_count):
                        outcome = self.executor.execute(step)
                        iterations_completed += 1
                        if iteration + 1 < loop_count:
                            self._sleep(loop_delay_seconds or 0.0)
            except Exception as error:
                status = TaskStatus.FAILED
                task_error = str(error)
                step_results.append(
                    StepResult(
                        index=index,
                        type=step.type,
                        status=StepStatus.FAILED,
                        phase=phase,
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
                        condition_prompt=condition_prompt,
                        condition_expected=condition_expected,
                        condition_actual=condition_actual,
                        condition_duration_seconds=condition_duration,
                        condition_screenshot=condition_screenshot,
                        loop_count=configured_loop_count,
                        loop_iterations_completed=iterations_completed,
                        loop_delay_seconds=loop_delay_seconds,
                    )
                )
                break

            step_results.append(
                StepResult(
                    index=index,
                    type=step.type,
                    status=StepStatus.PASSED,
                    phase=phase,
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
                    condition_prompt=condition_prompt,
                    condition_expected=condition_expected,
                    condition_actual=condition_actual,
                    condition_duration_seconds=condition_duration,
                    condition_screenshot=condition_screenshot,
                    loop_count=configured_loop_count,
                    loop_iterations_completed=iterations_completed,
                    loop_delay_seconds=loop_delay_seconds,
                )
            )

            if outcome == StepOutcome.DONE:
                self._append_skipped(
                    step_results,
                    steps,
                    position + 1,
                    phase,
                    "task already completed",
                )
                break

        return status, task_error

    def _check_vision(
        self,
        prompt: str,
        expected: bool,
        attempts: int,
        retry_delay_seconds: float,
    ) -> bool:
        if self.vision_verifier is None:
            raise TaskRunnerError(
                "vision verification requires a vision verifier"
            )

        verification_result = None
        for attempt in range(attempts):
            verification_result = self.vision_verifier(prompt)
            if verification_result == expected:
                return verification_result
            if attempt + 1 < attempts:
                self._sleep(retry_delay_seconds)

        return bool(verification_result)

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

    def _get_condition_artifact(
        self,
        index: int,
        step: TaskStep,
    ) -> Optional[str]:
        if self.condition_artifact_provider is None:
            return None

        try:
            artifact = self.condition_artifact_provider(index, step)
        except Exception:
            return None

        return str(artifact) if artifact else None

    @staticmethod
    def _append_skipped(
        step_results,
        steps,
        start_position: int,
        phase: StepPhase,
        reason: str,
    ) -> None:
        for position in range(start_position, len(steps)):
            step = steps[position]
            skipped_at = datetime.now(timezone.utc)
            step_results.append(
                StepResult(
                    index=len(step_results),
                    type=step.type,
                    status=StepStatus.SKIPPED,
                    phase=phase,
                    started_at=skipped_at,
                    finished_at=skipped_at,
                    duration_seconds=0.0,
                    error=reason,
                )
            )
