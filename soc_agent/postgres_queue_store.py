"""PostgreSQL-backed queue storage."""

import json
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional, Union

from soc_agent.queue_backend import (
    QueueStore,
    QueueStoreBackendError,
    QueueStoreError,
)
from soc_agent.queue_models import (
    TERMINAL_QUEUE_STATES,
    QueueJob,
    QueueState,
    QueueWorkerRecord,
    WorkerState,
)
from soc_agent.task_models import (
    DatasetTargetType,
    ExecutionPermissions,
)


POSTGRES_CLAIM_SQL = """
SELECT *
FROM queue_jobs
WHERE state = 'pending'
  AND required_labels_json <@ %s::jsonb
  AND (
      parallel_safe = TRUE
      OR NOT EXISTS (
          SELECT 1
          FROM queue_jobs running
          WHERE running.state = 'running'
            AND running.parallel_safe = FALSE
      )
  )
ORDER BY priority DESC, created_at ASC, job_id ASC
FOR UPDATE SKIP LOCKED
LIMIT 1
"""


POSTGRES_MIGRATIONS = (
    """
    CREATE TABLE IF NOT EXISTS queue_schema_migrations (
        migration_id TEXT PRIMARY KEY,
        applied_at TIMESTAMPTZ NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS queue_jobs (
        job_id TEXT PRIMARY KEY,
        target_type TEXT NOT NULL,
        target_path TEXT NOT NULL,
        parameters_json JSONB NOT NULL,
        permissions_json JSONB NOT NULL,
        required_labels_json JSONB NOT NULL DEFAULT '[]'::jsonb,
        parallel_safe BOOLEAN NOT NULL DEFAULT FALSE,
        state TEXT NOT NULL,
        priority BIGINT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL,
        updated_at TIMESTAMPTZ NOT NULL,
        started_at TIMESTAMPTZ,
        claimed_at TIMESTAMPTZ,
        worker_id TEXT,
        finished_at TIMESTAMPTZ,
        attempts INTEGER NOT NULL DEFAULT 0,
        recovery_count INTEGER NOT NULL DEFAULT 0,
        report_path TEXT,
        error TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS queue_workers (
        worker_id TEXT PRIMARY KEY,
        hostname TEXT NOT NULL,
        pid INTEGER NOT NULL,
        state TEXT NOT NULL,
        current_job_id TEXT,
        labels_json JSONB NOT NULL DEFAULT '[]'::jsonb,
        max_concurrency INTEGER NOT NULL DEFAULT 1,
        started_at TIMESTAMPTZ NOT NULL,
        last_heartbeat TIMESTAMPTZ NOT NULL,
        stopped_at TIMESTAMPTZ
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS queue_exclusive_locks (
        lock_name TEXT PRIMARY KEY,
        job_id TEXT NOT NULL UNIQUE,
        created_at TIMESTAMPTZ NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_queue_pending
    ON queue_jobs (
        state, priority DESC, created_at, job_id
    )
    """,
)


class PostgreSQLQueueStore(QueueStore):
    """Persist queue jobs in PostgreSQL for multi-machine workers."""

    def __init__(
        self,
        dsn: str,
        clock: Optional[Callable[[], datetime]] = None,
        connection_factory=None,
    ):
        if not dsn.strip():
            raise QueueStoreBackendError("PostgreSQL DSN must not be empty")
        self.dsn = dsn
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._connection_factory = connection_factory
        self._initialize()

    def enqueue(
        self,
        target_type: DatasetTargetType,
        target_path: Union[str, Path],
        parameters: Optional[Dict[str, str]] = None,
        permissions: Optional[ExecutionPermissions] = None,
        required_labels: Optional[List[str]] = None,
        parallel_safe: bool = False,
        priority: int = 0,
        job_id: Optional[str] = None,
    ) -> QueueJob:
        now = self._clock()
        job = QueueJob(
            job_id=job_id or str(uuid.uuid4()),
            target_type=target_type,
            target_path=str(target_path),
            parameters=dict(parameters or {}),
            permissions=permissions or ExecutionPermissions(),
            required_labels=list(required_labels or []),
            parallel_safe=parallel_safe,
            priority=priority,
            created_at=now,
            updated_at=now,
        )
        with self._connection() as connection:
            row = connection.execute(
                """
                INSERT INTO queue_jobs (
                    job_id, target_type, target_path, parameters_json,
                    permissions_json, required_labels_json, parallel_safe,
                    state, priority, created_at, updated_at, started_at,
                    claimed_at, worker_id, finished_at, attempts,
                    recovery_count, report_path, error
                ) VALUES (
                    %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s,
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                RETURNING *
                """,
                self._job_values(job),
            ).fetchone()
        return self._job_from_row(row)

    def get(self, job_id: str) -> QueueJob:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM queue_jobs WHERE job_id = %s",
                (job_id,),
            ).fetchone()
        if row is None:
            raise QueueStoreError(f"queue job not found: {job_id}")
        return self._job_from_row(row)

    def list_jobs(
        self,
        state: Optional[QueueState] = None,
    ) -> List[QueueJob]:
        query = "SELECT * FROM queue_jobs"
        values = ()
        if state is not None:
            query += " WHERE state = %s"
            values = (state.value,)
        query += (
            " ORDER BY priority DESC, created_at ASC, job_id ASC"
        )
        with self._connection() as connection:
            rows = connection.execute(query, values).fetchall()
        return [self._job_from_row(row) for row in rows]

    def claim_next(
        self,
        worker_id: str = "local",
        worker_labels: Optional[List[str]] = None,
    ) -> Optional[QueueJob]:
        if not worker_id.strip():
            raise QueueStoreError("worker_id must not be empty")
        now = self._clock()
        labels_json = json.dumps(
            list(worker_labels or []),
            ensure_ascii=False,
        )
        with self._connection() as connection:
            row = connection.execute(
                POSTGRES_CLAIM_SQL,
                (labels_json,),
            ).fetchone()
            if row is None:
                return None
            if not row["parallel_safe"]:
                exclusive = connection.execute(
                    """
                    INSERT INTO queue_exclusive_locks (
                        lock_name, job_id, created_at
                    ) VALUES ('macos-gui', %s, %s)
                    ON CONFLICT DO NOTHING
                    RETURNING job_id
                    """,
                    (row["job_id"], now),
                ).fetchone()
                if exclusive is None:
                    return None
            updated = connection.execute(
                """
                UPDATE queue_jobs
                SET state = %s, started_at = %s, claimed_at = %s,
                    worker_id = %s, updated_at = %s,
                    attempts = attempts + 1
                WHERE job_id = %s AND state = %s
                RETURNING *
                """,
                (
                    QueueState.RUNNING.value,
                    now,
                    now,
                    worker_id,
                    now,
                    row["job_id"],
                    QueueState.PENDING.value,
                ),
            ).fetchone()
        if updated is None:
            raise QueueStoreError(
                f"failed to claim queue job: {row['job_id']}"
            )
        return self._job_from_row(updated)

    def heartbeat(
        self,
        job_id: str,
        worker_id: Optional[str] = None,
    ) -> QueueJob:
        now = self._clock()
        query = """
            UPDATE queue_jobs
            SET claimed_at = %s, updated_at = %s
            WHERE job_id = %s AND state = %s
        """
        values = [
            now,
            now,
            job_id,
            QueueState.RUNNING.value,
        ]
        if worker_id is not None:
            query += " AND worker_id = %s"
            values.append(worker_id)
        query += " RETURNING *"
        with self._connection() as connection:
            row = connection.execute(
                query,
                tuple(values),
            ).fetchone()
        if row is None:
            raise QueueStoreError(
                f"queue job is not running: {job_id}"
            )
        return self._job_from_row(row)

    def recover_stale_jobs(
        self,
        stale_after_seconds: float,
        max_attempts: int = 3,
    ) -> List[QueueJob]:
        if stale_after_seconds <= 0:
            raise QueueStoreError(
                "stale_after_seconds must be greater than 0"
            )
        if max_attempts < 1:
            raise QueueStoreError("max_attempts must be at least 1")

        now = self._clock()
        cutoff = now.timestamp() - stale_after_seconds
        cutoff_at = datetime.fromtimestamp(cutoff, tz=timezone.utc)
        recovered = []
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT job_id, attempts
                FROM queue_jobs
                WHERE state = %s
                  AND claimed_at IS NOT NULL
                  AND claimed_at <= %s
                FOR UPDATE SKIP LOCKED
                """,
                (QueueState.RUNNING.value, cutoff_at),
            ).fetchall()
            for row in rows:
                if row["attempts"] >= max_attempts:
                    updated = connection.execute(
                        """
                        UPDATE queue_jobs
                        SET state = %s, finished_at = %s,
                            updated_at = %s,
                            recovery_count = recovery_count + 1,
                            error = %s
                        WHERE job_id = %s AND state = %s
                        RETURNING *
                        """,
                        (
                            QueueState.FAILED.value,
                            now,
                            now,
                            "stale queue lease exceeded maximum attempts",
                            row["job_id"],
                            QueueState.RUNNING.value,
                        ),
                    ).fetchone()
                else:
                    updated = connection.execute(
                        """
                        UPDATE queue_jobs
                        SET state = %s, started_at = NULL,
                            claimed_at = NULL, worker_id = NULL,
                            updated_at = %s,
                            recovery_count = recovery_count + 1,
                            error = %s
                        WHERE job_id = %s AND state = %s
                        RETURNING *
                        """,
                        (
                            QueueState.PENDING.value,
                            now,
                            "stale queue lease recovered",
                            row["job_id"],
                            QueueState.RUNNING.value,
                        ),
                    ).fetchone()
                if updated is not None:
                    connection.execute(
                        "DELETE FROM queue_exclusive_locks "
                        "WHERE job_id = %s",
                        (row["job_id"],),
                    )
                    recovered.append(self._job_from_row(updated))
        return recovered

    def complete(
        self,
        job_id: str,
        state: QueueState,
        report_path: Optional[str] = None,
        error: Optional[str] = None,
        worker_id: Optional[str] = None,
    ) -> QueueJob:
        if state not in TERMINAL_QUEUE_STATES:
            raise QueueStoreError(
                f"queue job completion requires terminal state: {state}"
            )
        now = self._clock()
        query = """
            UPDATE queue_jobs
            SET state = %s, finished_at = %s, updated_at = %s,
                report_path = %s, error = %s
            WHERE job_id = %s AND state = %s
        """
        values = [
            state.value,
            now,
            now,
            report_path,
            error,
            job_id,
            QueueState.RUNNING.value,
        ]
        if worker_id is not None:
            query += " AND worker_id = %s"
            values.append(worker_id)
        query += " RETURNING *"
        with self._connection() as connection:
            row = connection.execute(
                query,
                tuple(values),
            ).fetchone()
            if row is not None:
                connection.execute(
                    "DELETE FROM queue_exclusive_locks "
                    "WHERE job_id = %s",
                    (job_id,),
                )
        if row is None:
            raise QueueStoreError(
                f"queue job is not running: {job_id}"
            )
        return self._job_from_row(row)

    def register_worker(
        self,
        worker_id: str,
        hostname: str,
        pid: int,
        labels: Optional[List[str]] = None,
        max_concurrency: int = 1,
    ) -> QueueWorkerRecord:
        now = self._clock()
        labels_json = json.dumps(
            list(labels or []),
            ensure_ascii=False,
        )
        with self._connection() as connection:
            row = connection.execute(
                """
                INSERT INTO queue_workers (
                    worker_id, hostname, pid, state, current_job_id,
                    labels_json, max_concurrency, started_at,
                    last_heartbeat, stopped_at
                ) VALUES (
                    %s, %s, %s, %s, NULL, %s::jsonb, %s, %s, %s, NULL
                )
                ON CONFLICT (worker_id) DO UPDATE SET
                    hostname = EXCLUDED.hostname,
                    pid = EXCLUDED.pid,
                    state = EXCLUDED.state,
                    current_job_id = NULL,
                    labels_json = EXCLUDED.labels_json,
                    max_concurrency = EXCLUDED.max_concurrency,
                    started_at = EXCLUDED.started_at,
                    last_heartbeat = EXCLUDED.last_heartbeat,
                    stopped_at = NULL
                RETURNING *
                """,
                (
                    worker_id,
                    hostname,
                    pid,
                    WorkerState.IDLE.value,
                    labels_json,
                    max_concurrency,
                    now,
                    now,
                ),
            ).fetchone()
        return self._worker_from_row(row)

    def heartbeat_worker(
        self,
        worker_id: str,
        state: WorkerState,
        current_job_id: Optional[str] = None,
    ) -> QueueWorkerRecord:
        now = self._clock()
        with self._connection() as connection:
            row = connection.execute(
                """
                UPDATE queue_workers
                SET state = %s, current_job_id = %s,
                    last_heartbeat = %s
                WHERE worker_id = %s
                RETURNING *
                """,
                (
                    state.value,
                    current_job_id,
                    now,
                    worker_id,
                ),
            ).fetchone()
        if row is None:
            raise QueueStoreError(f"worker is not registered: {worker_id}")
        return self._worker_from_row(row)

    def mark_worker_offline(self, worker_id: str) -> QueueWorkerRecord:
        now = self._clock()
        with self._connection() as connection:
            row = connection.execute(
                """
                UPDATE queue_workers
                SET state = %s, current_job_id = NULL,
                    last_heartbeat = %s, stopped_at = %s
                WHERE worker_id = %s
                RETURNING *
                """,
                (
                    WorkerState.OFFLINE.value,
                    now,
                    now,
                    worker_id,
                ),
            ).fetchone()
        if row is None:
            raise QueueStoreError(f"worker is not registered: {worker_id}")
        return self._worker_from_row(row)

    def get_worker(self, worker_id: str) -> QueueWorkerRecord:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM queue_workers WHERE worker_id = %s",
                (worker_id,),
            ).fetchone()
        if row is None:
            raise QueueStoreError(f"worker not found: {worker_id}")
        return self._worker_from_row(row)

    def list_workers(
        self,
        online_within_seconds: Optional[float] = None,
    ) -> List[QueueWorkerRecord]:
        query = "SELECT * FROM queue_workers"
        values = ()
        if online_within_seconds is not None:
            if online_within_seconds <= 0:
                raise QueueStoreError(
                    "online_within_seconds must be greater than 0"
                )
            cutoff = (
                self._clock().timestamp() - online_within_seconds
            )
            query += " WHERE last_heartbeat >= %s"
            values = (
                datetime.fromtimestamp(cutoff, tz=timezone.utc),
            )
        query += " ORDER BY last_heartbeat DESC, worker_id ASC"
        with self._connection() as connection:
            rows = connection.execute(query, values).fetchall()
        return [self._worker_from_row(row) for row in rows]

    def _initialize(self) -> None:
        with self._connection() as connection:
            for statement in POSTGRES_MIGRATIONS:
                connection.execute(statement)
            now = self._clock()
            connection.execute(
                """
                INSERT INTO queue_schema_migrations (
                    migration_id, applied_at
                ) VALUES (%s, %s)
                ON CONFLICT (migration_id) DO NOTHING
                """,
                ("001_initial_postgres_queue", now),
            )

    @contextmanager
    def _connection(self):
        connection = self._connect()
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _connect(self):
        if self._connection_factory is not None:
            return self._connection_factory()
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as error:
            raise QueueStoreBackendError(
                "PostgreSQL backend requires psycopg 3"
            ) from error
        return psycopg.connect(
            self.dsn,
            row_factory=dict_row,
        )

    @staticmethod
    def _job_values(job: QueueJob):
        return (
            job.job_id,
            job.target_type.value,
            job.target_path,
            json.dumps(job.parameters, ensure_ascii=False),
            job.permissions.model_dump_json(),
            json.dumps(job.required_labels, ensure_ascii=False),
            job.parallel_safe,
            job.state.value,
            job.priority,
            job.created_at,
            job.updated_at,
            job.started_at,
            job.claimed_at,
            job.worker_id,
            job.finished_at,
            job.attempts,
            job.recovery_count,
            job.report_path,
            job.error,
        )

    @staticmethod
    def _json_value(value):
        return value if isinstance(value, (dict, list)) else json.loads(value)

    @classmethod
    def _job_from_row(cls, row) -> QueueJob:
        return QueueJob(
            job_id=row["job_id"],
            target_type=DatasetTargetType(row["target_type"]),
            target_path=row["target_path"],
            parameters=cls._json_value(row["parameters_json"]),
            permissions=ExecutionPermissions.model_validate(
                cls._json_value(row["permissions_json"])
            ),
            required_labels=cls._json_value(
                row["required_labels_json"]
            ),
            parallel_safe=bool(row["parallel_safe"]),
            state=QueueState(row["state"]),
            priority=row["priority"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            started_at=row["started_at"],
            claimed_at=row["claimed_at"],
            worker_id=row["worker_id"],
            finished_at=row["finished_at"],
            attempts=row["attempts"],
            recovery_count=row["recovery_count"],
            report_path=row["report_path"],
            error=row["error"],
        )

    @classmethod
    def _worker_from_row(cls, row) -> QueueWorkerRecord:
        return QueueWorkerRecord(
            worker_id=row["worker_id"],
            hostname=row["hostname"],
            pid=row["pid"],
            state=WorkerState(row["state"]),
            current_job_id=row["current_job_id"],
            labels=cls._json_value(row["labels_json"]),
            max_concurrency=row["max_concurrency"],
            started_at=row["started_at"],
            last_heartbeat=row["last_heartbeat"],
            stopped_at=row["stopped_at"],
        )
