"""Tests for sequential workflow execution."""

import unittest
from datetime import datetime, timezone
from pathlib import Path

from opskestrel.task_models import (
    RuntimeVariableRecord,
    StepPhase,
    TaskDefinition,
    TaskResult,
    TaskStatus,
    WorkflowDefinition,
)
from opskestrel.workflow_runner import WorkflowRunner, WorkflowRunnerError
from opskestrel.workflows import LoadedWorkflow


class WorkflowRunnerTests(unittest.TestCase):
    def make_task_definition(self, name, parameters):
        return TaskDefinition.model_validate(
            {
                "name": name,
                "parameters": parameters,
                "steps": [
                    {"type": "done", "summary": "finished"}
                ],
            }
        )

    def make_loaded_workflow(
        self,
        task_names,
        parameters,
        cleanup_name=None,
    ):
        task_paths = [
            Path("/tmp") / f"{name}.json"
            for name in task_names
        ]
        cleanup_task_path = (
            Path("/tmp") / f"{cleanup_name}.json"
            if cleanup_name
            else None
        )
        payload = {
            "name": "test_workflow",
            "parameters": {
                name: {} for name in parameters
            },
            "task_files": [str(path) for path in task_paths],
        }
        if cleanup_task_path is not None:
            payload["cleanup_task"] = str(cleanup_task_path)
        return LoadedWorkflow(
            definition=WorkflowDefinition.model_validate(payload),
            workflow_path=Path("/tmp/workflow.json"),
            task_paths=task_paths,
            cleanup_task_path=cleanup_task_path,
            parameters=dict(parameters),
        )

    def make_task_result(self, name, status, error=None):
        timestamp = datetime(2026, 11, 25, tzinfo=timezone.utc)
        return TaskResult(
            task_name=name,
            status=status,
            started_at=timestamp,
            finished_at=timestamp,
            duration_seconds=0.1,
            error=error,
        )

    def test_runs_tasks_in_order_with_only_declared_parameters(self):
        loaded = self.make_loaded_workflow(
            ["login", "update_customer"],
            {
                "customer_name": "张三",
                "note": "首次联系",
                "unused": "ignored",
            },
        )
        definitions = {
            loaded.task_paths[0]: self.make_task_definition(
                "login",
                {"customer_name": {}},
            ),
            loaded.task_paths[1]: self.make_task_definition(
                "update_customer",
                {"note": {}},
            ),
        }
        calls = []

        def execute_task(path, parameters, runtime_values):
            calls.append((path.name, parameters))
            return self.make_task_result(
                definitions[path].name,
                TaskStatus.PASSED,
            )

        result = WorkflowRunner(
            execute_task,
            task_loader=definitions.__getitem__,
        ).run(loaded)

        self.assertEqual(
            calls,
            [
                ("login.json", {"customer_name": "张三"}),
                ("update_customer.json", {"note": "首次联系"}),
            ],
        )
        self.assertEqual(result.status, TaskStatus.PASSED)
        self.assertTrue(result.successful)
        self.assertEqual(result.total, 2)
        self.assertEqual(result.passed, 2)
        self.assertFalse(result.stopped_early)
        self.assertEqual(
            [item.phase for item in result.task_results],
            [StepPhase.MAIN, StepPhase.MAIN],
        )

    def test_failure_stops_main_tasks_and_always_runs_cleanup(self):
        loaded = self.make_loaded_workflow(
            ["login", "update_customer", "verify"],
            {"customer_name": "张三"},
            cleanup_name="logout",
        )
        definitions = {
            loaded.task_paths[0]: self.make_task_definition(
                "login",
                {"customer_name": {}},
            ),
            loaded.task_paths[1]: self.make_task_definition(
                "update_customer",
                {"customer_name": {}},
            ),
            loaded.task_paths[2]: self.make_task_definition(
                "verify",
                {"customer_name": {}},
            ),
            loaded.cleanup_task_path: self.make_task_definition(
                "logout",
                {"customer_name": {}},
            ),
        }
        calls = []

        def execute_task(path, parameters, runtime_values):
            calls.append(path.name)
            if path.name == "login.json":
                return self.make_task_result(
                    "login",
                    TaskStatus.FAILED,
                    "login failed",
                )
            return self.make_task_result(
                definitions[path].name,
                TaskStatus.PASSED,
            )

        result = WorkflowRunner(
            execute_task,
            task_loader=definitions.__getitem__,
        ).run(loaded)

        self.assertEqual(calls, ["login.json", "logout.json"])
        self.assertEqual(result.status, TaskStatus.FAILED)
        self.assertEqual(result.error, "login failed")
        self.assertTrue(result.stopped_early)
        self.assertEqual(result.total, 1)
        self.assertEqual(result.cleanup_result.phase, StepPhase.CLEANUP)
        self.assertEqual(
            result.cleanup_result.parameters,
            {"customer_name": "张三"},
        )

    def test_cleanup_failure_changes_passed_workflow_to_failed(self):
        loaded = self.make_loaded_workflow(
            ["main"],
            {},
            cleanup_name="cleanup",
        )
        definitions = {
            loaded.task_paths[0]: self.make_task_definition(
                "main",
                {},
            ),
            loaded.cleanup_task_path: self.make_task_definition(
                "cleanup",
                {},
            ),
        }

        def execute_task(path, parameters, runtime_values):
            status = (
                TaskStatus.FAILED
                if path.name == "cleanup.json"
                else TaskStatus.PASSED
            )
            return self.make_task_result(
                definitions[path].name,
                status,
                "cleanup failed" if status == TaskStatus.FAILED else None,
            )

        result = WorkflowRunner(
            execute_task,
            task_loader=definitions.__getitem__,
        ).run(loaded)

        self.assertEqual(result.status, TaskStatus.FAILED)
        self.assertEqual(result.error, "cleanup failed")
        self.assertFalse(result.successful)

    def test_executor_exception_becomes_failed_task_and_runs_cleanup(self):
        loaded = self.make_loaded_workflow(
            ["main"],
            {},
            cleanup_name="cleanup",
        )
        definitions = {
            loaded.task_paths[0]: self.make_task_definition(
                "main",
                {},
            ),
            loaded.cleanup_task_path: self.make_task_definition(
                "cleanup",
                {},
            ),
        }
        calls = []

        def execute_task(path, parameters, runtime_values):
            calls.append(path.name)
            if path.name == "main.json":
                raise RuntimeError("executor crashed")
            return self.make_task_result(
                definitions[path].name,
                TaskStatus.PASSED,
            )

        result = WorkflowRunner(
            execute_task,
            task_loader=definitions.__getitem__,
        ).run(loaded)

        self.assertEqual(calls, ["main.json", "cleanup.json"])
        self.assertEqual(result.status, TaskStatus.FAILED)
        self.assertEqual(result.task_results[0].error, "executor crashed")
        self.assertEqual(
            result.cleanup_result.status,
            TaskStatus.PASSED,
        )

    def test_missing_child_parameter_fails_before_execution(self):
        loaded = self.make_loaded_workflow(
            ["main"],
            {"customer_name": "张三"},
        )
        definitions = {
            loaded.task_paths[0]: self.make_task_definition(
                "main",
                {"note": {}},
            ),
        }
        calls = []

        with self.assertRaisesRegex(
            WorkflowRunnerError,
            "requires parameters not provided by the workflow: note",
        ):
            WorkflowRunner(
                lambda path, parameters, runtime_values: calls.append(path),
                task_loader=definitions.__getitem__,
            ).run(loaded)

        self.assertEqual(calls, [])

    def test_runtime_value_is_passed_to_later_child_task(self):
        loaded = self.make_loaded_workflow(
            ["read_value", "write_value"],
            {},
        )
        definitions = {
            loaded.task_paths[0]: TaskDefinition.model_validate(
                {
                    "name": "read_value",
                    "steps": [
                        {
                            "type": "read_element",
                            "app": "计算器",
                            "output": "result",
                            "element": {"role": "AXStaticText"},
                        }
                    ],
                }
            ),
            loaded.task_paths[1]: TaskDefinition.model_validate(
                {
                    "name": "write_value",
                    "steps": [
                        {"type": "write", "content": "${result}"},
                        {"type": "done", "summary": "finished"},
                    ],
                }
            ),
        }
        seen_runtime_values = []

        def execute_task(path, parameters, runtime_values):
            seen_runtime_values.append(
                (path.name, dict(runtime_values))
            )
            if path.name == "read_value.json":
                timestamp = self.make_task_result(
                    "read_value",
                    TaskStatus.PASSED,
                )
                timestamp.runtime_values = {"result": "391"}
                timestamp.runtime_variables = {
                    "result": RuntimeVariableRecord(
                        name="result",
                        source_task="read_value",
                        value="391",
                    )
                }
                return timestamp
            return self.make_task_result(
                "write_value",
                TaskStatus.PASSED,
            )

        result = WorkflowRunner(
            execute_task,
            task_loader=definitions.__getitem__,
        ).run(loaded)

        self.assertEqual(
            seen_runtime_values[1],
            ("write_value.json", {"result": "391"}),
        )
        self.assertEqual(
            result.runtime_variables["result"].source_task,
            "read_value",
        )
        self.assertEqual(
            result.runtime_variables["result"].value,
            "391",
        )


if __name__ == "__main__":
    unittest.main()
