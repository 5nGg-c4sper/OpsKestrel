"""Tests for task definition and execution result models."""

import unittest
from datetime import datetime, timezone

from pydantic import ValidationError

from soc_agent.task_models import (
    ActionType,
    StepResult,
    StepStatus,
    TaskDefinition,
    TaskResult,
    TaskStatus,
)


class TaskDefinitionTests(unittest.TestCase):
    def setUp(self):
        self.valid_task = {
            "name": "calculator_17x23",
            "description": "计算 17*23",
            "app": "计算器",
            "max_duration_seconds": 60,
            "steps": [
                {"type": "open_app", "app": "计算器"},
                {"type": "write", "content": "17*23"},
                {"type": "press", "keys": ["enter"]},
                {
                    "type": "verify_vision",
                    "prompt": "计算器是否显示结果 391？",
                },
                {"type": "done", "summary": "17 * 23 = 391"},
            ],
        }

    def parameterized_task(self):
        return TaskDefinition.model_validate(
            {
                "name": "parameterized_task",
                "parameters": {
                    "left": {"default": "17"},
                    "right": {"description": "required operand"},
                    "operator": {"default": "*"},
                },
                "steps": [{"type": "done", "summary": "finished"}],
            }
        )

    def test_valid_task_is_parsed(self):
        task = TaskDefinition.model_validate(self.valid_task)

        self.assertEqual(task.name, "calculator_17x23")
        self.assertEqual(task.parameters, {})
        self.assertEqual(len(task.steps), 5)
        self.assertEqual(task.steps[0].type, ActionType.OPEN_APP)
        self.assertEqual(task.steps[1].content, "17*23")

    def test_parameters_with_defaults_and_required_values_are_parsed(self):
        task_data = {
            **self.valid_task,
            "parameters": {
                "left": {
                    "description": "第一个操作数",
                    "default": "17",
                },
                "right": {
                    "description": "第二个操作数",
                },
            },
        }

        task = TaskDefinition.model_validate(task_data)

        self.assertEqual(task.parameters["left"].default, "17")
        self.assertEqual(
            task.parameters["left"].description,
            "第一个操作数",
        )
        self.assertIsNone(task.parameters["right"].default)

    def test_invalid_parameter_names_are_rejected(self):
        task_data = {
            **self.valid_task,
            "parameters": {
                "17x": {},
                "中文参数": {},
            },
        }

        with self.assertRaisesRegex(
            ValidationError,
            "invalid parameter names",
        ):
            TaskDefinition.model_validate(task_data)

    def test_unknown_parameter_fields_are_rejected(self):
        task_data = {
            **self.valid_task,
            "parameters": {
                "left": {
                    "default": "17",
                    "unsupported": True,
                },
            },
        }

        with self.assertRaises(ValidationError):
            TaskDefinition.model_validate(task_data)

    def test_resolve_parameters_applies_defaults(self):
        task = self.parameterized_task()

        resolved = task.resolve_parameters({"right": "23"})

        self.assertEqual(
            resolved,
            {"left": "17", "operator": "*", "right": "23"},
        )

    def test_resolve_parameters_overrides_defaults(self):
        task = self.parameterized_task()

        resolved = task.resolve_parameters({"left": "3", "right": "4"})

        self.assertEqual(
            resolved,
            {"left": "3", "operator": "*", "right": "4"},
        )
        self.assertEqual(task.parameters["left"].default, "17")

    def test_resolve_parameters_rejects_missing_values(self):
        task = self.parameterized_task()

        with self.assertRaisesRegex(
            ValueError,
            "missing task parameters: right",
        ):
            task.resolve_parameters()

    def test_resolve_parameters_rejects_unknown_values(self):
        task = self.parameterized_task()

        with self.assertRaisesRegex(
            ValueError,
            "unknown task parameters: unsupported",
        ):
            task.resolve_parameters(
                {"right": "23", "unsupported": "value"}
            )

    def test_resolve_parameters_rejects_non_string_values(self):
        task = self.parameterized_task()

        with self.assertRaisesRegex(
            ValueError,
            "task parameter overrides must be strings: right",
        ):
            task.resolve_parameters({"right": 23})

    def test_open_app_requires_app(self):
        task = {
            "name": "missing_app",
            "steps": [{"type": "open_app"}],
        }

        with self.assertRaisesRegex(ValidationError, "open_app requires app"):
            TaskDefinition.model_validate(task)

    def test_write_requires_content(self):
        task = {
            "name": "missing_content",
            "steps": [{"type": "write"}],
        }

        with self.assertRaisesRegex(ValidationError, "write requires content"):
            TaskDefinition.model_validate(task)

    def test_press_requires_keys(self):
        task = {
            "name": "missing_keys",
            "steps": [{"type": "press", "keys": []}],
        }

        with self.assertRaisesRegex(
            ValidationError, "must contain at least one key"
        ):
            TaskDefinition.model_validate(task)

    def test_click_coordinate_must_be_in_range(self):
        task = {
            "name": "bad_click",
            "steps": [{"type": "click", "x": 2, "y": 0.5}],
        }

        with self.assertRaisesRegex(
            ValidationError, "must be between 0 and 1"
        ):
            TaskDefinition.model_validate(task)

    def test_click_requires_both_coordinates(self):
        task = {
            "name": "missing_coordinate",
            "steps": [{"type": "click", "x": 0.5}],
        }

        with self.assertRaisesRegex(
            ValidationError, "click requires x and y"
        ):
            TaskDefinition.model_validate(task)

    def test_wait_requires_positive_seconds(self):
        task = {
            "name": "invalid_wait",
            "steps": [{"type": "wait", "seconds": 0}],
        }

        with self.assertRaises(ValidationError):
            TaskDefinition.model_validate(task)

    def test_step_count_cannot_exceed_max_steps(self):
        task = {
            "name": "too_many_steps",
            "max_steps": 1,
            "steps": [
                {"type": "done", "summary": "one"},
                {"type": "done", "summary": "two"},
            ],
        }

        with self.assertRaisesRegex(ValidationError, "max_steps"):
            TaskDefinition.model_validate(task)

    def test_unknown_fields_are_rejected(self):
        task = {
            "name": "unknown_field",
            "steps": [
                {
                    "type": "open_app",
                    "app": "计算器",
                    "unsupported": True,
                }
            ],
        }

        with self.assertRaises(ValidationError):
            TaskDefinition.model_validate(task)


class TaskResultTests(unittest.TestCase):
    def test_task_result_serializes_to_json(self):
        started_at = datetime(2026, 11, 18, tzinfo=timezone.utc)
        result = TaskResult(
            task_name="calculator_17x23",
            status=TaskStatus.PASSED,
            started_at=started_at,
            finished_at=started_at,
            duration_seconds=4.5,
            steps=[
                StepResult(
                    index=0,
                    type=ActionType.OPEN_APP,
                    status=StepStatus.PASSED,
                    started_at=started_at,
                    finished_at=started_at,
                    duration_seconds=0.8,
                )
            ],
        )

        payload = result.model_dump_json()

        self.assertIn('"task_name":"calculator_17x23"', payload)
        self.assertIn('"status":"passed"', payload)
        self.assertIn('"duration_seconds":4.5', payload)


if __name__ == "__main__":
    unittest.main()
