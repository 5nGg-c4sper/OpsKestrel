"""Tests for loading workflow definitions and task paths."""

import json
import tempfile
import unittest
from pathlib import Path

from soc_agent.workflows import WorkflowLoadError, load_workflow


class WorkflowLoaderTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        self.tasks_dir = self.root / "tasks"
        self.workflows_dir = self.root / "workflows"
        self.tasks_dir.mkdir()
        self.workflows_dir.mkdir()

    def write_task(self, name):
        path = self.tasks_dir / name
        path.write_text(
            json.dumps(
                {
                    "name": path.stem,
                    "steps": [
                        {"type": "done", "summary": "finished"}
                    ],
                }
            ),
            encoding="utf-8",
        )
        return path

    def write_workflow(self, payload):
        path = self.workflows_dir / "workflow.json"
        path.write_text(
            json.dumps(payload, ensure_ascii=False),
            encoding="utf-8",
        )
        return path

    def valid_payload(self):
        return {
            "name": "customer_update",
            "parameters": {
                "customer_name": {},
                "operator": {"default": "*"},
            },
            "task_files": [
                "../tasks/login.json",
                "../tasks/update_customer.json",
            ],
            "cleanup_task": "../tasks/logout.json",
        }

    def test_loads_ordered_tasks_and_resolves_parameters(self):
        for name in (
            "login.json",
            "update_customer.json",
            "logout.json",
        ):
            self.write_task(name)
        workflow_path = self.write_workflow(self.valid_payload())

        loaded = load_workflow(
            workflow_path,
            {"customer_name": "张三"},
        )

        self.assertEqual(loaded.workflow_path, workflow_path.resolve())
        self.assertEqual(
            loaded.task_paths,
            [
                (self.tasks_dir / "login.json").resolve(),
                (self.tasks_dir / "update_customer.json").resolve(),
            ],
        )
        self.assertEqual(
            loaded.cleanup_task_path,
            (self.tasks_dir / "logout.json").resolve(),
        )
        self.assertEqual(
            loaded.parameters,
            {"customer_name": "张三", "operator": "*"},
        )

    def test_rejects_missing_workflow_file(self):
        with self.assertRaisesRegex(
            WorkflowLoadError,
            "failed to read workflow",
        ):
            load_workflow(self.root / "missing.json")

    def test_rejects_invalid_workflow_json(self):
        workflow_path = self.workflows_dir / "workflow.json"
        workflow_path.write_text("{invalid", encoding="utf-8")

        with self.assertRaisesRegex(
            WorkflowLoadError,
            "invalid JSON in workflow",
        ):
            load_workflow(workflow_path)

    def test_rejects_invalid_workflow_definition(self):
        payload = {
            **self.valid_payload(),
            "task_files": [],
        }
        workflow_path = self.write_workflow(payload)

        with self.assertRaisesRegex(
            WorkflowLoadError,
            "invalid workflow",
        ):
            load_workflow(workflow_path)

    def test_rejects_missing_task_file(self):
        self.write_task("login.json")
        workflow_path = self.write_workflow(self.valid_payload())

        with self.assertRaisesRegex(
            WorkflowLoadError,
            "workflow task file is missing",
        ):
            load_workflow(
                workflow_path,
                {"customer_name": "张三"},
            )

    def test_rejects_missing_cleanup_task(self):
        self.write_task("login.json")
        self.write_task("update_customer.json")
        workflow_path = self.write_workflow(self.valid_payload())

        with self.assertRaisesRegex(
            WorkflowLoadError,
            "logout.json",
        ):
            load_workflow(
                workflow_path,
                {"customer_name": "张三"},
            )

    def test_rejects_missing_parameter_before_returning(self):
        for name in (
            "login.json",
            "update_customer.json",
            "logout.json",
        ):
            self.write_task(name)
        workflow_path = self.write_workflow(self.valid_payload())

        with self.assertRaisesRegex(
            WorkflowLoadError,
            "missing workflow parameters: customer_name",
        ):
            load_workflow(workflow_path)

    def test_rejects_duplicate_paths_after_resolution(self):
        self.write_task("login.json")
        payload = {
            "name": "duplicate_resolved_tasks",
            "task_files": [
                "../tasks/login.json",
                "../tasks/./login.json",
            ],
        }
        workflow_path = self.write_workflow(payload)

        with self.assertRaisesRegex(
            WorkflowLoadError,
            "duplicate task file",
        ):
            load_workflow(workflow_path)


if __name__ == "__main__":
    unittest.main()
