"""Tests for persistent queue models and SQLite storage."""

import tempfile
import unittest
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from pydantic import ValidationError

from soc_agent.queue_models import QueueJob, QueueState, WorkerState
from soc_agent.queue_store import QueueStoreError, SQLiteQueueStore
from soc_agent.task_models import (
    ActionType,
    DatasetTargetType,
    ExecutionPermissions,
)


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
            permissions=ExecutionPermissions(
                allowed_apps=["计算器"],
                allowed_actions=[
                    ActionType.OPEN_APP,
                    ActionType.WRITE,
                ],
            ),
            required_labels=["office-mac", "high-memory"],
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
        self.assertEqual(
            reloaded.permissions.allowed_apps,
            ["计算器"],
        )
        self.assertEqual(
            reloaded.permissions.allowed_actions,
            [ActionType.OPEN_APP, ActionType.WRITE],
        )
        self.assertEqual(
            reloaded.required_labels,
            ["office-mac", "high-memory"],
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
        self.store.complete(
            claimed.job_id,
            QueueState.CANCELLED,
        )
        remaining = self.store.claim_next()

        self.assertEqual(claimed.job_id, "high")
        self.assertEqual(claimed.state, QueueState.RUNNING)
        self.assertEqual(claimed.started_at, self.current_time)
        self.assertEqual(claimed.claimed_at, self.current_time)
        self.assertEqual(claimed.worker_id, "local")
        self.assertEqual(claimed.attempts, 1)
        self.assertEqual(remaining.job_id, "low")
        self.assertIsNone(self.store.claim_next())

    def test_claim_next_returns_none_for_empty_queue(self):
        self.assertIsNone(self.store.claim_next())

    def test_claim_next_routes_by_worker_labels(self):
        self.store.enqueue(
            DatasetTargetType.TASK,
            "labeled.json",
            required_labels=["office-mac", "high-memory"],
            priority=10,
            job_id="labeled",
        )
        self.store.enqueue(
            DatasetTargetType.TASK,
            "general.json",
            priority=1,
            job_id="general",
        )

        general = self.store.claim_next(
            "worker-a",
            worker_labels=["office-mac"],
        )
        self.store.complete(
            general.job_id,
            QueueState.CANCELLED,
        )
        labeled = self.store.claim_next(
            "worker-b",
            worker_labels=["OFFICE-MAC", "high-memory"],
        )

        self.assertEqual(general.job_id, "general")
        self.assertEqual(labeled.job_id, "labeled")

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

    def test_existing_database_is_migrated_with_lease_columns(self):
        legacy_path = self.root / "legacy-queue.db"
        connection = sqlite3.connect(legacy_path)
        connection.execute(
            """
            CREATE TABLE queue_jobs (
                job_id TEXT PRIMARY KEY,
                target_type TEXT NOT NULL,
                target_path TEXT NOT NULL,
                parameters_json TEXT NOT NULL,
                state TEXT NOT NULL,
                priority INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                started_at TEXT,
                finished_at TEXT,
                report_path TEXT,
                error TEXT
            )
            """
        )
        connection.execute(
            """
            INSERT INTO queue_jobs VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            (
                "legacy-job",
                "task",
                "task.json",
                "{}",
                "pending",
                0,
                self.current_time.isoformat(),
                self.current_time.isoformat(),
                None,
                None,
                None,
                None,
            ),
        )
        connection.commit()
        connection.close()

        migrated = SQLiteQueueStore(legacy_path).get("legacy-job")

        self.assertIsNone(migrated.claimed_at)
        self.assertIsNone(migrated.worker_id)
        self.assertEqual(migrated.attempts, 0)
        self.assertEqual(migrated.recovery_count, 0)

    def test_heartbeat_renews_running_job_lease(self):
        self.store.enqueue(
            DatasetTargetType.TASK,
            "task.json",
            job_id="heartbeat-job",
        )
        self.store.claim_next()
        self.advance(5)

        renewed = self.store.heartbeat("heartbeat-job")

        self.assertEqual(renewed.claimed_at, self.current_time)
        self.advance(6)
        self.assertEqual(
            self.store.recover_stale_jobs(
                stale_after_seconds=10,
            ),
            [],
        )

    def test_worker_ownership_guards_heartbeat_and_completion(self):
        self.store.enqueue(
            DatasetTargetType.TASK,
            "task.json",
            job_id="owned-job",
        )
        self.store.claim_next("worker-a")
        self.advance()

        with self.assertRaisesRegex(
            QueueStoreError,
            "not running",
        ):
            self.store.heartbeat(
                "owned-job",
                worker_id="worker-b",
            )

        renewed = self.store.heartbeat(
            "owned-job",
            worker_id="worker-a",
        )
        self.assertEqual(renewed.worker_id, "worker-a")

        with self.assertRaisesRegex(
            QueueStoreError,
            "not running",
        ):
            self.store.complete(
                "owned-job",
                QueueState.PASSED,
                worker_id="worker-b",
            )

        completed = self.store.complete(
            "owned-job",
            QueueState.PASSED,
            worker_id="worker-a",
        )
        self.assertEqual(completed.state, QueueState.PASSED)

    def test_worker_registry_tracks_heartbeat_and_offline_state(self):
        registered = self.store.register_worker(
            "worker-a",
            "macbook",
            123,
            labels=["office-mac", "high-memory"],
        )

        self.assertEqual(registered.state, WorkerState.IDLE)
        self.assertEqual(registered.hostname, "macbook")
        self.assertEqual(registered.pid, 123)
        self.assertEqual(
            registered.labels,
            ["office-mac", "high-memory"],
        )

        self.advance()
        self.store.heartbeat_worker(
            "worker-a",
            WorkerState.RUNNING,
            current_job_id="job-1",
        )
        workers = self.store.list_workers()
        self.assertEqual(workers[0].state, WorkerState.RUNNING)
        self.assertEqual(workers[0].current_job_id, "job-1")

        self.advance()
        offline = self.store.mark_worker_offline("worker-a")
        self.assertEqual(offline.state, WorkerState.OFFLINE)
        self.assertIsNone(offline.current_job_id)
        self.assertEqual(offline.stopped_at, self.current_time)

    def test_list_workers_can_filter_recent_heartbeats(self):
        self.store.register_worker("old-worker", "macbook", 100)
        self.advance(20)
        self.store.register_worker("new-worker", "macbook", 101)

        workers = self.store.list_workers(
            online_within_seconds=10
        )

        self.assertEqual(
            [worker.worker_id for worker in workers],
            ["new-worker"],
        )

    def test_recover_stale_job_requeues_then_fails_at_max_attempts(self):
        self.store.enqueue(
            DatasetTargetType.TASK,
            "task.json",
            job_id="stale-job",
        )
        self.store.claim_next()
        self.advance(11)

        recovered = self.store.recover_stale_jobs(
            stale_after_seconds=10,
            max_attempts=2,
        )[0]

        self.assertEqual(recovered.state, QueueState.PENDING)
        self.assertIsNone(recovered.claimed_at)
        self.assertEqual(recovered.attempts, 1)
        self.assertEqual(recovered.recovery_count, 1)

        self.store.claim_next()
        self.advance(11)
        failed = self.store.recover_stale_jobs(
            stale_after_seconds=10,
            max_attempts=2,
        )[0]

        self.assertEqual(failed.state, QueueState.FAILED)
        self.assertEqual(failed.attempts, 2)
        self.assertEqual(failed.recovery_count, 2)
        self.assertIn("maximum attempts", failed.error)


if __name__ == "__main__":
    unittest.main()
