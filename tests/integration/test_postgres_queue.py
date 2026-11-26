"""PostgreSQL queue integration tests.

Set SOC_TEST_POSTGRES_DSN to run these tests:

    SOC_TEST_POSTGRES_DSN=postgresql://soc_agent:soc_agent_test@localhost:5432/soc_agent_test
"""

import os
import unittest
from datetime import datetime, timedelta, timezone

from soc_agent.postgres_queue_store import PostgreSQLQueueStore
from soc_agent.queue_models import QueueState, WorkerState
from soc_agent.task_models import DatasetTargetType


POSTGRES_DSN = os.getenv("SOC_TEST_POSTGRES_DSN", "").strip()


def _psycopg_connection():
    import psycopg
    from psycopg.rows import dict_row

    return psycopg.connect(POSTGRES_DSN, row_factory=dict_row)


@unittest.skipUnless(
    POSTGRES_DSN,
    "SOC_TEST_POSTGRES_DSN is required for PostgreSQL integration tests",
)
class PostgreSQLQueueIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store = PostgreSQLQueueStore(POSTGRES_DSN)
        with _psycopg_connection() as connection:
            connection.execute(
                """
                SELECT migration_id
                FROM queue_schema_migrations
                ORDER BY migration_id
                """
            ).fetchall()

    def setUp(self):
        with _psycopg_connection() as connection:
            connection.execute(
                """
                TRUNCATE TABLE
                    queue_exclusive_locks,
                    queue_jobs,
                    queue_workers
                """
            )

    def test_enqueue_claim_heartbeat_and_complete(self):
        job = self.store.enqueue(
            DatasetTargetType.TASK,
            "tasks/example.json",
            {"value": "hello"},
            required_labels=["office-mac"],
            job_id="postgres-job",
        )

        claimed = self.store.claim_next(
            "worker-a",
            worker_labels=["office-mac"],
        )
        renewed = self.store.heartbeat(
            claimed.job_id,
            worker_id="worker-a",
        )
        completed = self.store.complete(
            claimed.job_id,
            QueueState.PASSED,
            report_path="reports/postgres-job.json",
            worker_id="worker-a",
        )

        self.assertEqual(job.job_id, "postgres-job")
        self.assertEqual(claimed.worker_id, "worker-a")
        self.assertEqual(renewed.claimed_at, renewed.updated_at)
        self.assertEqual(completed.state, QueueState.PASSED)
        self.assertEqual(
            completed.report_path,
            "reports/postgres-job.json",
        )

    def test_labels_and_gui_exclusive_lock(self):
        self.store.enqueue(
            DatasetTargetType.TASK,
            "gui-a.json",
            required_labels=["office-mac"],
            job_id="gui-a",
        )
        self.store.enqueue(
            DatasetTargetType.TASK,
            "gui-b.json",
            required_labels=["office-mac"],
            job_id="gui-b",
        )
        self.store.enqueue(
            DatasetTargetType.TASK,
            "parallel.json",
            required_labels=["office-mac"],
            parallel_safe=True,
            job_id="parallel",
        )

        first_gui = self.store.claim_next(
            "worker-a",
            worker_labels=["office-mac"],
        )
        parallel = self.store.claim_next(
            "worker-b",
            worker_labels=["office-mac"],
        )
        blocked = self.store.claim_next(
            "worker-c",
            worker_labels=["office-mac"],
        )

        self.assertEqual(first_gui.job_id, "gui-a")
        self.assertEqual(parallel.job_id, "parallel")
        self.assertIsNone(blocked)

    def test_recover_stale_job(self):
        self.store.enqueue(
            DatasetTargetType.TASK,
            "stale.json",
            job_id="stale-job",
        )
        claimed = self.store.claim_next("stale-worker")
        old_timestamp = (
            datetime.now(timezone.utc) - timedelta(minutes=20)
        )
        with _psycopg_connection() as connection:
            connection.execute(
                """
                UPDATE queue_jobs
                SET claimed_at = %s
                WHERE job_id = %s
                """,
                (old_timestamp, claimed.job_id),
            )

        recovered = self.store.recover_stale_jobs(
            stale_after_seconds=60,
            max_attempts=2,
        )

        self.assertEqual(len(recovered), 1)
        self.assertEqual(recovered[0].state, QueueState.PENDING)
        self.assertEqual(recovered[0].recovery_count, 1)

    def test_requeue_running_job(self):
        self.store.enqueue(
            DatasetTargetType.TASK,
            "retry.json",
            job_id="retry-job",
        )
        self.store.claim_next("retry-worker")

        requeued = self.store.requeue(
            "retry-job",
            error="temporary failure",
            worker_id="retry-worker",
        )

        self.assertEqual(requeued.state, QueueState.PENDING)
        self.assertIsNone(requeued.claimed_at)
        self.assertEqual(requeued.attempts, 1)
        self.assertEqual(requeued.error, "temporary failure")

    def test_cancel_pending_and_retry_failed_job(self):
        self.store.enqueue(
            DatasetTargetType.TASK,
            "control.json",
            job_id="control-cancel",
        )
        cancelled = self.store.cancel("control-cancel")

        self.assertEqual(cancelled.state, QueueState.CANCELLED)

        self.store.enqueue(
            DatasetTargetType.TASK,
            "control-retry.json",
            job_id="control-retry",
        )
        self.store.claim_next("retry-worker")
        self.store.complete(
            "control-retry",
            QueueState.FAILED,
            worker_id="retry-worker",
        )
        retried = self.store.retry("control-retry")

        self.assertEqual(retried.state, QueueState.PENDING)
        self.assertEqual(retried.attempts, 0)

    def test_worker_registry(self):
        self.store.register_worker(
            "worker-a",
            "macbook-a",
            123,
            labels=["office-mac", "high-memory"],
            max_concurrency=2,
        )
        self.store.heartbeat_worker(
            "worker-a",
            WorkerState.RUNNING,
            current_job_id="job-1",
        )
        workers = self.store.list_workers()

        self.assertEqual(len(workers), 1)
        self.assertEqual(workers[0].worker_id, "worker-a")
        self.assertEqual(
            workers[0].labels,
            ["office-mac", "high-memory"],
        )
        self.assertEqual(workers[0].max_concurrency, 2)


if __name__ == "__main__":
    unittest.main()
