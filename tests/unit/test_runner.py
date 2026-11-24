"""Tests for task execution orchestration."""

import json
import tempfile
import unittest
from pathlib import Path

from soc_agent.actions.executor import ActionExecutor
from soc_agent.runner import TaskRunner
from soc_agent.safety.policy import SafetyPolicy
from soc_agent.task_models import (
    ActionType,
    StepPhase,
    StepStatus,
    TaskDefinition,
    TaskStatus,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]


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

    def test_load_task_resolves_and_renders_parameters(self):
        task_payload = {
            "name": "parameterized_task",
            "parameters": {
                "left": {"default": "17"},
                "right": {},
            },
            "steps": [
                {
                    "type": "write",
                    "content": "${left}*${right}",
                },
                {
                    "type": "done",
                    "summary": "${left}*${right}",
                },
            ],
        }

        with tempfile.TemporaryDirectory() as directory:
            task_path = Path(directory) / "parameterized.json"
            original_payload = json.dumps(
                task_payload,
                ensure_ascii=False,
                indent=2,
            )
            task_path.write_text(original_payload, encoding="utf-8")

            task = TaskRunner.load_task(
                task_path,
                {"right": "23"},
            )

            self.assertEqual(task.steps[0].content, "17*23")
            self.assertEqual(task.steps[1].summary, "17*23")
            self.assertEqual(
                task_path.read_text(encoding="utf-8"),
                original_payload,
            )

    def test_load_task_propagates_missing_parameter_error(self):
        task_payload = {
            "name": "parameterized_task",
            "parameters": {"right": {}},
            "steps": [{"type": "write", "content": "${right}"}],
        }

        with tempfile.TemporaryDirectory() as directory:
            task_path = Path(directory) / "parameterized.json"
            task_path.write_text(
                json.dumps(task_payload),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                ValueError,
                "missing task parameters: right",
            ):
                TaskRunner.load_task(task_path)

    def test_parameterized_calculator_task(self):
        task_path = (
            PROJECT_ROOT / "tasks" / "calculator_parameterized.json"
        )

        task = TaskRunner.load_task(task_path, {"right": "23"})

        self.assertEqual(task.steps[2].content, "17*23")
        self.assertIn("391", task.steps[4].prompt)
        self.assertEqual(task.steps[5].summary, "17 * 23 = 391")

        with self.assertRaisesRegex(
            ValueError,
            "missing task parameters: right",
        ):
            TaskRunner.load_task(task_path)

    def test_multi_app_activate_task_is_valid(self):
        task_path = (
            PROJECT_ROOT / "tasks" / "examples" / "multi_app_activate.json"
        )

        task = TaskRunner.load_task(task_path)

        self.assertEqual(task.name, "multi_app_activate")
        self.assertEqual(len(task.steps), 9)
        self.assertEqual(task.steps[4].app, "文本编辑")
        self.assertEqual(
            task.steps[6].type,
            ActionType.ACTIVATE_APP,
        )
        self.assertEqual(task.steps[6].app, "计算器")

    def test_conditional_step_skip_task_is_valid(self):
        task_path = (
            PROJECT_ROOT
            / "tasks"
            / "examples"
            / "conditional_step_skip.json"
        )

        task = TaskRunner.load_task(task_path)

        self.assertEqual(task.name, "conditional_step_skip")
        self.assertEqual(task.steps[4].type, ActionType.WAIT)
        self.assertIsNotNone(task.steps[4].condition)
        self.assertTrue(task.steps[4].condition.expected)
        self.assertIn("999", task.steps[4].condition.prompt)

    def test_loop_write_task_is_valid(self):
        task_path = (
            PROJECT_ROOT / "tasks" / "examples" / "loop_write.json"
        )

        task = TaskRunner.load_task(task_path)

        self.assertEqual(task.name, "loop_write")
        self.assertEqual(task.steps[2].type, ActionType.WRITE)
        self.assertEqual(task.steps[2].content, "LOOP ")
        self.assertEqual(task.steps[2].loop.count, 3)
        self.assertEqual(task.steps[2].loop.delay_seconds, 0.2)

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

    def test_setup_steps_run_before_main_steps(self):
        environment = FakeEnvironment()
        runner = TaskRunner(
            ActionExecutor(environment, settle_delay=0)
        )
        task = TaskDefinition.model_validate(
            {
                "name": "setup_task",
                "setup_steps": [
                    {"type": "write", "content": "prepare"}
                ],
                "steps": [
                    {"type": "write", "content": "main"},
                    {"type": "done", "summary": "finished"},
                ],
                "cleanup_steps": [
                    {"type": "write", "content": "cleanup"}
                ],
            }
        )

        result = runner.run(task)

        self.assertEqual(result.status, TaskStatus.PASSED)
        self.assertEqual(
            environment.calls,
            [
                ("write", "prepare"),
                ("write", "main"),
                ("write", "cleanup"),
            ],
        )
        self.assertEqual(
            [step.phase for step in result.steps],
            [
                StepPhase.SETUP,
                StepPhase.MAIN,
                StepPhase.MAIN,
                StepPhase.CLEANUP,
            ],
        )
        self.assertEqual(
            [step.index for step in result.steps],
            [0, 1, 2, 3],
        )

    def test_cleanup_runs_after_main_failure(self):
        class FailingEnvironment(FakeEnvironment):
            def write(self, content):
                self.calls.append(("write", content))
                if content == "main":
                    raise RuntimeError("main failed")

        environment = FailingEnvironment()
        runner = TaskRunner(
            ActionExecutor(environment, settle_delay=0)
        )
        task = TaskDefinition.model_validate(
            {
                "name": "cleanup_after_failure",
                "steps": [{"type": "write", "content": "main"}],
                "cleanup_steps": [
                    {"type": "write", "content": "cleanup"}
                ],
            }
        )

        result = runner.run(task)

        self.assertEqual(result.status, TaskStatus.FAILED)
        self.assertEqual(
            environment.calls,
            [("write", "main"), ("write", "cleanup")],
        )
        self.assertEqual(result.steps[-1].phase, StepPhase.CLEANUP)
        self.assertEqual(result.steps[-1].status, StepStatus.PASSED)

    def test_cleanup_failure_changes_passed_task_status(self):
        class CleanupFailEnvironment(FakeEnvironment):
            def write(self, content):
                self.calls.append(("write", content))
                if content == "cleanup":
                    raise RuntimeError("cleanup failed")

        environment = CleanupFailEnvironment()
        runner = TaskRunner(
            ActionExecutor(environment, settle_delay=0)
        )
        task = TaskDefinition.model_validate(
            {
                "name": "cleanup_failure",
                "steps": [{"type": "done", "summary": "finished"}],
                "cleanup_steps": [
                    {"type": "write", "content": "cleanup"}
                ],
            }
        )

        result = runner.run(task)

        self.assertEqual(result.status, TaskStatus.FAILED)
        self.assertIn("cleanup failed", result.error)
        self.assertEqual(result.steps[-1].phase, StepPhase.CLEANUP)
        self.assertEqual(result.steps[-1].status, StepStatus.FAILED)

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

    def test_expected_false_accepts_negative_vision_result(self):
        environment = FakeEnvironment()
        runner = TaskRunner(
            ActionExecutor(environment, settle_delay=0),
            vision_verifier=lambda prompt: False,
        )
        task = TaskDefinition.model_validate(
            {
                "name": "negative_assertion",
                "steps": [
                    {
                        "type": "verify_vision",
                        "prompt": "错误提示是否未显示？",
                        "expected_vision_result": False,
                    },
                    {"type": "done", "summary": "finished"},
                ],
            }
        )

        result = runner.run(task)

        self.assertEqual(result.status, TaskStatus.PASSED)
        self.assertTrue(
            all(step.status == StepStatus.PASSED for step in result.steps)
        )

    def test_expected_false_rejects_positive_vision_result(self):
        environment = FakeEnvironment()
        runner = TaskRunner(
            ActionExecutor(environment, settle_delay=0),
            vision_verifier=lambda prompt: True,
        )
        task = TaskDefinition.model_validate(
            {
                "name": "negative_assertion",
                "steps": [
                    {
                        "type": "verify_vision",
                        "prompt": "错误提示是否未显示？",
                        "expected_vision_result": False,
                    }
                ],
            }
        )

        result = runner.run(task)

        self.assertEqual(result.status, TaskStatus.FAILED)
        self.assertIn("expected False, got True", result.error)

    def test_vision_verification_retries_until_it_passes(self):
        responses = iter([False, True])
        sleeps = []
        runner = TaskRunner(
            ActionExecutor(FakeEnvironment(), settle_delay=0),
            vision_verifier=lambda prompt: next(responses),
            sleep=sleeps.append,
        )
        task = TaskDefinition.model_validate(
            {
                "name": "retry_vision",
                "steps": [
                    {
                        "type": "verify_vision",
                        "prompt": "结果是否正确？",
                        "verification_attempts": 2,
                        "verification_retry_delay_seconds": 0.25,
                    }
                ],
            }
        )

        result = runner.run(task)

        self.assertEqual(result.status, TaskStatus.PASSED)
        self.assertEqual(sleeps, [0.25])

    def test_vision_verification_reports_attempt_count(self):
        verifier_calls = []
        sleeps = []

        def verify(prompt):
            verifier_calls.append(prompt)
            return False

        runner = TaskRunner(
            ActionExecutor(FakeEnvironment(), settle_delay=0),
            vision_verifier=verify,
            sleep=sleeps.append,
        )
        task = TaskDefinition.model_validate(
            {
                "name": "retry_vision",
                "steps": [
                    {
                        "type": "verify_vision",
                        "prompt": "结果是否正确？",
                        "verification_attempts": 3,
                        "verification_retry_delay_seconds": 0.1,
                    }
                ],
            }
        )

        result = runner.run(task)

        self.assertEqual(result.status, TaskStatus.FAILED)
        self.assertEqual(len(verifier_calls), 3)
        self.assertEqual(sleeps, [0.1, 0.1])
        self.assertIn("after 3 attempt(s)", result.error)

    def test_true_condition_executes_step(self):
        environment = FakeEnvironment()
        prompts = []
        runner = TaskRunner(
            ActionExecutor(environment, settle_delay=0),
            vision_verifier=lambda prompt: prompts.append(prompt) or True,
            condition_artifact_provider=(
                lambda index, step: "condition.png"
            ),
        )
        task = TaskDefinition.model_validate(
            {
                "name": "conditional_write",
                "steps": [
                    {
                        "type": "write",
                        "content": "conditional",
                        "condition": {
                            "type": "vision",
                            "prompt": "编辑区域是否已打开？",
                        },
                    }
                ],
            }
        )

        result = runner.run(task)

        self.assertEqual(result.status, TaskStatus.PASSED)
        self.assertEqual(result.steps[0].status, StepStatus.PASSED)
        self.assertEqual(environment.calls, [("write", "conditional")])
        self.assertEqual(prompts, ["编辑区域是否已打开？"])
        self.assertEqual(
            result.steps[0].condition_prompt,
            "编辑区域是否已打开？",
        )
        self.assertTrue(result.steps[0].condition_expected)
        self.assertTrue(result.steps[0].condition_actual)
        self.assertIsNotNone(
            result.steps[0].condition_duration_seconds
        )
        self.assertEqual(
            result.steps[0].condition_screenshot,
            "condition.png",
        )

    def test_false_condition_skips_step(self):
        environment = FakeEnvironment()
        runner = TaskRunner(
            ActionExecutor(environment, settle_delay=0),
            vision_verifier=lambda prompt: False,
            condition_artifact_provider=(
                lambda index, step: "condition.png"
            ),
        )
        task = TaskDefinition.model_validate(
            {
                "name": "conditional_skip",
                "steps": [
                    {
                        "type": "write",
                        "content": "must not run",
                        "condition": {
                            "type": "vision",
                            "prompt": "编辑区域是否已打开？",
                        },
                    },
                    {"type": "done", "summary": "finished"},
                ],
            }
        )

        result = runner.run(task)

        self.assertEqual(result.status, TaskStatus.PASSED)
        self.assertEqual(result.steps[0].status, StepStatus.SKIPPED)
        self.assertIn("condition not met", result.steps[0].error)
        self.assertFalse(result.steps[0].condition_actual)
        self.assertIsNotNone(
            result.steps[0].condition_duration_seconds
        )
        self.assertEqual(
            result.steps[0].condition_screenshot,
            "condition.png",
        )
        self.assertEqual(result.steps[1].status, StepStatus.PASSED)
        self.assertEqual(environment.calls, [])

    def test_expected_false_condition_executes_step(self):
        environment = FakeEnvironment()
        runner = TaskRunner(
            ActionExecutor(environment, settle_delay=0),
            vision_verifier=lambda prompt: False,
        )
        task = TaskDefinition.model_validate(
            {
                "name": "negative_condition",
                "steps": [
                    {
                        "type": "write",
                        "content": "negative condition",
                        "condition": {
                            "type": "vision",
                            "prompt": "错误提示是否未显示？",
                            "expected": False,
                        },
                    }
                ],
            }
        )

        result = runner.run(task)

        self.assertEqual(result.status, TaskStatus.PASSED)
        self.assertEqual(environment.calls, [("write", "negative condition")])

    def test_condition_verifier_error_fails_task(self):
        def verify(prompt):
            raise RuntimeError("condition provider failed")

        runner = TaskRunner(
            ActionExecutor(FakeEnvironment(), settle_delay=0),
            vision_verifier=verify,
        )
        task = TaskDefinition.model_validate(
            {
                "name": "condition_error",
                "steps": [
                    {
                        "type": "write",
                        "content": "must not run",
                        "condition": {
                            "type": "vision",
                            "prompt": "条件是否成立？",
                        },
                    }
                ],
            }
        )

        result = runner.run(task)

        self.assertEqual(result.status, TaskStatus.FAILED)
        self.assertEqual(result.steps[0].status, StepStatus.FAILED)
        self.assertIn("condition provider failed", result.error)
        self.assertEqual(
            result.steps[0].condition_prompt,
            "条件是否成立？",
        )
        self.assertIsNone(result.steps[0].condition_actual)
        self.assertIsNotNone(
            result.steps[0].condition_duration_seconds
        )

    def test_loop_executes_step_configured_number_of_times(self):
        environment = FakeEnvironment()
        sleeps = []
        runner = TaskRunner(
            ActionExecutor(environment, settle_delay=0),
            sleep=sleeps.append,
        )
        task = TaskDefinition.model_validate(
            {
                "name": "looped_press",
                "steps": [
                    {
                        "type": "press",
                        "keys": ["tab"],
                        "loop": {
                            "count": 3,
                            "delay_seconds": 0.2,
                        },
                    }
                ],
            }
        )

        result = runner.run(task)

        self.assertEqual(result.status, TaskStatus.PASSED)
        self.assertEqual(
            environment.calls,
            [
                ("press", ["tab"]),
                ("press", ["tab"]),
                ("press", ["tab"]),
            ],
        )
        self.assertEqual(sleeps, [0.2, 0.2])
        self.assertEqual(result.steps[0].loop_count, 3)
        self.assertEqual(
            result.steps[0].loop_iterations_completed,
            3,
        )
        self.assertEqual(result.steps[0].loop_delay_seconds, 0.2)

    def test_loop_records_completed_iterations_before_failure(self):
        class FailingEnvironment(FakeEnvironment):
            def press(self, keys):
                self.calls.append(("press", keys))
                if len(self.calls) == 2:
                    raise RuntimeError("second iteration failed")

        environment = FailingEnvironment()
        runner = TaskRunner(
            ActionExecutor(environment, settle_delay=0)
        )
        task = TaskDefinition.model_validate(
            {
                "name": "looped_failure",
                "steps": [
                    {
                        "type": "press",
                        "keys": ["tab"],
                        "loop": {
                            "count": 3,
                            "delay_seconds": 0,
                        },
                    }
                ],
            }
        )

        result = runner.run(task)

        self.assertEqual(result.status, TaskStatus.FAILED)
        self.assertEqual(
            result.steps[0].loop_iterations_completed,
            1,
        )
        self.assertIn("second iteration failed", result.error)

    def test_skipped_loop_records_zero_completed_iterations(self):
        environment = FakeEnvironment()
        runner = TaskRunner(
            ActionExecutor(environment, settle_delay=0),
            vision_verifier=lambda prompt: False,
        )
        task = TaskDefinition.model_validate(
            {
                "name": "skipped_loop",
                "steps": [
                    {
                        "type": "press",
                        "keys": ["tab"],
                        "loop": {"count": 3},
                        "condition": {
                            "type": "vision",
                            "prompt": "是否继续？",
                        },
                    }
                ],
            }
        )

        result = runner.run(task)

        self.assertEqual(result.steps[0].status, StepStatus.SKIPPED)
        self.assertEqual(result.steps[0].loop_count, 3)
        self.assertEqual(
            result.steps[0].loop_iterations_completed,
            0,
        )
        self.assertEqual(environment.calls, [])

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

    def test_safety_policy_blocks_dangerous_action(self):
        environment = FakeEnvironment()
        runner = TaskRunner(
            ActionExecutor(environment, settle_delay=0),
            policy=SafetyPolicy(),
        )
        task = TaskDefinition.model_validate(
            {
                "name": "unsafe_task",
                "steps": [
                    {"type": "press", "keys": ["command", "q"]},
                ],
            }
        )

        result = runner.run(task)

        self.assertEqual(result.status, TaskStatus.CANCELLED)
        self.assertIn("safety policy blocked", result.error)
        self.assertEqual(result.steps[0].status, StepStatus.SKIPPED)
        self.assertEqual(environment.calls, [])


if __name__ == "__main__":
    unittest.main()
