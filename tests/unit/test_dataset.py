"""Contract tests for shipped task datasets."""

import json
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from soc_agent.dataset_runner import DatasetRunner
from soc_agent.datasets import DatasetLoadError, load_dataset
from soc_agent.task_models import (
    DatasetTargetType,
    TaskDatasetDefinition,
    TaskResult,
    TaskStatus,
    WorkflowResult,
)


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

    def test_failure_diagnostic_dataset_is_valid(self):
        dataset_path = (
            PROJECT_ROOT / "datasets" / "calculator_failure_case.json"
        )
        loaded = load_dataset(dataset_path)
        case = loaded.definition.cases[0]

        self.assertEqual(
            loaded.definition.name,
            "calculator_failure_diagnostic",
        )
        self.assertEqual(len(loaded.definition.cases), 1)
        self.assertEqual(case.name, "expected_result_mismatch")
        self.assertEqual(
            case.parameters,
            {
                "left": "17",
                "right": "23",
                "expected_result": "999",
            },
        )
        self.assertEqual(case.attempts, 1)
        self.assertEqual(case.retry_delay_seconds, 0)
        self.assertTrue(loaded.task_path.is_file())

    def test_calculator_csv_dataset_is_valid(self):
        dataset_path = (
            PROJECT_ROOT / "datasets" / "calculator_csv.json"
        )

        loaded = load_dataset(dataset_path)

        self.assertEqual(
            loaded.definition.name,
            "calculator_csv_regression",
        )
        self.assertEqual(
            [case.name for case in loaded.definition.cases],
            ["case_17x23", "case_125_div_5", "case_3x4"],
        )
        self.assertEqual(
            loaded.definition.cases[0].parameters,
            {
                "left": "17",
                "operator": "*",
                "right": "23",
                "expected_result": "391",
            },
        )

    def test_textedit_csv_dataset_is_valid(self):
        dataset_path = (
            PROJECT_ROOT / "datasets" / "textedit_csv.json"
        )

        loaded = load_dataset(dataset_path)

        self.assertEqual(
            loaded.definition.name,
            "textedit_csv_workflow",
        )
        self.assertEqual(
            [case.name for case in loaded.definition.cases],
            ["record_01", "record_02", "record_03"],
        )
        self.assertEqual(
            loaded.definition.cases[0].parameters,
            {
                "customer_name": "张三",
                "note": "首次联系",
            },
        )
        self.assertEqual(
            loaded.definition.cases[2].parameters,
            {
                "customer_name": "王五",
                "note": "资料已确认",
            },
        )

    def test_textedit_workflow_csv_dataset_is_valid(self):
        dataset_path = (
            PROJECT_ROOT / "datasets" / "textedit_workflow_csv.json"
        )

        loaded = load_dataset(dataset_path)

        self.assertEqual(
            loaded.target_type,
            DatasetTargetType.WORKFLOW,
        )
        self.assertEqual(
            loaded.definition.name,
            "textedit_workflow_batch",
        )
        self.assertEqual(
            loaded.workflow_path,
            (
                PROJECT_ROOT
                / "workflows"
                / "textedit_calculator.json"
            ).resolve(),
        )
        self.assertEqual(
            [case.name for case in loaded.definition.cases],
            ["customer_zhang", "customer_li"],
        )
        self.assertEqual(
            loaded.definition.cases[0].parameters,
            {
                "customer_name": "张三",
                "note": "首次联系",
            },
        )


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
        self.assertEqual(
            loaded.target_type,
            DatasetTargetType.TASK,
        )
        self.assertEqual(loaded.target_path, loaded.task_path)
        self.assertIsNone(loaded.workflow_path)
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

    def test_load_dataset_resolves_csv_source_relative_to_dataset(self):
        loaded = load_dataset(
            PROJECT_ROOT / "datasets" / "calculator_csv.json"
        )

        self.assertEqual(len(loaded.definition.cases), 3)
        self.assertEqual(
            loaded.definition.cases[1].parameters,
            {
                "left": "125",
                "operator": "/",
                "right": "5",
                "expected_result": "25",
            },
        )

    def test_load_dataset_rejects_missing_csv_source(self):
        dataset_payload = {
            "name": "missing_csv",
            "task": "task.json",
            "data_source": {
                "type": "csv",
                "path": "missing.csv",
            },
        }

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "task.json").write_text(
                """
                {
                  "name": "missing_csv_task",
                  "steps": [{"type": "done", "summary": "finished"}]
                }
                """,
                encoding="utf-8",
            )
            dataset_path = root / "dataset.json"
            dataset_path.write_text(
                json.dumps(dataset_payload),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                DatasetLoadError,
                "CSV data source is missing",
            ):
                load_dataset(dataset_path)

    def test_load_dataset_resolves_workflow_target(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workflows_dir = root / "workflows"
            workflows_dir.mkdir()
            workflow_path = workflows_dir / "customer.json"
            workflow_path.write_text("{}", encoding="utf-8")
            dataset_path = root / "dataset.json"
            dataset_path.write_text(
                json.dumps(
                    {
                        "name": "workflow_dataset",
                        "workflow": "workflows/customer.json",
                        "cases": [
                            {
                                "name": "customer_01",
                                "parameters": {
                                    "customer_name": "张三",
                                },
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            loaded = load_dataset(dataset_path)

        self.assertEqual(
            loaded.target_type,
            DatasetTargetType.WORKFLOW,
        )
        self.assertEqual(loaded.target_path, workflow_path.resolve())
        self.assertEqual(
            loaded.workflow_path,
            workflow_path.resolve(),
        )
        self.assertIsNone(loaded.task_path)

    def test_load_dataset_loads_csv_cases_for_workflow_target(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "rows.csv").write_text(
                "case_id,customer_name\ncustomer_01,张三\n",
                encoding="utf-8",
            )
            (root / "workflow.json").write_text(
                "{}",
                encoding="utf-8",
            )
            dataset_path = root / "dataset.json"
            dataset_path.write_text(
                json.dumps(
                    {
                        "name": "workflow_csv",
                        "workflow": "workflow.json",
                        "data_source": {
                            "type": "csv",
                            "path": "rows.csv",
                        },
                    }
                ),
                encoding="utf-8",
            )

            loaded = load_dataset(dataset_path)

        self.assertEqual(
            loaded.target_type,
            DatasetTargetType.WORKFLOW,
        )
        self.assertEqual(
            loaded.definition.cases[0].parameters,
            {"customer_name": "张三"},
        )

    def test_load_dataset_rejects_missing_workflow_target(self):
        with tempfile.TemporaryDirectory() as directory:
            dataset_path = Path(directory) / "dataset.json"
            dataset_path.write_text(
                json.dumps(
                    {
                        "name": "missing_workflow",
                        "workflow": "missing.json",
                        "cases": [
                            {"name": "case", "parameters": {}}
                        ],
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                DatasetLoadError,
                "workflow file is missing or not a file",
            ):
                load_dataset(dataset_path)


class CSVDataSourceTests(unittest.TestCase):
    def load_csv_dataset(
        self,
        csv_content,
        *,
        case_name_column="case_id",
        parameters=None,
        attempts=1,
        retry_delay_seconds=0.5,
    ):
        temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(temporary_directory.cleanup)
        root = Path(temporary_directory.name)
        (root / "rows.csv").write_text(
            csv_content,
            encoding="utf-8",
        )
        (root / "task.json").write_text(
            """
            {
              "name": "csv_task",
              "steps": [{"type": "done", "summary": "finished"}]
            }
            """,
            encoding="utf-8",
        )
        data_source = {
            "type": "csv",
            "path": "rows.csv",
            "case_name_column": case_name_column,
            "attempts": attempts,
            "retry_delay_seconds": retry_delay_seconds,
        }
        if parameters is not None:
            data_source["parameters"] = parameters
        dataset_path = root / "dataset.json"
        dataset_path.write_text(
            json.dumps(
                {
                    "name": "csv_dataset",
                    "task": "task.json",
                    "data_source": data_source,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return load_dataset(dataset_path)

    def test_infers_parameter_columns_and_preserves_quoted_values(self):
        loaded = self.load_csv_dataset(
            "\ufeffcase_id,name,note\n"
            "case_01,\"张三,北京\",正常\n",
        )

        self.assertEqual(
            loaded.definition.cases[0].parameters,
            {"name": "张三,北京", "note": "正常"},
        )

    def test_applies_source_retry_settings_to_every_case(self):
        loaded = self.load_csv_dataset(
            "case_id,value\ncase_01,a\ncase_02,b\n",
            parameters={"input_value": "value"},
            attempts=2,
            retry_delay_seconds=0.25,
        )

        self.assertEqual(
            [case.attempts for case in loaded.definition.cases],
            [2, 2],
        )
        self.assertEqual(
            [
                case.retry_delay_seconds
                for case in loaded.definition.cases
            ],
            [0.25, 0.25],
        )

    def test_rejects_missing_parameter_column(self):
        with self.assertRaisesRegex(
            DatasetLoadError,
            "CSV parameter columns are missing: right",
        ):
            self.load_csv_dataset(
                "case_id,left\ncase_01,17\n",
                parameters={"left": "left", "right": "right"},
            )

    def test_rejects_empty_parameter_value(self):
        with self.assertRaisesRegex(
            DatasetLoadError,
            "CSV value for 'right' is empty",
        ):
            self.load_csv_dataset(
                "case_id,left,right\ncase_01,17, \n",
                parameters={"left": "left", "right": "right"},
            )

    def test_rejects_duplicate_case_names(self):
        with self.assertRaisesRegex(
            DatasetLoadError,
            "duplicate CSV case name 'case_01'",
        ):
            self.load_csv_dataset(
                "case_id,value\ncase_01,a\ncase_01,b\n",
            )


class DatasetRunnerTests(unittest.TestCase):
    def make_loaded_dataset(self):
        return load_dataset(
            PROJECT_ROOT / "datasets" / "calculator_cases.json"
        )

    def make_single_case_dataset(self):
        loaded = self.make_loaded_dataset()
        loaded.definition.cases = loaded.definition.cases[:1]
        return loaded

    def make_task_result(self, status, error=None):
        started_at = datetime(2026, 11, 20, tzinfo=timezone.utc)
        return TaskResult(
            task_name="calculator_parameterized",
            status=status,
            started_at=started_at,
            finished_at=started_at,
            duration_seconds=1.5,
            error=error,
        )

    def test_run_executes_cases_in_order(self):
        loaded = self.make_loaded_dataset()
        current_time = [0.0]
        calls = []

        def execute_case(task_path, case):
            calls.append((task_path, case.name, case.parameters))
            current_time[0] += 1.5
            return self.make_task_result(TaskStatus.PASSED)

        result = DatasetRunner(
            execute_case,
            clock=lambda: current_time[0],
        ).run(loaded)

        self.assertEqual(result.dataset_name, "calculator_regression")
        self.assertEqual(result.status, TaskStatus.PASSED)
        self.assertEqual(result.duration_seconds, 3.0)
        self.assertEqual(
            [case.name for case in result.cases],
            ["default_17x23", "custom_3x4"],
        )
        self.assertEqual(
            [case.parameters for case in result.cases],
            [
                {"right": "23"},
                {
                    "left": "3",
                    "right": "4",
                    "expected_result": "12",
                },
            ],
        )
        self.assertEqual(
            calls,
            [
                (
                    loaded.task_path,
                    "default_17x23",
                    {"right": "23"},
                ),
                (
                    loaded.task_path,
                    "custom_3x4",
                    {
                        "left": "3",
                        "right": "4",
                        "expected_result": "12",
                    },
                ),
            ],
        )

    def test_run_executes_workflow_cases(self):
        loaded = replace(
            self.make_single_case_dataset(),
            target_type=DatasetTargetType.WORKFLOW,
            target_path=Path("/tmp/customer_workflow.json"),
        )
        calls = []
        timestamp = datetime(2026, 11, 25, tzinfo=timezone.utc)

        def execute_case(target_path, case):
            calls.append((target_path, case.parameters))
            return WorkflowResult(
                workflow_name="customer_workflow",
                status=TaskStatus.PASSED,
                started_at=timestamp,
                finished_at=timestamp,
                duration_seconds=2.0,
                error=None,
            )

        result = DatasetRunner(execute_case).run(loaded)

        self.assertEqual(
            calls,
            [
                (
                    Path("/tmp/customer_workflow.json"),
                    {"right": "23"},
                )
            ],
        )
        self.assertEqual(result.status, TaskStatus.PASSED)
        self.assertEqual(
            result.cases[0].target_type,
            DatasetTargetType.WORKFLOW,
        )
        self.assertIsNone(result.cases[0].task_result)
        self.assertEqual(
            result.cases[0].workflow_result.workflow_name,
            "customer_workflow",
        )

    def test_workflow_executor_exception_becomes_failed_case(self):
        loaded = replace(
            self.make_single_case_dataset(),
            target_type=DatasetTargetType.WORKFLOW,
            target_path=Path("/tmp/broken_workflow.json"),
        )

        def execute_case(target_path, case):
            raise RuntimeError("workflow crashed")

        result = DatasetRunner(execute_case).run(loaded)

        self.assertEqual(result.status, TaskStatus.FAILED)
        self.assertEqual(
            result.cases[0].workflow_result.workflow_name,
            "broken_workflow",
        )
        self.assertEqual(
            result.cases[0].workflow_result.error,
            "workflow crashed",
        )

    def test_run_continues_after_failed_case(self):
        loaded = self.make_loaded_dataset()
        statuses = iter([TaskStatus.FAILED, TaskStatus.PASSED])

        def execute_case(task_path, case):
            status = next(statuses)
            error = "failed" if status == TaskStatus.FAILED else None
            return self.make_task_result(status, error)

        result = DatasetRunner(execute_case).run(loaded)

        self.assertEqual(result.status, TaskStatus.FAILED)
        self.assertFalse(result.stopped_early)
        self.assertEqual(
            [case.status for case in result.cases],
            [TaskStatus.FAILED, TaskStatus.PASSED],
        )

    def test_run_stops_after_failed_case_when_configured(self):
        loaded = self.make_loaded_dataset()
        calls = []

        def execute_case(task_path, case):
            calls.append(case.name)
            return self.make_task_result(
                TaskStatus.FAILED,
                "failed",
            )

        result = DatasetRunner(
            execute_case,
            stop_on_failure=True,
        ).run(loaded)

        self.assertEqual(calls, ["default_17x23"])
        self.assertEqual(len(result.cases), 1)
        self.assertTrue(result.stopped_early)
        self.assertEqual(result.status, TaskStatus.FAILED)

    def test_run_converts_executor_exception_to_failed_case(self):
        loaded = self.make_loaded_dataset()
        calls = []

        def execute_case(task_path, case):
            calls.append(case.name)
            if len(calls) == 1:
                raise RuntimeError("executor crashed")
            return self.make_task_result(TaskStatus.PASSED)

        result = DatasetRunner(execute_case).run(loaded)

        self.assertEqual(len(result.cases), 2)
        self.assertEqual(result.cases[0].status, TaskStatus.FAILED)
        self.assertEqual(result.cases[0].error, "executor crashed")
        self.assertEqual(
            result.cases[0].task_result.error,
            "executor crashed",
        )
        self.assertEqual(result.cases[1].status, TaskStatus.PASSED)
        self.assertEqual(result.status, TaskStatus.FAILED)

    def test_run_aggregates_non_passed_statuses(self):
        loaded = self.make_loaded_dataset()

        for expected_status in (
            TaskStatus.TIMED_OUT,
            TaskStatus.CANCELLED,
        ):
            with self.subTest(expected_status=expected_status):
                def execute_case(task_path, case):
                    return self.make_task_result(expected_status)

                result = DatasetRunner(execute_case).run(loaded)
                self.assertEqual(result.status, expected_status)

    def test_run_retries_failed_case_until_it_passes(self):
        loaded = self.make_single_case_dataset()
        loaded.definition.cases[0].attempts = 2
        loaded.definition.cases[0].retry_delay_seconds = 0.25
        statuses = iter([TaskStatus.FAILED, TaskStatus.PASSED])
        sleeps = []

        def execute_case(task_path, case):
            status = next(statuses)
            error = "failed" if status == TaskStatus.FAILED else None
            return self.make_task_result(status, error)

        result = DatasetRunner(
            execute_case,
            sleep=sleeps.append,
        ).run(loaded)

        self.assertEqual(result.status, TaskStatus.PASSED)
        self.assertEqual(result.cases[0].attempts, 2)
        self.assertEqual(result.cases[0].status, TaskStatus.PASSED)
        self.assertEqual(sleeps, [0.25])

    def test_run_stops_retrying_after_configured_attempts(self):
        loaded = self.make_single_case_dataset()
        loaded.definition.cases[0].attempts = 2
        loaded.definition.cases[0].retry_delay_seconds = 0.1
        calls = []
        sleeps = []

        def execute_case(task_path, case):
            calls.append(case.name)
            return self.make_task_result(
                TaskStatus.FAILED,
                "failed",
            )

        result = DatasetRunner(
            execute_case,
            sleep=sleeps.append,
        ).run(loaded)

        self.assertEqual(
            calls,
            ["default_17x23", "default_17x23"],
        )
        self.assertEqual(result.cases[0].attempts, 2)
        self.assertEqual(result.cases[0].status, TaskStatus.FAILED)
        self.assertEqual(sleeps, [0.1])

    def test_run_does_not_retry_cancelled_case(self):
        loaded = self.make_single_case_dataset()
        loaded.definition.cases[0].attempts = 3
        calls = []
        sleeps = []

        def execute_case(task_path, case):
            calls.append(case.name)
            return self.make_task_result(TaskStatus.CANCELLED)

        result = DatasetRunner(
            execute_case,
            sleep=sleeps.append,
        ).run(loaded)

        self.assertEqual(calls, ["default_17x23"])
        self.assertEqual(result.cases[0].attempts, 1)
        self.assertEqual(result.status, TaskStatus.CANCELLED)
        self.assertEqual(sleeps, [])


if __name__ == "__main__":
    unittest.main()
