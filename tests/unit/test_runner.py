"""Tests for task execution orchestration."""

import unittest

from soc_agent.actions.executor import ActionExecutor
from soc_agent.runner import TaskRunner
from soc_agent.task_models import (
    StepStatus,
    TaskDefinition,
    TaskStatus,
)


class FakeEnvironment:
    def __init__(self):
        self.calls = []

    def open_app(self, app):
        self.calls.append(("open_app", app))

    def write(self, content):
        self.calls.append(("write", content))

    def press(self, keys):
        self.calls.append(("press", keys))

    def click(self, x, y):
        self.calls.append(("click", x, y))

    def wait(self, seconds):
        self.calls.append(("wait", seconds))


class FlakyExecutor:
    def execute(self, step):
        raise RuntimeError("execution failed")


class TaskRunnerTests(unittest.TestCase):
    def make_task(self):
        return TaskDefinition.model_validate(
            {
                "name": "calculator",
                "steps": [
                    {"type": "open_app", "app": "计算器"},
                    {"type": "write", "content": "17*23"},
                    {"type": "press", "keys": ["enter"]},
                    {
                        "type": "verify_vision",
                        "prompt": "结果是否为 391？",
                    },
                    {"type": "done", "summary": "完成"},
                ],
            }
        )

    def test_successful_task(self):
        environment = FakeEnvironment()
        runner = TaskRunner(
            ActionExecutor(environment, settle_delay=0),
            vision_verifier=lambda prompt: True,
        )

        result = runner.run(self.make_task())

        self.assertEqual(result.status, TaskStatus.PASSED)
        self.assertEqual(len(result.steps), 5)
        self.assertTrue(
            all(step.status == StepStatus.PASSED for step in result.steps)
        )
        self.assertEqual(
            environment.calls,
            [
                ("open_app", "计算器"),
                ("write", "17*23"),
                ("press", ["enter"]),
            ],
        )

    def test_artifact_provider_records_step_screenshot(self):
        environment = FakeEnvironment()
        runner = TaskRunner(
            ActionExecutor(environment, settle_delay=0),
            vision_verifier=lambda prompt: True,
            artifact_provider=lambda index, step, status: (
                f"/private/tmp/step-{index}.png"
            ),
        )

        result = runner.run(self.make_task())

        self.assertEqual(
            result.steps[3].screenshot,
            "/private/tmp/step-3.png",
        )

    def test_failed_vision_verification(self):
        environment = FakeEnvironment()
        runner = TaskRunner(
            ActionExecutor(environment, settle_delay=0),
            vision_verifier=lambda prompt: False,
        )

        result = runner.run(self.make_task())

        self.assertEqual(result.status, TaskStatus.FAILED)
        self.assertIn("vision verification failed", result.error)
        self.assertEqual(result.steps[-1].status, StepStatus.FAILED)

    def test_failed_action_records_artifact(self):
        runner = TaskRunner(
            FlakyExecutor(),
            artifact_provider=lambda index, step, status: (
                f"/private/tmp/failure-{index}.png"
            ),
        )
        task = TaskDefinition.model_validate(
            {
                "name": "failing_task",
                "steps": [{"type": "press", "keys": ["enter"]}],
            }
        )

        result = runner.run(task)

        self.assertEqual(result.steps[0].screenshot, "/private/tmp/failure-0.png")

    def test_missing_vision_verifier_fails(self):
        environment = FakeEnvironment()
        runner = TaskRunner(
            ActionExecutor(environment, settle_delay=0)
        )

        result = runner.run(self.make_task())

        self.assertEqual(result.status, TaskStatus.FAILED)
        self.assertIn("requires a vision verifier", result.error)

    def test_done_skips_remaining_steps(self):
        environment = FakeEnvironment()
        runner = TaskRunner(
            ActionExecutor(environment, settle_delay=0)
        )
        task = TaskDefinition.model_validate(
            {
                "name": "done_early",
                "steps": [
                    {"type": "done", "summary": "finished"},
                    {"type": "write", "content": "must not run"},
                ],
            }
        )

        result = runner.run(task)

        self.assertEqual(result.status, TaskStatus.PASSED)
        self.assertEqual(result.steps[0].status, StepStatus.PASSED)
        self.assertEqual(result.steps[1].status, StepStatus.SKIPPED)
        self.assertEqual(environment.calls, [])

    def test_execution_error_marks_task_failed(self):
        runner = TaskRunner(FlakyExecutor())
        task = TaskDefinition.model_validate(
            {
                "name": "failing_task",
                "steps": [{"type": "press", "keys": ["enter"]}],
            }
        )

        result = runner.run(task)

        self.assertEqual(result.status, TaskStatus.FAILED)
        self.assertEqual(result.steps[0].status, StepStatus.FAILED)
        self.assertIn("execution failed", result.error)

    def test_required_confirmation_can_cancel(self):
        environment = FakeEnvironment()
        runner = TaskRunner(
            ActionExecutor(environment, settle_delay=0),
            confirmation_handler=lambda step: False,
        )
        task = TaskDefinition.model_validate(
            {
                "name": "confirm_task",
                "steps": [
                    {
                        "type": "write",
                        "content": "sensitive",
                        "requires_confirmation": True,
                    }
                ],
            }
        )

        result = runner.run(task)

        self.assertEqual(result.status, TaskStatus.CANCELLED)
        self.assertIn("rejected", result.error)
        self.assertEqual(result.steps[0].status, StepStatus.SKIPPED)
        self.assertEqual(environment.calls, [])

    def test_missing_confirmation_handler_fails(self):
        environment = FakeEnvironment()
        runner = TaskRunner(
            ActionExecutor(environment, settle_delay=0)
        )
        task = TaskDefinition.model_validate(
            {
                "name": "confirm_task",
                "steps": [
                    {
                        "type": "write",
                        "content": "sensitive",
                        "requires_confirmation": True,
                    }
                ],
            }
        )

        result = runner.run(task)

        self.assertEqual(result.status, TaskStatus.FAILED)
        self.assertIn("no confirmation handler", result.error)

    def test_timeout(self):
        current_time = [0.0]

        class AdvancingEnvironment(FakeEnvironment):
            def write(self, content):
                super().write(content)
                current_time[0] = 61.0

        environment = AdvancingEnvironment()
        runner = TaskRunner(
            ActionExecutor(environment, settle_delay=0),
            clock=lambda: current_time[0],
        )
        task = TaskDefinition.model_validate(
            {
                "name": "timeout_task",
                "max_duration_seconds": 60,
                "steps": [
                    {"type": "write", "content": "first"},
                    {"type": "done", "summary": "finished"},
                ],
            }
        )

        result = runner.run(task)

        self.assertEqual(result.status, TaskStatus.TIMED_OUT)
        self.assertEqual(result.steps[0].status, StepStatus.PASSED)
        self.assertEqual(result.steps[1].status, StepStatus.SKIPPED)


if __name__ == "__main__":
    unittest.main()
