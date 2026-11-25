"""Tests for deterministic task action execution."""

import unittest

from soc_agent.actions.executor import (
    ActionExecutionError,
    ActionExecutor,
    StepOutcome,
)
from soc_agent.task_models import TaskStep


class FakeEnvironment:
    def __init__(self):
        self.calls = []

    def open_app(self, app):
        self.calls.append(("open_app", app))

    def activate_app(self, app):
        self.calls.append(("activate_app", app))

    def close_document(self, app, save_changes=False):
        self.calls.append(
            ("close_document", app, save_changes)
        )

    def write(self, content):
        self.calls.append(("write", content))

    def press(self, keys):
        self.calls.append(("press", keys))

    def click(self, x, y):
        self.calls.append(("click", x, y))

    def wait(self, seconds):
        self.calls.append(("wait", seconds))


class ActionExecutorTests(unittest.TestCase):
    def setUp(self):
        self.environment = FakeEnvironment()
        self.executor = ActionExecutor(
            self.environment,
            settle_delay=0.6,
        )

    def test_open_app(self):
        result = self.executor.execute(
            TaskStep(type="open_app", app="计算器")
        )

        self.assertEqual(result, StepOutcome.CONTINUE)
        self.assertEqual(
            self.environment.calls,
            [("open_app", "计算器"), ("wait", 0.6)],
        )

    def test_activate_app(self):
        result = self.executor.execute(
            TaskStep(type="activate_app", app="Safari")
        )

        self.assertEqual(result, StepOutcome.CONTINUE)
        self.assertEqual(
            self.environment.calls,
            [("activate_app", "Safari"), ("wait", 0.6)],
        )

    def test_close_document(self):
        result = self.executor.execute(
            TaskStep(
                type="close_document",
                app="文本编辑",
            )
        )

        self.assertEqual(result, StepOutcome.CONTINUE)
        self.assertEqual(
            self.environment.calls,
            [
                ("close_document", "文本编辑", False),
                ("wait", 0.6),
            ],
        )

    def test_approval_is_a_noop_after_confirmation(self):
        result = self.executor.execute(
            TaskStep(type="approval", prompt="是否允许继续？")
        )

        self.assertEqual(result, StepOutcome.CONTINUE)
        self.assertEqual(self.environment.calls, [])

    def test_write(self):
        result = self.executor.execute(
            TaskStep(type="write", content="17*23")
        )

        self.assertEqual(result, StepOutcome.CONTINUE)
        self.assertEqual(
            self.environment.calls,
            [("write", "17*23")],
        )

    def test_press(self):
        result = self.executor.execute(
            TaskStep(type="press", keys=["enter"])
        )

        self.assertEqual(result, StepOutcome.CONTINUE)
        self.assertEqual(
            self.environment.calls,
            [("press", ["enter"]), ("wait", 0.6)],
        )

    def test_click(self):
        result = self.executor.execute(
            TaskStep(type="click", x=0.4, y=0.7)
        )

        self.assertEqual(result, StepOutcome.CONTINUE)
        self.assertEqual(
            self.environment.calls,
            [("click", 0.4, 0.7), ("wait", 0.6)],
        )

    def test_wait(self):
        result = self.executor.execute(
            TaskStep(type="wait", seconds=1.5)
        )

        self.assertEqual(result, StepOutcome.CONTINUE)
        self.assertEqual(
            self.environment.calls,
            [("wait", 1.5)],
        )

    def test_done_returns_done(self):
        result = self.executor.execute(
            TaskStep(type="done", summary="finished")
        )

        self.assertEqual(result, StepOutcome.DONE)
        self.assertEqual(self.environment.calls, [])

    def test_verify_vision_is_not_handled_here(self):
        step = TaskStep(
            type="verify_vision",
            prompt="结果是否为 391？",
        )

        with self.assertRaises(ActionExecutionError):
            self.executor.execute(step)

    def test_negative_settle_delay_is_rejected(self):
        with self.assertRaises(ValueError):
            ActionExecutor(self.environment, settle_delay=-0.1)


if __name__ == "__main__":
    unittest.main()
