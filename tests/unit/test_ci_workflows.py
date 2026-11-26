"""Tests for CI workflow safety and runner configuration."""

import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
GUI_WORKFLOW = (
    PROJECT_ROOT / ".github" / "workflows" / "macos-gui-smoke.yml"
)
POSTGRES_WORKFLOW = (
    PROJECT_ROOT
    / ".github"
    / "workflows"
    / "postgres-integration.yml"
)


class MacOSGUIWorkflowTests(unittest.TestCase):
    def test_gui_workflow_is_manual_and_uses_dedicated_runner(self):
        workflow = GUI_WORKFLOW.read_text(encoding="utf-8")

        self.assertIn("workflow_dispatch:", workflow)
        self.assertNotIn("  push:", workflow)
        self.assertNotIn("  pull_request:", workflow)
        self.assertIn(
            "runs-on: [self-hosted, macOS, soc-gui]",
            workflow,
        )
        self.assertIn("TASK_PATH: ${{ inputs.task }}", workflow)
        self.assertIn('run "$TASK_PATH"', workflow)
        self.assertIn("--non-interactive", workflow)
        self.assertIn(
            "if: ${{ always() && inputs.upload_reports }}",
            workflow,
        )


class PostgreSQLWorkflowTests(unittest.TestCase):
    def test_postgres_workflow_runs_integration_suite(self):
        workflow = POSTGRES_WORKFLOW.read_text(encoding="utf-8")

        self.assertIn("image: postgres:16-alpine", workflow)
        self.assertIn("SOC_TEST_POSTGRES_DSN", workflow)
        self.assertIn("requirements-integration.txt", workflow)
        self.assertIn(
            "python -m unittest discover",
            workflow,
        )
        self.assertIn("-s tests/integration", workflow)


if __name__ == "__main__":
    unittest.main()
