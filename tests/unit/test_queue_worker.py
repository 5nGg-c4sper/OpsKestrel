"""Tests for persistent queue job execution."""

import tempfile
import threading
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path

from soc_agent.queue_models import QueueJob, QueueState
from soc_agent.queue_store import SQLiteQueueStore
from soc_agent.queue_worker import QueueWorker
from soc_agent.task_models import (
    DatasetTargetType,
    TaskResult,
    TaskStatus,
    WorkflowResult,
)


class QueueWorkerTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.database_path = (
            Path(self.temporary_directory.name) / "queue.db"
        )
        self.timestamp = datetime(
            2026,
            11,
            25,
            10,
            0,
            tzinfo=timezone.utc,
        )
        self.store = SQLiteQueueStore(self.database_path)

    def make_task_result(
        self,
        status=TaskStatus.PASSED,
        report_path=None,
        error=None,
    ):
        return TaskResult(
            task_name="queued_task",
            status=status,
            started_at=self.timestamp,
            finished_at=self.timestamp,
            duration_seconds=1.0,
            report_path=report_path,
            error=error,
        )

    def test_run_once_returns_none_for_empty_queue(self):
        worker = QueueWorker(
            self.store,
            lambda job: self.make_task_result(),
        )

        self.assertIsNone(worker.run_once())

    def test_run_once_executes_and_completes_task_job(self):
        job = self.store.enqueue(
            DatasetTargetType.TASK,
            "tasks/example.json",
            {"value": "hello"},
            job_id="task-job",
        )
        calls = []

        worker = QueueWorker(
            self.store,
            lambda queued_job: (
                calls.append(queued_job) or self.make_task_result(
                    report_path="reports/task.json"
                )
            ),
        )

        completed = worker.run_once()

        self.assertEqual(calls[0].job_id, job.job_id)
        self.assertEqual(completed.state, QueueState.PASSED)
        self.assertEqual(completed.report_path, "reports/task.json")
        self.assertIsNone(completed.error)

    def test_run_once_persists_failed_workflow_result(self):
        self.store.enqueue(
            DatasetTargetType.WORKFLOW,
            "workflows/example.json",
            job_id="workflow-job",
        )
        workflow_result = WorkflowResult(
            workflow_name="queued_workflow",
            status=TaskStatus.FAILED,
            started_at=self.timestamp,
            finished_at=self.timestamp,
            duration_seconds=2.0,
            error="workflow failed",
            report_path="reports/workflow.json",
        )
        worker = QueueWorker(
            self.store,
            lambda job: workflow_result,
        )

        completed = worker.run_once()

        self.assertEqual(completed.state, QueueState.FAILED)
        self.assertEqual(completed.error, "workflow failed")
        self.assertEqual(
            completed.report_path,
            "reports/workflow.json",
        )

    def test_run_once_converts_executor_exception_to_failed_job(self):
        self.store.enqueue(
            DatasetTargetType.TASK,
            "tasks/broken.json",
            job_id="broken-job",
        )

        def execute_job(job):
            raise RuntimeError("executor crashed")

        completed = QueueWorker(
            self.store,
            execute_job,
        ).run_once()

        self.assertEqual(completed.state, QueueState.FAILED)
        self.assertIn(
            "queue worker execution failed: executor crashed",
            completed.error,
        )

    def test_run_once_maps_timeout_and_cancellation(self):
        statuses = (
            TaskStatus.TIMED_OUT,
            TaskStatus.CANCELLED,
        )
        expected_states = (
            QueueState.TIMED_OUT,
            QueueState.CANCELLED,
        )

        for status, expected_state in zip(statuses, expected_states):
            with self.subTest(status=status):
                self.store.enqueue(
                    DatasetTargetType.TASK,
                    f"tasks/{status.value}.json",
                )
                worker = QueueWorker(
                    self.store,
                    lambda job, value=status: self.make_task_result(
                        status=value,
                        error=value.value,
                    ),
                )

                completed = worker.run_once()

                self.assertEqual(completed.state, expected_state)
                self.assertEqual(completed.error, status.value)

    def test_run_until_empty_processes_jobs_in_priority_order(self):
        self.store.enqueue(
            DatasetTargetType.TASK,
            "low.json",
            priority=1,
            job_id="low",
        )
        self.store.enqueue(
            DatasetTargetType.TASK,
            "high.json",
            priority=10,
            job_id="high",
        )
        calls = []
        worker = QueueWorker(
            self.store,
            lambda job: (
                calls.append(job.job_id) or self.make_task_result()
            ),
        )

        completed = worker.run_until_empty()

        self.assertEqual(calls, ["high", "low"])
        self.assertEqual(
            [job.job_id for job in completed],
            ["high", "low"],
        )
        self.assertEqual(self.store.list_jobs(QueueState.PENDING), [])

    def test_run_until_empty_respects_max_jobs(self):
        for index in range(3):
            self.store.enqueue(
                DatasetTargetType.TASK,
                f"task-{index}.json",
            )
        worker = QueueWorker(
            self.store,
            lambda job: self.make_task_result(),
        )

        completed = worker.run_until_empty(max_jobs=2)

        self.assertEqual(len(completed), 2)
        self.assertEqual(
            len(self.store.list_jobs(QueueState.PENDING)),
            1,
        )

    def test_run_until_empty_rejects_invalid_max_jobs(self):
        worker = QueueWorker(
            self.store,
            lambda job: self.make_task_result(),
        )

        with self.assertRaisesRegex(ValueError, "max_jobs"):
            worker.run_until_empty(max_jobs=0)

    def test_run_once_recovers_stale_job_before_claiming(self):
        self.store.enqueue(
            DatasetTargetType.TASK,
            "stale.json",
            job_id="stale-job",
        )
        claimed = self.store.claim_next()
        self.assertIsNotNone(claimed)
        # Stale recovery uses the store's real clock, so age the claim
        # through a separate store configured with a later clock.
        later_timestamp = claimed.claimed_at.replace(
            year=claimed.claimed_at.year + 1
        )
        later_store = SQLiteQueueStore(
            self.database_path,
            clock=lambda: later_timestamp,
        )
        calls = []
        worker = QueueWorker(
            later_store,
            lambda job: (
                calls.append(job) or self.make_task_result()
            ),
            stale_after_seconds=10,
            max_attempts=3,
        )

        completed = worker.run_once()

        self.assertEqual(calls[0].job_id, "stale-job")
        self.assertEqual(completed.state, QueueState.PASSED)
        self.assertEqual(completed.recovery_count, 1)
        self.assertEqual(completed.attempts, 2)

    def test_worker_auto_heartbeats_and_records_ownership(self):
        timestamp = self.timestamp
        job = QueueJob(
            job_id="heartbeat-job",
            target_type=DatasetTargetType.TASK,
            target_path="task.json",
            state=QueueState.PENDING,
            created_at=timestamp,
            updated_at=timestamp,
        )

        class RecordingStore:
            def __init__(self):
                self.claimed_worker = None
                self.heartbeat_calls = []
                self.completed_worker = None
                self.worker_heartbeats = []
                self.registered = False
                self.offline = False

            def register_worker(
                self,
                worker_id,
                hostname,
                pid,
                labels=None,
                max_concurrency=1,
            ):
                self.registered = True
                return None

            def recover_stale_jobs(self, **kwargs):
                return []

            def claim_next(self, worker_id, worker_labels=None):
                self.claimed_worker = worker_id
                return job

            def heartbeat(self, job_id, worker_id=None):
                self.heartbeat_calls.append((job_id, worker_id))
                return job

            def heartbeat_worker(
                self,
                worker_id,
                state,
                current_job_id=None,
            ):
                self.worker_heartbeats.append(
                    (worker_id, state, current_job_id)
                )
                return None

            def complete(self, job_id, state, **kwargs):
                self.completed_worker = kwargs.get("worker_id")
                return job.model_copy(
                    update={
                        "state": state,
                        "worker_id": self.completed_worker,
                        "finished_at": timestamp,
                    }
                )

            def mark_worker_offline(self, worker_id):
                self.offline = True
                return None

        store = RecordingStore()

        def execute_job(queued_job):
            time.sleep(0.06)
            return self.make_task_result()

        completed = QueueWorker(
            store,
            execute_job,
            stale_after_seconds=0.03,
            heartbeat_interval_seconds=0.01,
            worker_id="worker-heartbeat",
        ).run_once()

        self.assertEqual(store.claimed_worker, "worker-heartbeat")
        self.assertGreaterEqual(len(store.heartbeat_calls), 1)
        self.assertTrue(
            all(
                worker_id == "worker-heartbeat"
                for _, worker_id in store.heartbeat_calls
            )
        )
        self.assertEqual(store.completed_worker, "worker-heartbeat")
        self.assertTrue(store.registered)
        self.assertGreaterEqual(len(store.worker_heartbeats), 1)
        self.assertTrue(store.offline)
        self.assertEqual(completed.state, QueueState.PASSED)

    def test_parallel_safe_jobs_use_worker_capacity(self):
        for index in range(2):
            self.store.enqueue(
                DatasetTargetType.TASK,
                f"parallel-{index}.json",
                parallel_safe=True,
            )
        lock = threading.Lock()
        active = [0]
        maximum = [0]

        def execute_job(job):
            with lock:
                active[0] += 1
                maximum[0] = max(maximum[0], active[0])
            time.sleep(0.05)
            with lock:
                active[0] -= 1
            return self.make_task_result()

        completed = QueueWorker(
            self.store,
            execute_job,
            max_concurrency=2,
        ).run_until_empty(max_jobs=2)

        self.assertEqual(len(completed), 2)
        self.assertEqual(maximum[0], 2)

    def test_gui_jobs_remain_globally_serialized(self):
        for index in range(2):
            self.store.enqueue(
                DatasetTargetType.TASK,
                f"serial-{index}.json",
            )
        lock = threading.Lock()
        active = [0]
        maximum = [0]

        def execute_job(job):
            with lock:
                active[0] += 1
                maximum[0] = max(maximum[0], active[0])
            time.sleep(0.05)
            with lock:
                active[0] -= 1
            return self.make_task_result()

        completed = QueueWorker(
            self.store,
            execute_job,
            max_concurrency=2,
        ).run_until_empty(max_jobs=2)

        self.assertEqual(len(completed), 2)
        self.assertEqual(maximum[0], 1)


if __name__ == "__main__":
    unittest.main()
