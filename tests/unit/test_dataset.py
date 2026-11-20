"""Contract tests for shipped task datasets."""

import json
import unittest
from pathlib import Path

from soc_agent.task_models import TaskDatasetDefinition


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class DatasetFileTests(unittest.TestCase):
    def test_calculator_dataset_is_valid(self):
        dataset_path = PROJECT_ROOT / "datasets" / "calculator_cases.json"
        dataset = TaskDatasetDefinition.model_validate(
            json.loads(dataset_path.read_text(encoding="utf-8"))
        )

        self.assertEqual(dataset.name, "calculator_regression")
        self.assertEqual(
            [case.name for case in dataset.cases],
            ["default_17x23", "custom_3x4"],
        )
        self.assertEqual(
            dataset.cases[0].parameters,
            {"right": "23"},
        )
        self.assertEqual(
            dataset.cases[1].parameters,
            {
                "left": "3",
                "right": "4",
                "expected_result": "12",
            },
        )

        task_path = (dataset_path.parent / dataset.task).resolve()
        self.assertTrue(task_path.is_file())


if __name__ == "__main__":
    unittest.main()
