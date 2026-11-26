"""PostgreSQL multi-worker coordination integration tests."""

import os
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from opskestrel.postgres_queue_store import PostgreSQLQueueStore
from opskestrel.queue_models import QueueState, WorkerState
from opskestrel.task_models import DatasetTargetType


POSTGRES_DSN = os.getenv("OPSKESTREL_TEST_POSTGRES_DSN", "").strip()


def _psycopg_connection():
    import psycopg
    from psycopg.rows import dict_row

    return psycopg.connect(POSTGRES_DSN, row_factory=dict_row)


@unittest.skipUnless(
    POSTGRES_DSN,
    "OPSKESTREL_TEST_POSTGRES_DSN is required for multi-worker tests",
)
class PostgreSQLMultiWorkerTests(unittest.TestCase):
    def setUp(self):
        self.store = PostgreSQLQueueStore(POSTGRES_DSN)
        with _psycopg_connection() as connection:
            connection.execute(
                """
                TRUNCATE TABLE
                    queue_exclusive_locks,
                    queue_jobs,
                    queue_workers
                """
            )

    def test_two_workers_claim_parallel_safe_jobs_without_overlap(self):
        for index in range(2):
            self.store.enqueue(
                DatasetTargetType.TASK,
                f"parallel-{index}.json",
                required_labels=["office-mac"],
                parallel_safe=True,
                priority=10 - index,
                job_id=f"parallel-{index}",
            )
        barrier = threading.Barrier(2)

        def claim(worker_id):
            store = PostgreSQLQueueStore(POSTGRES_DSN)
            barrier.wait(timeout=5)
            return store.claim_next(
                worker_id,
                worker_labels=["office-mac"],
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(claim, "worker-a"),
                executor.submit(claim, "worker-b"),
            ]
            claimed = [future.result(timeout=10) for future in futures]

        self.assertTrue(all(job is not None for job in claimed))
        self.assertEqual(
            {job.job_id for job in claimed},
            {"parallel-0", "parallel-1"},
        )
        self.assertEqual(
            {job.worker_id for job in claimed},
            {"worker-a", "worker-b"},
        )

    def test_gui_exclusive_lock_is_visible_to_other_workers(self):
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
        worker_a = PostgreSQLQueueStore(POSTGRES_DSN)
        worker_b = PostgreSQLQueueStore(POSTGRES_DSN)

        first = worker_a.claim_next(
            "worker-a",
            worker_labels=["office-mac"],
        )
        second = worker_b.claim_next(
            "worker-b",
            worker_labels=["office-mac"],
        )

        self.assertEqual(first.job_id, "gui-a")
        self.assertIsNone(second)

    def test_other_worker_recovers_stale_job_and_reclaims_it(self):
        self.store.enqueue(
            DatasetTargetType.TASK,
            "stale.json",
            job_id="stale-job",
        )
        worker_a = PostgreSQLQueueStore(POSTGRES_DSN)
        claimed = worker_a.claim_next("worker-a")
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

        worker_b = PostgreSQLQueueStore(POSTGRES_DSN)
        recovered = worker_b.recover_stale_jobs(
            stale_after_seconds=60,
            max_attempts=3,
        )
        reclaimed = worker_b.claim_next("worker-b")

        self.assertEqual(recovered[0].state, QueueState.PENDING)
        self.assertEqual(reclaimed.job_id, "stale-job")
        self.assertEqual(reclaimed.worker_id, "worker-b")
        self.assertEqual(reclaimed.attempts, 2)

    def test_worker_registry_reports_two_running_workers(self):
        worker_a = PostgreSQLQueueStore(POSTGRES_DSN)
        worker_b = PostgreSQLQueueStore(POSTGRES_DSN)
        worker_a.register_worker(
            "worker-a",
            "macbook-a",
            101,
            labels=["office-mac"],
        )
        worker_b.register_worker(
            "worker-b",
            "macbook-b",
            102,
            labels=["office-mac"],
        )
        worker_a.heartbeat_worker(
            "worker-a",
            WorkerState.RUNNING,
            current_job_id="job-a",
        )
        worker_b.heartbeat_worker(
            "worker-b",
            WorkerState.RUNNING,
            current_job_id="job-b",
        )

        workers = worker_a.list_workers(online_within_seconds=60)

        self.assertEqual(
            {worker.worker_id for worker in workers},
            {"worker-a", "worker-b"},
        )
        self.assertEqual(
            {worker.current_job_id for worker in workers},
            {"job-a", "job-b"},
        )


if __name__ == "__main__":
    unittest.main()
