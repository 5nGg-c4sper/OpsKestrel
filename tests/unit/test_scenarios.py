"""Tests for packaged business scenario definitions."""

import json
import tempfile
import unittest
from pathlib import Path

from soc_agent.scenarios import ScenarioLoadError, load_scenario


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class ScenarioLoaderTests(unittest.TestCase):
    def test_customer_followup_scenario_is_valid(self):
        scenario = load_scenario(
            PROJECT_ROOT
            / "scenarios"
            / "customer_followup"
            / "scenario.json"
        )

        self.assertEqual(
            scenario.definition.name,
            "customer_followup_batch",
        )
        self.assertEqual(
            scenario.definition.required_apps,
            ["文本编辑", "计算器"],
        )
        self.assertEqual(len(scenario.dataset.definition.cases), 3)
        self.assertTrue(scenario.dataset.workflow_path.is_file())

    def test_scenario_rejects_task_dataset(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "task.json").write_text(
                json.dumps(
                    {
                        "name": "task",
                        "steps": [
                            {"type": "done", "summary": "done"}
                        ],
                    }
                ),
                encoding="utf-8",
            )
            (root / "dataset.json").write_text(
                json.dumps(
                    {
                        "name": "task_dataset",
                        "task": "task.json",
                        "cases": [
                            {"name": "case", "parameters": {}}
                        ],
                    }
                ),
                encoding="utf-8",
            )
            scenario_path = root / "scenario.json"
            scenario_path.write_text(
                json.dumps(
                    {
                        "name": "invalid",
                        "dataset": "dataset.json",
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                ScenarioLoadError,
                "must target a workflow",
            ):
                load_scenario(scenario_path)

    def test_scenario_rejects_unknown_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            scenario_path = Path(directory) / "scenario.json"
            scenario_path.write_text(
                json.dumps(
                    {
                        "name": "invalid",
                        "dataset": "dataset.json",
                        "unknown": True,
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                ScenarioLoadError,
                "invalid scenario",
            ):
                load_scenario(scenario_path)
