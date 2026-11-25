"""Tests for persistent queue models and SQLite storage."""

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from pydantic import ValidationError

from soc_agent.queue_models import QueueJob, QueueState
from soc_agent.queue_store import QueueStoreError, SQLiteQueueStore
from soc_agent.task_models import DatasetTargetType


class QueueJobTests(unittest.TestCase):
    def test_queue_job_validates_parameter_names_and_values(self):
        now = datetime(2026, 11, 25, tzinfo=timezone.utc)

        with self.assertRaisesRegex(
            ValidationError,
            "invalid parameter names",
        ):
            QueueJob(
                job_id="job",
                target_type=DatasetTargetType.TASK,
                target_path="task.json",
                parameters={"17x": "value"},
                created_at=now,
                updated_at=now,
            )

        with self.assertRaises(ValidationError):
            QueueJob(
                job_id="job",
                target_type=DatasetTargetType.TASK,
                target_path="task.json",
                parameters={"value": 123},
                created_at=now,
                updated_at=now,
            )


class SQLiteQueueStoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        self.database_path = self.root / "queue.db"
        self.current_time = datetime(
            2026,
            11,
            25,
            9,
            0,
            tzinfo=timezone.utc,
        )
        self.store = SQLiteQueueStore(
            self.database_path,
            clock=lambda: self.current_time,
        )

    def advance(self, seconds=1):
        self.current_time += timedelta(seconds=seconds)

    def test_enqueue_and_reload_persists_job(self):
        job = self.store.enqueue(
            DatasetTargetType.TASK,
            "tasks/example.json",
            {"customer_name": "张三"},
            job_id="job-1",
        )

        reloaded_store = SQLiteQueueStore(self.database_path)
        reloaded = reloaded_store.get(job.job_id)

        self.assertEqual(reloaded.state, QueueState.PENDING)
        self.assertEqual(
            reloaded.parameters,
            {"customer_name": "张三"},
        )
        self.assertEqual(
            reloaded.target_type,
            DatasetTargetType.TASK,
        )

    def test_claim_next_uses_priority_and_marks_running(self):
        self.store.enqueue(
            DatasetTargetType.TASK,
            "low.json",
            priority=1,
            job_id="low",
        )
        self.advance()
        self.store.enqueue(
            DatasetTargetType.WORKFLOW,
            "high.json",
            priority=10,
            job_id="high",
        )

        claimed = self.store.claim_next()
        remaining = self.store.claim_next()

        self.assertEqual(claimed.job_id, "high")
        self.assertEqual(claimed.state, QueueState.RUNNING)
        self.assertEqual(claimed.started_at, self.current_time)
        self.assertEqual(remaining.job_id, "low")
        self.assertIsNone(self.store.claim_next())

    def test_claim_next_returns_none_for_empty_queue(self):
        self.assertIsNone(self.store.claim_next())

    def test_complete_records_terminal_metadata(self):
        self.store.enqueue(
            DatasetTargetType.WORKFLOW,
            "workflow.json",
            job_id="job-complete",
        )
        self.store.claim_next()
        self.advance()

        completed = self.store.complete(
            "job-complete",
            QueueState.PASSED,
            report_path="reports/workflow.json",
        )

        self.assertEqual(completed.state, QueueState.PASSED)
        self.assertEqual(completed.report_path, "reports/workflow.json")
        self.assertIsNone(completed.error)
        self.assertEqual(completed.finished_at, self.current_time)

    def test_complete_requires_running_job_and_terminal_state(self):
        self.store.enqueue(
            DatasetTargetType.TASK,
            "task.json",
            job_id="job-pending",
        )

        with self.assertRaisesRegex(
            QueueStoreError,
            "requires terminal state",
        ):
            self.store.complete("job-pending", QueueState.RUNNING)

        with self.assertRaisesRegex(
            QueueStoreError,
            "is not running",
        ):
            self.store.complete("job-pending", QueueState.FAILED)

    def test_list_jobs_filters_and_orders_by_priority(self):
        self.store.enqueue(
            DatasetTargetType.TASK,
            "low.json",
            priority=1,
            job_id="low",
        )
        self.store.enqueue(
            DatasetTargetType.TASK,
            "high.json",
            priority=5,
            job_id="high",
        )

        jobs = self.store.list_jobs(QueueState.PENDING)

        self.assertEqual(
            [job.job_id for job in jobs],
            ["high", "low"],
        )


if __name__ == "__main__":
    unittest.main()
