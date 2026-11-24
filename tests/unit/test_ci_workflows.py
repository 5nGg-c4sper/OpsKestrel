"""Tests for CI workflow safety and runner configuration."""

import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
GUI_WORKFLOW = (
    PROJECT_ROOT / ".github" / "workflows" / "macos-gui-smoke.yml"
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


if __name__ == "__main__":
    unittest.main()
