"""Tests for task definition and execution result models."""

import unittest
from datetime import datetime, timezone

from pydantic import ValidationError

from soc_agent.task_models import (
    ActionType,
    ConditionType,
    StepResult,
    StepPhase,
    StepStatus,
    TaskCaseResult,
    TaskCondition,
    TaskDatasetDefinition,
    TaskDatasetResult,
    TaskDefinition,
    TaskLoop,
    TaskResult,
    TaskStatus,
    UIElementLocator,
    WorkflowDefinition,
    WorkflowResult,
)


class TaskConditionTests(unittest.TestCase):
    def test_condition_defaults(self):
        condition = TaskCondition(
            type="vision",
            prompt="结果是否正确？",
        )

        self.assertEqual(condition.type, ConditionType.VISION)
        self.assertTrue(condition.expected)
        self.assertEqual(condition.attempts, 1)
        self.assertEqual(condition.retry_delay_seconds, 0.5)

    def test_condition_accepts_custom_retry_values(self):
        condition = TaskCondition(
            type="vision",
            prompt="错误提示是否未显示？",
            expected=False,
            attempts=3,
            retry_delay_seconds=0.2,
        )

        self.assertFalse(condition.expected)
        self.assertEqual(condition.attempts, 3)
        self.assertEqual(condition.retry_delay_seconds, 0.2)

    def test_condition_rejects_empty_prompt(self):
        with self.assertRaises(ValidationError):
            TaskCondition(type="vision", prompt=" ")

    def test_condition_rejects_invalid_retry_values(self):
        invalid_values = (
            {"attempts": 0},
            {"attempts": 6},
            {"retry_delay_seconds": -0.1},
            {"retry_delay_seconds": 11},
        )

        for values in invalid_values:
            with self.subTest(values=values):
                with self.assertRaises(ValidationError):
                    TaskCondition(
                        type="vision",
                        prompt="结果是否正确？",
                        **values,
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
                        "condition": {
                            "type": "vision",
                            "prompt": "结果是否为 ${expected}？",
                        },
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
        self.assertEqual(task.setup_steps, [])
        self.assertEqual(task.cleanup_steps, [])

    def test_task_accepts_setup_and_cleanup_steps(self):
        task_data = {
            **self.valid_task,
            "setup_steps": [
                {"type": "open_app", "app": "文本编辑"},
            ],
            "cleanup_steps": [
                {"type": "press", "keys": ["escape"]},
            ],
        }

        task = TaskDefinition.model_validate(task_data)

        self.assertEqual(len(task.setup_steps), 1)
        self.assertEqual(task.setup_steps[0].app, "文本编辑")
        self.assertEqual(len(task.cleanup_steps), 1)
        self.assertEqual(task.cleanup_steps[0].keys, ["escape"])

    def test_step_count_includes_setup_and_cleanup(self):
        task = {
            "name": "too_many_phase_steps",
            "max_steps": 2,
            "setup_steps": [{"type": "wait", "seconds": 0.1}],
            "steps": [{"type": "wait", "seconds": 0.1}],
            "cleanup_steps": [{"type": "wait", "seconds": 0.1}],
        }

        with self.assertRaisesRegex(ValidationError, "max_steps"):
            TaskDefinition.model_validate(task)

    def test_done_is_rejected_in_setup_or_cleanup(self):
        for field_name in ("setup_steps", "cleanup_steps"):
            with self.subTest(field_name=field_name):
                task = {
                    "name": "invalid_done",
                    "steps": [{"type": "done", "summary": "finished"}],
                    field_name: [
                        {"type": "done", "summary": "phase finished"}
                    ],
                }
                with self.assertRaisesRegex(
                    ValidationError,
                    "done is only supported in main steps",
                ):
                    TaskDefinition.model_validate(task)

    def test_setup_and_cleanup_parameters_are_rendered(self):
        task = TaskDefinition.model_validate(
            {
                "name": "phase_parameters",
                "parameters": {
                    "setup_text": {},
                    "cleanup_text": {},
                },
                "setup_steps": [
                    {"type": "write", "content": "${setup_text}"}
                ],
                "steps": [{"type": "done", "summary": "finished"}],
                "cleanup_steps": [
                    {"type": "write", "content": "${cleanup_text}"}
                ],
            }
        )

        rendered = task.render_parameters(
            {
                "setup_text": "prepared",
                "cleanup_text": "cleaned",
            }
        )

        self.assertEqual(
            rendered.setup_steps[0].content,
            "prepared",
        )
        self.assertEqual(
            rendered.cleanup_steps[0].content,
            "cleaned",
        )

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

    def test_verify_vision_defaults_to_expected_true(self):
        task = TaskDefinition.model_validate(self.valid_task)

        self.assertTrue(task.steps[3].expected_vision_result)

    def test_verify_vision_accepts_expected_false(self):
        task_data = {
            **self.valid_task,
            "steps": [
                {
                    "type": "verify_vision",
                    "prompt": "错误提示是否未显示？只返回 true 或 false。",
                    "expected_vision_result": False,
                }
            ],
        }

        task = TaskDefinition.model_validate(task_data)

        self.assertFalse(task.steps[0].expected_vision_result)

    def test_verify_vision_retry_defaults(self):
        task = TaskDefinition.model_validate(self.valid_task)
        step = task.steps[3]

        self.assertEqual(step.verification_attempts, 1)
        self.assertEqual(step.verification_retry_delay_seconds, 0.5)

    def test_verify_vision_retry_values_are_validated(self):
        invalid_values = (
            {"verification_attempts": 0},
            {"verification_attempts": 6},
            {"verification_retry_delay_seconds": -0.1},
            {"verification_retry_delay_seconds": 11},
        )

        for values in invalid_values:
            with self.subTest(values=values):
                task = {
                    "name": "invalid_retry",
                    "steps": [
                        {
                            "type": "verify_vision",
                            "prompt": "结果是否正确？",
                            **values,
                        }
                    ],
                }
                with self.assertRaises(ValidationError):
                    TaskDefinition.model_validate(task)

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
        self.assertEqual(
            rendered.steps[1].condition.prompt,
            "结果是否为 391？",
        )
        self.assertEqual(rendered.steps[2].keys, ["enter"])
        self.assertEqual(rendered.steps[3].prompt, "结果是否为 391？")
        self.assertEqual(rendered.steps[4].summary, "17*23=391")
        self.assertEqual(task.app, "${app_name}")
        self.assertEqual(
            task.steps[1].content,
            "${left}${operator}${right}",
        )
        self.assertEqual(
            task.steps[1].condition.prompt,
            "结果是否为 ${expected}？",
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

    def test_activate_app_is_parsed(self):
        task = TaskDefinition.model_validate(
            {
                "name": "activate_app",
                "steps": [
                    {
                        "type": "activate_app",
                        "app": "Safari",
                    }
                ],
            }
        )

        self.assertEqual(
            task.steps[0].type,
            ActionType.ACTIVATE_APP,
        )
        self.assertEqual(task.steps[0].app, "Safari")

    def test_activate_app_requires_app(self):
        task = {
            "name": "missing_app",
            "steps": [{"type": "activate_app"}],
        }

        with self.assertRaisesRegex(
            ValidationError,
            "activate_app requires app",
        ):
            TaskDefinition.model_validate(task)

    def test_close_document_is_parsed(self):
        task = TaskDefinition.model_validate(
            {
                "name": "close_document",
                "steps": [
                    {
                        "type": "close_document",
                        "app": "文本编辑",
                        "save_changes": False,
                    }
                ],
            }
        )

        self.assertEqual(
            task.steps[0].type,
            ActionType.CLOSE_DOCUMENT,
        )
        self.assertEqual(task.steps[0].app, "文本编辑")
        self.assertFalse(task.steps[0].save_changes)

    def test_close_document_requires_app(self):
        with self.assertRaisesRegex(
            ValidationError,
            "close_document requires app",
        ):
            TaskDefinition.model_validate(
                {
                    "name": "missing_app",
                    "steps": [{"type": "close_document"}],
                }
            )

    def test_approval_requires_prompt(self):
        task = TaskDefinition.model_validate(
            {
                "name": "approval",
                "steps": [
                    {
                        "type": "approval",
                        "prompt": "是否允许继续？",
                    }
                ],
            }
        )

        self.assertEqual(task.steps[0].type, ActionType.APPROVAL)
        self.assertEqual(task.steps[0].prompt, "是否允许继续？")

        with self.assertRaisesRegex(
            ValidationError,
            "approval requires prompt",
        ):
            TaskDefinition.model_validate(
                {
                    "name": "missing_prompt",
                    "steps": [{"type": "approval"}],
                }
            )

    def test_click_element_is_parsed_and_rendered(self):
        task = TaskDefinition.model_validate(
            {
                "name": "element_click",
                "parameters": {"button_name": {}},
                "steps": [
                    {
                        "type": "click_element",
                        "app": "计算器",
                        "element": {
                            "role": "AXButton",
                            "text": "${button_name}",
                            "title": "${button_name}",
                            "match_index": 0,
                        },
                    }
                ],
            }
        )

        rendered = task.render_parameters(
            {"button_name": "7"}
        )

        self.assertEqual(
            rendered.steps[0].type,
            ActionType.CLICK_ELEMENT,
        )
        self.assertEqual(rendered.steps[0].app, "计算器")
        self.assertEqual(rendered.steps[0].element.role, "AXButton")
        self.assertEqual(rendered.steps[0].element.text, "7")
        self.assertEqual(rendered.steps[0].element.title, "7")

    def test_click_element_requires_app_and_locator(self):
        invalid_steps = (
            {
                "type": "click_element",
                "element": {"role": "AXButton"},
            },
            {
                "type": "click_element",
                "app": "计算器",
            },
        )
        for step in invalid_steps:
            with self.subTest(step=step):
                with self.assertRaises(ValidationError):
                    TaskDefinition.model_validate(
                        {
                            "name": "invalid_element_click",
                            "steps": [step],
                        }
                    )

    def test_element_locator_requires_criterion(self):
        with self.assertRaisesRegex(
            ValidationError,
            "at least one criterion",
        ):
            UIElementLocator()

    def test_read_element_is_parsed_and_validates_output_name(self):
        task = TaskDefinition.model_validate(
            {
                "name": "read_element",
                "steps": [
                    {
                        "type": "read_element",
                        "app": "计算器",
                        "output": "display_value",
                        "read_attribute": "value",
                        "element": {
                            "role": "AXStaticText",
                        },
                    }
                ],
            }
        )

        self.assertEqual(task.steps[0].type, ActionType.READ_ELEMENT)
        self.assertEqual(task.steps[0].output, "display_value")
        self.assertEqual(task.steps[0].read_attribute, "value")

        with self.assertRaises(ValidationError):
            TaskDefinition.model_validate(
                {
                    "name": "invalid_output",
                    "steps": [
                        {
                            "type": "read_element",
                            "app": "计算器",
                            "output": "invalid-name",
                            "element": {"role": "AXStaticText"},
                        }
                    ],
                }
            )

    def test_render_parameters_can_preserve_runtime_outputs(self):
        task = TaskDefinition.model_validate(
            {
                "name": "runtime_render",
                "parameters": {"prefix": {"default": "value"}},
                "steps": [
                    {
                        "type": "read_element",
                        "app": "计算器",
                        "output": "display_value",
                        "element": {"role": "AXStaticText"},
                    },
                    {
                        "type": "write",
                        "content": "${prefix}-${display_value}",
                    },
                ],
            }
        )

        rendered = task.render_parameters(
            {"prefix": "value"},
            preserve_placeholders={"display_value"},
        )

        self.assertEqual(
            rendered.steps[1].content,
            "value-${display_value}",
        )

    def test_runtime_outputs_must_be_unique_and_not_parameters(self):
        duplicate = {
            "name": "duplicate_outputs",
            "steps": [
                {
                    "type": "read_element",
                    "app": "计算器",
                    "output": "result",
                    "element": {"role": "AXStaticText"},
                },
                {
                    "type": "read_element",
                    "app": "计算器",
                    "output": "result",
                    "element": {"role": "AXStaticText"},
                },
            ],
        }
        with self.assertRaisesRegex(
            ValidationError,
            "duplicate runtime outputs",
        ):
            TaskDefinition.model_validate(duplicate)

        conflict = {
            "name": "conflicting_output",
            "parameters": {"result": {}},
            "steps": [
                {
                    "type": "read_element",
                    "app": "计算器",
                    "output": "result",
                    "element": {"role": "AXStaticText"},
                }
            ],
        }
        with self.assertRaisesRegex(
            ValidationError,
            "conflict with task parameters",
        ):
            TaskDefinition.model_validate(conflict)

    def test_step_accepts_vision_condition(self):
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
                            "expected": True,
                        },
                    }
                ],
            }
        )

        condition = task.steps[0].condition
        self.assertIsNotNone(condition)
        self.assertEqual(condition.type, ConditionType.VISION)
        self.assertEqual(condition.prompt, "编辑区域是否已打开？")

    def test_step_rejects_invalid_nested_condition(self):
        with self.assertRaises(ValidationError):
            TaskDefinition.model_validate(
                {
                    "name": "invalid_condition",
                    "steps": [
                        {
                            "type": "write",
                            "content": "conditional",
                            "condition": {
                                "type": "vision",
                                "prompt": " ",
                            },
                        }
                    ],
                }
            )

    def test_step_accepts_loop_configuration(self):
        task = TaskDefinition.model_validate(
            {
                "name": "looped_task",
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

        loop = task.steps[0].loop
        self.assertIsNotNone(loop)
        self.assertEqual(loop.count, 3)
        self.assertEqual(loop.delay_seconds, 0.2)

    def test_loop_rejects_invalid_count_and_delay(self):
        invalid_values = (
            {"count": 0},
            {"count": 21},
            {"count": 2, "delay_seconds": -0.1},
            {"count": 2, "delay_seconds": 11},
        )

        for values in invalid_values:
            with self.subTest(values=values):
                with self.assertRaises(ValidationError):
                    TaskLoop(**values)

    def test_loop_rejects_non_repeatable_action_types(self):
        task_steps = (
            {
                "type": "verify_vision",
                "prompt": "结果是否正确？",
                "loop": {"count": 2},
            },
            {
                "type": "done",
                "summary": "finished",
                "loop": {"count": 2},
            },
        )

        for step in task_steps:
            with self.subTest(action_type=step["type"]):
                with self.assertRaisesRegex(
                    ValidationError,
                    "loop is not supported",
                ):
                    TaskDefinition.model_validate(
                        {
                            "name": "invalid_loop",
                            "steps": [step],
                        }
                    )

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
        self.assertEqual(
            dataset.task,
            "tasks/calculator_parameterized.json",
        )
        self.assertIsNone(dataset.workflow)
        self.assertEqual(len(dataset.cases), 2)
        self.assertEqual(dataset.cases[0].parameters, {"right": "23"})
        self.assertEqual(dataset.cases[0].attempts, 1)
        self.assertEqual(dataset.cases[0].retry_delay_seconds, 0.5)

    def test_case_accepts_retry_attempts(self):
        dataset_data = {
            **self.valid_dataset,
            "cases": [
                {
                    "name": "retry_case",
                    "parameters": {"right": "23"},
                    "attempts": 2,
                    "retry_delay_seconds": 0.25,
                }
            ],
        }

        dataset = TaskDatasetDefinition.model_validate(dataset_data)

        self.assertEqual(dataset.cases[0].attempts, 2)
        self.assertEqual(dataset.cases[0].retry_delay_seconds, 0.25)

    def test_case_rejects_invalid_retry_attempts(self):
        for attempts in (0, 4):
            with self.subTest(attempts=attempts):
                dataset_data = {
                    **self.valid_dataset,
                    "cases": [
                        {
                            "name": "retry_case",
                            "parameters": {},
                            "attempts": attempts,
                        }
                    ],
                }
                with self.assertRaises(ValidationError):
                    TaskDatasetDefinition.model_validate(dataset_data)

    def test_case_rejects_invalid_retry_delay(self):
        for delay in (-0.1, 11):
            with self.subTest(delay=delay):
                dataset_data = {
                    **self.valid_dataset,
                    "cases": [
                        {
                            "name": "retry_case",
                            "parameters": {},
                            "retry_delay_seconds": delay,
                        }
                    ],
                }
                with self.assertRaises(ValidationError):
                    TaskDatasetDefinition.model_validate(dataset_data)

    def test_dataset_requires_exactly_one_case_source(self):
        dataset_data = {**self.valid_dataset, "cases": []}

        with self.assertRaisesRegex(
            ValidationError,
            "exactly one of cases or data_source",
        ):
            TaskDatasetDefinition.model_validate(dataset_data)

    def test_dataset_accepts_csv_data_source(self):
        dataset = TaskDatasetDefinition.model_validate(
            {
                "name": "calculator_csv",
                "task": "tasks/calculator_parameterized.json",
                "data_source": {
                    "type": "csv",
                    "path": "calculator_rows.csv",
                    "case_name_column": "case_id",
                    "parameters": {
                        "left": "left",
                        "right": "right",
                    },
                },
            }
        )

        self.assertEqual(dataset.cases, [])
        self.assertEqual(dataset.data_source.path, "calculator_rows.csv")
        self.assertEqual(dataset.data_source.attempts, 1)
        self.assertEqual(
            dataset.data_source.parameters,
            {"left": "left", "right": "right"},
        )

    def test_dataset_accepts_workflow_target(self):
        dataset = TaskDatasetDefinition.model_validate(
            {
                "name": "workflow_cases",
                "workflow": "workflows/customer_update.json",
                "cases": [
                    {
                        "name": "customer_01",
                        "parameters": {"customer_name": "张三"},
                    }
                ],
            }
        )

        self.assertIsNone(dataset.task)
        self.assertEqual(
            dataset.workflow,
            "workflows/customer_update.json",
        )

    def test_dataset_requires_exactly_one_target(self):
        invalid_payloads = [
            {
                "name": "missing_target",
                "cases": [{"name": "case", "parameters": {}}],
            },
            {
                "name": "two_targets",
                "task": "tasks/task.json",
                "workflow": "workflows/workflow.json",
                "cases": [{"name": "case", "parameters": {}}],
            },
        ]

        for payload in invalid_payloads:
            with self.subTest(payload=payload):
                with self.assertRaisesRegex(
                    ValidationError,
                    "exactly one of task or workflow",
                ):
                    TaskDatasetDefinition.model_validate(payload)

    def test_dataset_rejects_empty_workflow_target(self):
        with self.assertRaises(ValidationError):
            TaskDatasetDefinition.model_validate(
                {
                    "name": "empty_workflow",
                    "workflow": " ",
                    "cases": [{"name": "case", "parameters": {}}],
                }
            )

    def test_dataset_rejects_cases_with_data_source(self):
        dataset_data = {
            **self.valid_dataset,
            "data_source": {
                "type": "csv",
                "path": "calculator_rows.csv",
            },
        }

        with self.assertRaisesRegex(
            ValidationError,
            "exactly one of cases or data_source",
        ):
            TaskDatasetDefinition.model_validate(dataset_data)

    def test_csv_source_rejects_invalid_parameter_mapping(self):
        for parameters in (
            {"17x": "left"},
            {"left": " "},
        ):
            with self.subTest(parameters=parameters):
                with self.assertRaises(ValidationError):
                    TaskDatasetDefinition.model_validate(
                        {
                            "name": "invalid_csv",
                            "task": "task.json",
                            "data_source": {
                                "type": "csv",
                                "path": "rows.csv",
                                "parameters": parameters,
                            },
                        }
                    )

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


class WorkflowDefinitionTests(unittest.TestCase):
    def valid_workflow(self):
        return {
            "name": "customer_update",
            "description": "登录、查询并更新客户",
            "parameters": {
                "customer_name": {},
                "operator": {"default": "*"},
            },
            "task_files": [
                "tasks/login.json",
                "tasks/find_customer.json",
                "tasks/update_customer.json",
            ],
            "cleanup_task": "tasks/logout.json",
        }

    def test_valid_workflow_is_parsed(self):
        workflow = WorkflowDefinition.model_validate(
            self.valid_workflow()
        )

        self.assertEqual(workflow.name, "customer_update")
        self.assertEqual(len(workflow.task_files), 3)
        self.assertEqual(workflow.cleanup_task, "tasks/logout.json")

    def test_workflow_resolves_defaults_and_overrides(self):
        workflow = WorkflowDefinition.model_validate(
            self.valid_workflow()
        )

        resolved = workflow.resolve_parameters(
            {"customer_name": "张三"}
        )

        self.assertEqual(
            resolved,
            {"customer_name": "张三", "operator": "*"},
        )

    def test_workflow_rejects_missing_and_unknown_parameters(self):
        workflow = WorkflowDefinition.model_validate(
            self.valid_workflow()
        )

        with self.assertRaisesRegex(
            ValueError,
            "missing workflow parameters: customer_name",
        ):
            workflow.resolve_parameters()
        with self.assertRaisesRegex(
            ValueError,
            "unknown workflow parameters: unsupported",
        ):
            workflow.resolve_parameters(
                {
                    "customer_name": "张三",
                    "unsupported": "value",
                }
            )

    def test_workflow_rejects_non_string_parameter_values(self):
        workflow = WorkflowDefinition.model_validate(
            self.valid_workflow()
        )

        with self.assertRaisesRegex(
            ValueError,
            "workflow parameter overrides must be strings: customer_name",
        ):
            workflow.resolve_parameters({"customer_name": 123})

    def test_workflow_rejects_invalid_task_files(self):
        for task_files in (
            [],
            ["tasks/login.json", " "],
            ["tasks/login.json", "tasks/login.json"],
        ):
            with self.subTest(task_files=task_files):
                payload = {
                    **self.valid_workflow(),
                    "task_files": task_files,
                }
                with self.assertRaises(ValidationError):
                    WorkflowDefinition.model_validate(payload)

    def test_workflow_rejects_empty_cleanup_task(self):
        payload = {
            **self.valid_workflow(),
            "cleanup_task": " ",
        }

        with self.assertRaises(ValidationError):
            WorkflowDefinition.model_validate(payload)


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

    def test_task_result_serializes_condition_diagnostics(self):
        started_at = datetime(2026, 11, 23, tzinfo=timezone.utc)
        result = TaskResult(
            task_name="conditional_task",
            status=TaskStatus.PASSED,
            started_at=started_at,
            finished_at=started_at,
            steps=[
                StepResult(
                    index=0,
                    type=ActionType.WAIT,
                    status=StepStatus.SKIPPED,
                    started_at=started_at,
                    finished_at=started_at,
                    condition_prompt="结果是否为 999？",
                    condition_expected=True,
                    condition_actual=False,
                    condition_duration_seconds=1.25,
                    condition_screenshot="artifacts/condition.png",
                )
            ],
        )

        payload = result.model_dump_json()

        self.assertIn('"condition_prompt":"结果是否为 999？"', payload)
        self.assertIn('"condition_expected":true', payload)
        self.assertIn('"condition_actual":false', payload)
        self.assertIn('"condition_duration_seconds":1.25', payload)
        self.assertIn(
            '"condition_screenshot":"artifacts/condition.png"',
            payload,
        )

    def test_task_result_serializes_loop_diagnostics(self):
        started_at = datetime(2026, 11, 23, tzinfo=timezone.utc)
        result = TaskResult(
            task_name="looped_task",
            status=TaskStatus.PASSED,
            started_at=started_at,
            finished_at=started_at,
            steps=[
                StepResult(
                    index=0,
                    type=ActionType.PRESS,
                    status=StepStatus.PASSED,
                    started_at=started_at,
                    finished_at=started_at,
                    loop_count=3,
                    loop_iterations_completed=3,
                    loop_delay_seconds=0.2,
                )
            ],
        )

        payload = result.model_dump_json()

        self.assertIn('"loop_count":3', payload)
        self.assertIn('"loop_iterations_completed":3', payload)
        self.assertIn('"loop_delay_seconds":0.2', payload)


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

    def test_workflow_case_result_is_supported(self):
        started_at = datetime(2026, 11, 25, tzinfo=timezone.utc)
        workflow_result = WorkflowResult(
            workflow_name="customer_update",
            status=TaskStatus.PASSED,
            started_at=started_at,
            finished_at=started_at,
            duration_seconds=2.5,
            report_path="reports/customer_update.json",
        )
        case_result = TaskCaseResult(
            name="customer_01",
            parameters={"customer_name": "张三"},
            status=TaskStatus.PASSED,
            duration_seconds=2.5,
            workflow_result=workflow_result,
        )

        self.assertEqual(case_result.target_type.value, "workflow")
        self.assertEqual(
            case_result.report_path,
            "reports/customer_update.json",
        )
        self.assertIsNone(case_result.failure_log)
        payload = case_result.model_dump_json()
        self.assertIn('"workflow_name":"customer_update"', payload)
        self.assertIn('"task_result":null', payload)

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

    def test_dataset_result_aggregates_case_counts(self):
        started_at = datetime(2026, 11, 20, tzinfo=timezone.utc)
        statuses = (
            TaskStatus.PASSED,
            TaskStatus.FAILED,
            TaskStatus.TIMED_OUT,
            TaskStatus.CANCELLED,
        )
        case_results = [
            TaskCaseResult(
                name=f"case_{status.value}",
                status=status,
                task_result=self.make_task_result(status=status),
            )
            for status in statuses
        ]
        dataset_result = TaskDatasetResult(
            dataset_name="mixed_results",
            status=TaskStatus.FAILED,
            started_at=started_at,
            cases=case_results,
        )

        self.assertEqual(dataset_result.total, 4)
        self.assertEqual(dataset_result.passed, 1)
        self.assertEqual(dataset_result.failed, 1)
        self.assertEqual(dataset_result.timed_out, 1)
        self.assertEqual(dataset_result.cancelled, 1)
        self.assertFalse(dataset_result.successful)


if __name__ == "__main__":
    unittest.main()
