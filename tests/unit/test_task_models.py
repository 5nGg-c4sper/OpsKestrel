"""Tests for task definition and execution result models."""

import unittest
from datetime import datetime, timezone

from pydantic import ValidationError

from soc_agent.task_models import (
    ActionType,
    StepResult,
    StepStatus,
    TaskCaseResult,
    TaskDatasetDefinition,
    TaskDatasetResult,
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

    def renderable_task(self):
        return TaskDefinition.model_validate(
            {
                "name": "renderable_task",
                "app": "${app_name}",
                "parameters": {
                    "app_name": {},
                    "left": {},
                    "operator": {},
                    "right": {},
                    "expected": {},
                    "submit_key": {},
                },
                "steps": [
                    {"type": "open_app", "app": "${app_name}"},
                    {
                        "type": "write",
                        "content": "${left}${operator}${right}",
                    },
                    {"type": "press", "keys": ["${submit_key}"]},
                    {
                        "type": "verify_vision",
                        "prompt": "结果是否为 ${expected}？",
                    },
                    {
                        "type": "done",
                        "summary": "${left}${operator}${right}=${expected}",
                    },
                ],
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

    def test_render_parameters_replaces_supported_fields(self):
        task = self.renderable_task()

        rendered = task.render_parameters(
            {
                "app_name": "计算器",
                "left": "17",
                "operator": "*",
                "right": "23",
                "expected": "391",
                "submit_key": "enter",
            }
        )

        self.assertEqual(rendered.app, "计算器")
        self.assertEqual(rendered.steps[0].app, "计算器")
        self.assertEqual(rendered.steps[1].content, "17*23")
        self.assertEqual(rendered.steps[2].keys, ["enter"])
        self.assertEqual(rendered.steps[3].prompt, "结果是否为 391？")
        self.assertEqual(rendered.steps[4].summary, "17*23=391")
        self.assertEqual(task.app, "${app_name}")
        self.assertEqual(
            task.steps[1].content,
            "${left}${operator}${right}",
        )

    def test_render_parameters_preserves_non_placeholder_dollars(self):
        task = TaskDefinition.model_validate(
            {
                "name": "dollar_text",
                "steps": [
                    {"type": "write", "content": "价格 $5：${price}"}
                ],
            }
        )

        rendered = task.render_parameters({"price": "$6"})

        self.assertEqual(rendered.steps[0].content, "价格 $5：$6")

    def test_render_parameters_rejects_unresolved_placeholders(self):
        task = TaskDefinition.model_validate(
            {
                "name": "unresolved",
                "steps": [
                    {"type": "write", "content": "${missing}"}
                ],
            }
        )

        with self.assertRaisesRegex(
            ValueError,
            "unresolved task parameters: missing",
        ):
            task.render_parameters({})

    def test_render_parameters_does_not_recursively_expand_values(self):
        task = TaskDefinition.model_validate(
            {
                "name": "recursive_value",
                "steps": [
                    {"type": "write", "content": "${first}"}
                ],
            }
        )

        with self.assertRaisesRegex(
            ValueError,
            "unresolved task parameters: second",
        ):
            task.render_parameters(
                {"first": "${second}", "second": "expanded"}
            )

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


class TaskDatasetDefinitionTests(unittest.TestCase):
    def setUp(self):
        self.valid_dataset = {
            "name": "calculator_cases",
            "task": "tasks/calculator_parameterized.json",
            "cases": [
                {
                    "name": "default_result",
                    "parameters": {"right": "23"},
                },
                {
                    "name": "custom_result",
                    "parameters": {
                        "left": "3",
                        "right": "4",
                        "expected_result": "12",
                    },
                },
            ],
        }

    def test_valid_dataset_is_parsed(self):
        dataset = TaskDatasetDefinition.model_validate(self.valid_dataset)

        self.assertEqual(dataset.name, "calculator_cases")
        self.assertEqual(len(dataset.cases), 2)
        self.assertEqual(dataset.cases[0].parameters, {"right": "23"})

    def test_dataset_requires_at_least_one_case(self):
        dataset_data = {**self.valid_dataset, "cases": []}

        with self.assertRaises(ValidationError):
            TaskDatasetDefinition.model_validate(dataset_data)

    def test_duplicate_case_names_are_rejected(self):
        dataset_data = {
            **self.valid_dataset,
            "cases": [
                {"name": "duplicate", "parameters": {"right": "1"}},
                {"name": "duplicate", "parameters": {"right": "2"}},
            ],
        }

        with self.assertRaisesRegex(
            ValidationError,
            "duplicate case names: duplicate",
        ):
            TaskDatasetDefinition.model_validate(dataset_data)

    def test_empty_case_name_is_rejected(self):
        dataset_data = {
            **self.valid_dataset,
            "cases": [{"name": " ", "parameters": {}}],
        }

        with self.assertRaises(ValidationError):
            TaskDatasetDefinition.model_validate(dataset_data)

    def test_invalid_case_parameter_names_are_rejected(self):
        dataset_data = {
            **self.valid_dataset,
            "cases": [
                {
                    "name": "invalid_parameter",
                    "parameters": {"17x": "value"},
                }
            ],
        }

        with self.assertRaisesRegex(
            ValidationError,
            "invalid parameter names",
        ):
            TaskDatasetDefinition.model_validate(dataset_data)

    def test_unknown_dataset_and_case_fields_are_rejected(self):
        invalid_payloads = [
            {**self.valid_dataset, "unsupported": True},
            {
                **self.valid_dataset,
                "cases": [
                    {
                        "name": "case",
                        "parameters": {},
                        "unsupported": True,
                    }
                ],
            },
        ]

        for payload in invalid_payloads:
            with self.subTest(payload=payload):
                with self.assertRaises(ValidationError):
                    TaskDatasetDefinition.model_validate(payload)


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


class TaskDatasetResultTests(unittest.TestCase):
    def make_task_result(
        self,
        status=TaskStatus.PASSED,
        error=None,
    ):
        started_at = datetime(2026, 11, 20, tzinfo=timezone.utc)
        return TaskResult(
            task_name="calculator_parameterized",
            status=status,
            started_at=started_at,
            finished_at=started_at,
            duration_seconds=4.5,
            error=error,
        )

    def test_dataset_result_serializes_nested_case_results(self):
        started_at = datetime(2026, 11, 20, tzinfo=timezone.utc)
        case_result = TaskCaseResult(
            name="default_17x23",
            parameters={"right": "23"},
            status=TaskStatus.PASSED,
            duration_seconds=4.5,
            task_result=self.make_task_result(),
        )
        dataset_result = TaskDatasetResult(
            dataset_name="calculator_regression",
            status=TaskStatus.PASSED,
            started_at=started_at,
            finished_at=started_at,
            duration_seconds=4.5,
            cases=[case_result],
            report_path="reports/calculator_regression.json",
        )

        payload = dataset_result.model_dump_json()

        self.assertIn('"dataset_name":"calculator_regression"', payload)
        self.assertIn('"name":"default_17x23"', payload)
        self.assertIn('"right":"23"', payload)
        self.assertIn('"task_name":"calculator_parameterized"', payload)
        self.assertIn(
            '"report_path":"reports/calculator_regression.json"',
            payload,
        )

    def test_dataset_result_requires_at_least_one_case(self):
        started_at = datetime(2026, 11, 20, tzinfo=timezone.utc)

        with self.assertRaises(ValidationError):
            TaskDatasetResult(
                dataset_name="empty_dataset",
                status=TaskStatus.FAILED,
                started_at=started_at,
                cases=[],
            )

    def test_case_result_rejects_empty_name(self):
        with self.assertRaises(ValidationError):
            TaskCaseResult(
                name=" ",
                status=TaskStatus.PASSED,
                task_result=self.make_task_result(),
            )

    def test_dataset_result_preserves_failure_state(self):
        started_at = datetime(2026, 11, 20, tzinfo=timezone.utc)
        task_result = self.make_task_result(
            status=TaskStatus.FAILED,
            error="vision verification failed",
        )
        case_result = TaskCaseResult(
            name="failed_case",
            parameters={"right": "23"},
            status=TaskStatus.FAILED,
            duration_seconds=2.0,
            task_result=task_result,
            error="vision verification failed",
        )
        dataset_result = TaskDatasetResult(
            dataset_name="calculator_regression",
            status=TaskStatus.FAILED,
            started_at=started_at,
            finished_at=started_at,
            duration_seconds=2.0,
            cases=[case_result],
        )

        self.assertEqual(dataset_result.status, TaskStatus.FAILED)
        self.assertEqual(dataset_result.cases[0].status, TaskStatus.FAILED)
        self.assertEqual(
            dataset_result.cases[0].error,
            "vision verification failed",
        )


if __name__ == "__main__":
    unittest.main()
