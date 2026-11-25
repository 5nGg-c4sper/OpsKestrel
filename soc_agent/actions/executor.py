"""Dispatch validated task actions to the active environment."""

from enum import Enum

from soc_agent.task_models import ActionType, TaskStep


class StepOutcome(str, Enum):
    CONTINUE = "continue"
    DONE = "done"


class ActionExecutionError(RuntimeError):
    """Raised when an action cannot be executed."""


class ActionExecutor:
    """Execute deterministic task steps through an environment adapter."""

    def __init__(self, environment, settle_delay: float = 0.6):
        settle_delay = float(settle_delay)
        if settle_delay < 0:
            raise ValueError("settle_delay must not be negative")

        self.environment = environment
        self.settle_delay = settle_delay

    def execute(self, step: TaskStep) -> StepOutcome:
        if step.type == ActionType.OPEN_APP:
            self.environment.open_app(step.app)
            self._settle()
            return StepOutcome.CONTINUE

        if step.type == ActionType.ACTIVATE_APP:
            self.environment.activate_app(step.app)
            self._settle()
            return StepOutcome.CONTINUE

        if step.type == ActionType.CLOSE_DOCUMENT:
            self.environment.close_document(
                step.app,
                save_changes=step.save_changes,
            )
            self._settle()
            return StepOutcome.CONTINUE

        if step.type == ActionType.WRITE:
            self.environment.write(step.content)
            return StepOutcome.CONTINUE

        if step.type == ActionType.PRESS:
            self.environment.press(step.keys)
            self._settle()
            return StepOutcome.CONTINUE

        if step.type == ActionType.CLICK:
            self.environment.click(step.x, step.y)
            self._settle()
            return StepOutcome.CONTINUE

        if step.type == ActionType.WAIT:
            self.environment.wait(step.seconds)
            return StepOutcome.CONTINUE

        if step.type == ActionType.DONE:
            return StepOutcome.DONE

        if step.type == ActionType.VERIFY_VISION:
            raise ActionExecutionError(
                "verify_vision must be handled by the vision provider"
            )

        raise ActionExecutionError(f"unsupported action: {step.type}")

    def _settle(self) -> None:
        if self.settle_delay > 0:
            self.environment.wait(self.settle_delay)
