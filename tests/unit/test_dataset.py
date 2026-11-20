"""Contract tests for shipped task datasets."""

import json
import tempfile
import unittest
from pathlib import Path

from soc_agent.datasets import DatasetLoadError, load_dataset
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


class DatasetLoaderTests(unittest.TestCase):
    def test_load_dataset_resolves_relative_task_path(self):
        dataset_path = PROJECT_ROOT / "datasets" / "calculator_cases.json"

        loaded = load_dataset(dataset_path)

        self.assertEqual(
            loaded.definition.name,
            "calculator_regression",
        )
        self.assertEqual(
            loaded.dataset_path,
            dataset_path.resolve(),
        )
        self.assertEqual(
            loaded.task_path,
            (
                PROJECT_ROOT / "tasks" / "calculator_parameterized.json"
            ).resolve(),
        )
        self.assertTrue(loaded.task_path.is_file())

    def test_load_dataset_rejects_missing_task_file(self):
        dataset_payload = {
            "name": "missing_task",
            "task": "missing-task.json",
            "cases": [{"name": "case", "parameters": {}}],
        }

        with tempfile.TemporaryDirectory() as directory:
            dataset_path = Path(directory) / "dataset.json"
            dataset_path.write_text(
                json.dumps(dataset_payload),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                DatasetLoadError,
                "task file is missing or not a file",
            ):
                load_dataset(dataset_path)

    def test_load_dataset_rejects_missing_dataset_file(self):
        missing_path = PROJECT_ROOT / "datasets" / "missing.json"

        with self.assertRaisesRegex(
            DatasetLoadError,
            "failed to read dataset",
        ):
            load_dataset(missing_path)


if __name__ == "__main__":
    unittest.main()
