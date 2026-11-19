"""Tests for sequential task suite execution."""

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from soc_agent.suite import SuiteRunner
from soc_agent.task_models import TaskResult, TaskStatus


class SuiteRunnerTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)

        for name in ("b.json", "a.json", "c.json"):
            (self.root / name).write_text("{}", encoding="utf-8")

    def make_result(self, task_name, status=TaskStatus.PASSED):
        now = datetime.now(timezone.utc)
        return TaskResult(
            task_name=task_name,
            status=status,
            started_at=now,
            finished_at=now,
            duration_seconds=0.1,
        )

    def test_tasks_are_sorted_and_aggregated(self):
        calls = []

        def execute(path):
            calls.append(path.name)
            return self.make_result(path.stem)

        result = SuiteRunner(execute).run(self.root)

        self.assertEqual(calls, ["a.json", "b.json", "c.json"])
        self.assertEqual(result.total, 3)
        self.assertEqual(result.passed, 3)
        self.assertTrue(result.successful)

    def test_failure_continues_by_default(self):
        calls = []

        def execute(path):
            calls.append(path.name)
            status = (
                TaskStatus.FAILED
                if path.name == "b.json"
                else TaskStatus.PASSED
            )
            return self.make_result(path.stem, status)

        result = SuiteRunner(execute).run(self.root)

        self.assertEqual(calls, ["a.json", "b.json", "c.json"])
        self.assertEqual(result.failed, 1)
        self.assertFalse(result.successful)

    def test_stop_on_failure(self):
        calls = []

        def execute(path):
            calls.append(path.name)
            status = (
                TaskStatus.TIMED_OUT
                if path.name == "b.json"
                else TaskStatus.PASSED
            )
            return self.make_result(path.stem, status)

        result = SuiteRunner(
            execute,
            stop_on_failure=True,
        ).run(self.root)

        self.assertEqual(calls, ["a.json", "b.json"])
        self.assertTrue(result.stopped_early)
        self.assertEqual(result.timed_out, 1)

    def test_execution_exception_becomes_failed_result(self):
        def execute(path):
            raise RuntimeError("runner crashed")

        result = SuiteRunner(execute).run(self.root / "a.json")

        self.assertEqual(result.total, 1)
        self.assertEqual(result.failed, 1)
        self.assertIn("runner crashed", result.results[0].error)

    def test_empty_directory_is_rejected(self):
        empty = self.root / "empty"
        empty.mkdir()

        with self.assertRaisesRegex(FileNotFoundError, "no JSON tasks"):
            SuiteRunner(lambda path: None).run(empty)


if __name__ == "__main__":
    unittest.main()
