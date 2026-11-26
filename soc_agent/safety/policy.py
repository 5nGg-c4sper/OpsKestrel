"""Validate actions and block unsafe operations."""

from typing import Iterable, Optional

from soc_agent.task_models import ActionType, TaskStep


class SafetyViolation(RuntimeError):
    """Raised when a task step violates a safety policy."""


class SafetyPolicy:
    """Block a small set of explicitly dangerous operations."""

    DEFAULT_BLOCKED_APPS = frozenset(
        {
            "terminal",
            "终端",
            "system settings",
            "系统设置",
            "keychain access",
            "钥匙串访问",
        }
    )

    def __init__(
        self,
        blocked_apps: Optional[Iterable[str]] = None,
        allowed_apps: Optional[Iterable[str]] = None,
        allowed_actions: Optional[Iterable[ActionType]] = None,
    ):
        apps = blocked_apps or self.DEFAULT_BLOCKED_APPS
        self.blocked_apps = frozenset(app.casefold() for app in apps)
        self.allowed_apps = (
            frozenset(app.casefold() for app in allowed_apps)
            if allowed_apps is not None
            else None
        )
        self.allowed_actions = (
            frozenset(allowed_actions)
            if allowed_actions is not None
            else None
        )

    def validate(self, step: TaskStep) -> None:
        if (
            self.allowed_actions is not None
            and step.type not in self.allowed_actions
        ):
            raise SafetyViolation(
                f"action is not allowed: {step.type.value}"
            )

        if step.type == ActionType.PRESS:
            keys = {key.casefold() for key in step.keys or []}
            if "q" in keys and ("command" in keys or "cmd" in keys):
                raise SafetyViolation("Command+Q is not allowed")

        if step.type in {
            ActionType.OPEN_APP,
            ActionType.ACTIVATE_APP,
            ActionType.CLOSE_DOCUMENT,
            ActionType.CLICK_ELEMENT,
        }:
            app_name = (step.app or "").strip().casefold()
            if app_name in self.blocked_apps:
                raise SafetyViolation(
                    f"application access is not allowed: {step.app}"
                )
            if (
                self.allowed_apps is not None
                and app_name not in self.allowed_apps
            ):
                raise SafetyViolation(
                    f"application is outside the allowed set: {step.app}"
                )
