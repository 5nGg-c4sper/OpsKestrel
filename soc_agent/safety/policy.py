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

    def __init__(self, blocked_apps: Optional[Iterable[str]] = None):
        apps = blocked_apps or self.DEFAULT_BLOCKED_APPS
        self.blocked_apps = frozenset(app.casefold() for app in apps)

    def validate(self, step: TaskStep) -> None:
        if step.type == ActionType.PRESS:
            keys = {key.casefold() for key in step.keys or []}
            if "q" in keys and ("command" in keys or "cmd" in keys):
                raise SafetyViolation("Command+Q is not allowed")

        if step.type == ActionType.OPEN_APP:
            app_name = (step.app or "").strip().casefold()
            if app_name in self.blocked_apps:
                raise SafetyViolation(
                    f"opening application is not allowed: {step.app}"
                )
