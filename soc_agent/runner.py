"""Task execution orchestration."""

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, Optional

from soc_agent.actions.executor import ActionExecutor, StepOutcome
from soc_agent.safety.policy import SafetyPolicy, SafetyViolation
from soc_agent.task_models import (
    ActionType,
    ConditionType,
    StepPhase,
    StepResult,
    StepStatus,
    RuntimeVariableRecord,
    TaskDefinition,
    TaskResult,
    TaskStep,
    TaskStatus,
    ValueConditionOperator,
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
        runtime_values: Optional[Dict[str, str]] = None,
    ) -> TaskDefinition:
        task = TaskRunner.load_definition(task_path)
        resolved = task.resolve_parameters(parameter_overrides)
        runtime_outputs = {
            step.output
            for step in (
                task.setup_steps + task.steps + task.cleanup_steps
            )
            if step.output is not None
        }
        runtime_outputs.update((runtime_values or {}).keys())
        return task.render_parameters(
            resolved,
            preserve_placeholders=runtime_outputs,
        )

    @staticmethod
    def load_definition(task_path) -> TaskDefinition:
        path = Path(task_path)
        payload = json.loads(path.read_text(encoding="utf-8"))
        return TaskDefinition.model_validate(payload)

    def run(
        self,
        task: TaskDefinition,
        initial_runtime_values: Optional[Dict[str, str]] = None,
    ) -> TaskResult:
        started_at = datetime.now(timezone.utc)
        start_time = self._clock()
        step_results = []
        runtime_values = dict(initial_runtime_values or {})
        runtime_sensitive = {}

        status, task_error = self._run_sequence(
            task,
            task.setup_steps,
            StepPhase.SETUP,
            step_results,
            start_time,
            runtime_values,
            runtime_sensitive,
        )
        if status == TaskStatus.PASSED:
            status, task_error = self._run_sequence(
                task,
                task.steps,
                StepPhase.MAIN,
                step_results,
                start_time,
                runtime_values,
                runtime_sensitive,
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
            runtime_values,
            runtime_sensitive,
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
            runtime_variables={
                name: RuntimeVariableRecord(
                    name=name,
                    source_task=task.name,
                    sensitive=runtime_sensitive.get(name, False),
                    value=(
                        None
                        if runtime_sensitive.get(name, False)
                        else value
                    ),
                )
                for name, value in runtime_values.items()
                if name in runtime_sensitive
            },
            runtime_values=dict(runtime_values),
        )

    def _run_sequence(
        self,
        task: TaskDefinition,
        steps,
        phase: StepPhase,
        step_results,
        start_time: float,
        runtime_values: Dict[str, str],
        runtime_sensitive: Dict[str, bool],
        enforce_timeout: bool = True,
    ):
        status = TaskStatus.PASSED
        task_error = None

        for position, step in enumerate(steps):
            index = len(step_results)
            try:
                step = self._render_runtime_step(
                    step,
                    runtime_values,
                )
            except ValueError as error:
                task_error = str(error)
                self._append_skipped(
                    step_results,
                    steps,
                    position,
                    phase,
                    task_error,
                )
                status = TaskStatus.FAILED
                break
            condition_prompt = None
            condition_variable = None
            condition_operator = None
            condition_expected_value = None
            condition_actual_value = None
            condition_expected = None
            condition_actual = None
            condition_duration = None
            condition_screenshot = None
            approval_prompt = None
            approval_result = None
            extracted_value = None
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
                condition_prompt = step.condition.prompt
                condition_variable = step.condition.variable
                condition_operator = step.condition.operator
                condition_expected_value = (
                    step.condition.expected_value
                )
                condition_expected = step.condition.expected
                condition_started_at = datetime.now(timezone.utc)
                condition_start_time = self._clock()
                try:
                    if (
                        step.condition.type
                        == ConditionType.VISION
                    ):
                        condition_result = self._check_vision(
                            step.condition.prompt,
                            step.condition.expected,
                            step.condition.attempts,
                            step.condition.retry_delay_seconds,
                        )
                    else:
                        raw_value = runtime_values.get(
                            step.condition.variable
                        )
                        condition_actual_value = (
                            None
                            if runtime_sensitive.get(
                                step.condition.variable,
                                False,
                            )
                            else raw_value
                        )
                        condition_result = self._check_value(
                            raw_value,
                            step.condition.operator,
                            step.condition.expected_value,
                        )
                except Exception as error:
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
                            condition_variable=condition_variable,
                            condition_operator=condition_operator,
                            condition_expected_value=condition_expected_value,
                            condition_actual_value=condition_actual_value,
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
                            condition_variable=condition_variable,
                            condition_operator=condition_operator,
                            condition_expected_value=condition_expected_value,
                            condition_actual_value=condition_actual_value,
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

            requires_approval = (
                step.requires_confirmation
                or step.type == ActionType.APPROVAL
            )
            if requires_approval:
                approval_prompt = (
                    step.prompt
                    or step.summary
                    or f"{step.type.value} requires confirmation"
                )
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
                        approval_prompt=approval_prompt,
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
                        approval_prompt=approval_prompt,
                        approval_result=False,
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
                        approval_prompt=approval_prompt,
                        approval_result=False,
                    )
                    break
                approval_result = True

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
                        if step.type == ActionType.READ_ELEMENT:
                            extracted_value = self.executor.last_output
                            if step.output is not None:
                                runtime_values[step.output] = (
                                    extracted_value or ""
                                )
                                runtime_sensitive[step.output] = (
                                    step.sensitive_output
                                )
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
                        approval_prompt=approval_prompt,
                        approval_result=approval_result,
                        output=step.output,
                        extracted_value=(
                            None
                            if step.sensitive_output
                            else extracted_value
                        ),
                        condition_prompt=condition_prompt,
                        condition_variable=condition_variable,
                        condition_operator=condition_operator,
                        condition_expected_value=condition_expected_value,
                        condition_actual_value=condition_actual_value,
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
                    approval_prompt=approval_prompt,
                    approval_result=approval_result,
                    output=step.output,
                    extracted_value=(
                        None
                        if step.sensitive_output
                        else extracted_value
                    ),
                    condition_prompt=condition_prompt,
                    condition_variable=condition_variable,
                    condition_operator=condition_operator,
                    condition_expected_value=condition_expected_value,
                    condition_actual_value=condition_actual_value,
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

    @staticmethod
    def _render_runtime_step(step, runtime_values: Dict[str, str]):
        pattern = re.compile(r"\$\{([^{}]*)\}")

        def render_text(text: str) -> str:
            rendered = pattern.sub(
                lambda match: runtime_values.get(
                    match.group(1),
                    match.group(0),
                ),
                text,
            )
            unresolved = sorted(
                {
                    match.group(1) or "<empty>"
                    for match in pattern.finditer(rendered)
                }
            )
            if unresolved:
                raise ValueError(
                    "unresolved runtime variables: "
                    f"{', '.join(unresolved)}"
                )
            return rendered

        data = step.model_dump()
        for field_name in ("app", "content", "prompt", "summary"):
            if data[field_name] is not None:
                data[field_name] = render_text(data[field_name])
        if data["keys"] is not None:
            data["keys"] = [
                render_text(key) for key in data["keys"]
            ]
        condition = data["condition"]
        if condition is not None:
            if condition["prompt"] is not None:
                condition["prompt"] = render_text(
                    condition["prompt"]
                )
            if condition["expected_value"] is not None:
                condition["expected_value"] = render_text(
                    condition["expected_value"]
                )
        element = data["element"]
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
        return TaskStep.model_validate(data)

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

    @staticmethod
    def _check_value(
        actual: Optional[str],
        operator: Optional[ValueConditionOperator],
        expected: Optional[str],
    ) -> bool:
        if operator is None:
            raise TaskRunnerError("value condition requires operator")
        if operator == ValueConditionOperator.EXISTS:
            return actual is not None
        if operator == ValueConditionOperator.NOT_EXISTS:
            return actual is None
        if actual is None:
            return False

        actual_value = str(actual)
        expected_value = str(expected or "")
        if operator == ValueConditionOperator.EQUALS:
            return actual_value.casefold() == expected_value.casefold()
        if operator == ValueConditionOperator.NOT_EQUALS:
            return actual_value.casefold() != expected_value.casefold()
        if operator == ValueConditionOperator.CONTAINS:
            return expected_value.casefold() in actual_value.casefold()
        if operator == ValueConditionOperator.NOT_CONTAINS:
            return expected_value.casefold() not in actual_value.casefold()
        if operator == ValueConditionOperator.MATCHES:
            return re.search(expected_value, actual_value) is not None
        if operator == ValueConditionOperator.NOT_MATCHES:
            return re.search(expected_value, actual_value) is None
        raise TaskRunnerError(
            f"unsupported value condition operator: {operator}"
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
        approval_prompt=None,
        approval_result=None,
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
                    approval_prompt=(
                        approval_prompt
                        if position == start_position
                        else None
                    ),
                    approval_result=(
                        approval_result
                        if position == start_position
                        else None
                    ),
                )
            )
