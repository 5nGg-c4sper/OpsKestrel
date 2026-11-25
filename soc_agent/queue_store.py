"""SQLite-backed persistent task queue."""

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional, Union

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


class QueueStoreError(RuntimeError):
    """Raised when a queue operation cannot be completed."""


class SQLiteQueueStore:
    """Persist and atomically claim queue jobs."""

    def __init__(
        self,
        database_path: Union[str, Path] = "reports/queue.db",
        clock: Optional[Callable[[], datetime]] = None,
    ):
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._initialize()

    def enqueue(
        self,
        target_type: DatasetTargetType,
        target_path: Union[str, Path],
        parameters: Optional[Dict[str, str]] = None,
        permissions: Optional[ExecutionPermissions] = None,
        required_labels: Optional[List[str]] = None,
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
            priority=priority,
            created_at=now,
            updated_at=now,
        )
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO queue_jobs (
                    job_id,
                    target_type,
                    target_path,
                    parameters_json,
                    permissions_json,
                    required_labels_json,
                    state,
                    priority,
                    created_at,
                    updated_at,
                    started_at,
                    claimed_at,
                    worker_id,
                    finished_at,
                    attempts,
                    recovery_count,
                    report_path,
                    error
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,
                self._to_row(job),
            )
        return job

    def get(self, job_id: str) -> QueueJob:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM queue_jobs WHERE job_id = ?",
                (job_id,),
            ).fetchone()
        if row is None:
            raise QueueStoreError(f"queue job not found: {job_id}")
        return self._from_row(row)

    def list_jobs(
        self,
        state: Optional[QueueState] = None,
    ) -> List[QueueJob]:
        query = "SELECT * FROM queue_jobs"
        values = ()
        if state is not None:
            query += " WHERE state = ?"
            values = (state.value,)
        query += (
            " ORDER BY priority DESC, created_at ASC, job_id ASC"
        )
        with self._connection() as connection:
            rows = connection.execute(query, values).fetchall()
        return [self._from_row(row) for row in rows]

    def claim_next(
        self,
        worker_id: str = "local",
        worker_labels: Optional[List[str]] = None,
    ) -> Optional[QueueJob]:
        if not worker_id.strip():
            raise QueueStoreError("worker_id must not be empty")
        now = self._clock()
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                """
                SELECT job_id, required_labels_json
                FROM queue_jobs
                WHERE state = ?
                ORDER BY priority DESC, created_at ASC, job_id ASC
                """,
                (QueueState.PENDING.value,),
            ).fetchall()
            available_labels = {
                label.casefold()
                for label in (worker_labels or [])
            }
            row = next(
                (
                    candidate
                    for candidate in rows
                    if {
                        label.casefold()
                        for label in json.loads(
                            candidate["required_labels_json"]
                        )
                    }.issubset(available_labels)
                ),
                None,
            )
            if row is None:
                connection.commit()
                return None

            job_id = row["job_id"]
            updated = connection.execute(
                """
                UPDATE queue_jobs
                SET state = ?, started_at = ?, claimed_at = ?,
                    worker_id = ?,
                    updated_at = ?, attempts = attempts + 1
                WHERE job_id = ? AND state = ?
                """,
                (
                    QueueState.RUNNING.value,
                    now.isoformat(),
                    now.isoformat(),
                    worker_id,
                    now.isoformat(),
                    job_id,
                    QueueState.PENDING.value,
                ),
            )
            if updated.rowcount != 1:
                connection.rollback()
                raise QueueStoreError(
                    f"failed to claim queue job: {job_id}"
                )
            connection.commit()

        return self.get(job_id)

    def heartbeat(
        self,
        job_id: str,
        worker_id: Optional[str] = None,
    ) -> QueueJob:
        now = self._clock()
        owner_clause = ""
        values = [
            now.isoformat(),
            now.isoformat(),
            job_id,
            QueueState.RUNNING.value,
        ]
        if worker_id is not None:
            owner_clause = " AND worker_id = ?"
            values.append(worker_id)
        with self._connection() as connection:
            updated = connection.execute(
                f"""
                UPDATE queue_jobs
                SET claimed_at = ?, updated_at = ?
                WHERE job_id = ? AND state = ?{owner_clause}
                """,
                tuple(values),
            )
        if updated.rowcount != 1:
            raise QueueStoreError(
                f"queue job is not running: {job_id}"
            )
        return self.get(job_id)

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
        recovered_ids = []

        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                """
                SELECT job_id, attempts, claimed_at
                FROM queue_jobs
                WHERE state = ? AND claimed_at IS NOT NULL
                ORDER BY claimed_at ASC, job_id ASC
                """,
                (QueueState.RUNNING.value,),
            ).fetchall()

            for row in rows:
                claimed_at = datetime.fromisoformat(row["claimed_at"])
                if claimed_at.timestamp() > cutoff:
                    continue

                if row["attempts"] >= max_attempts:
                    connection.execute(
                        """
                        UPDATE queue_jobs
                        SET state = ?, finished_at = ?, updated_at = ?,
                            recovery_count = recovery_count + 1,
                            error = ?
                        WHERE job_id = ? AND state = ?
                        """,
                        (
                            QueueState.FAILED.value,
                            now.isoformat(),
                            now.isoformat(),
                            "stale queue lease exceeded maximum attempts",
                            row["job_id"],
                            QueueState.RUNNING.value,
                        ),
                    )
                else:
                    connection.execute(
                        """
                        UPDATE queue_jobs
                        SET state = ?, started_at = NULL, claimed_at = NULL,
                            worker_id = NULL,
                            updated_at = ?, recovery_count = recovery_count + 1,
                            error = ?
                        WHERE job_id = ? AND state = ?
                        """,
                        (
                            QueueState.PENDING.value,
                            now.isoformat(),
                            "stale queue lease recovered",
                            row["job_id"],
                            QueueState.RUNNING.value,
                        ),
                    )
                recovered_ids.append(row["job_id"])
            connection.commit()

        return [self.get(job_id) for job_id in recovered_ids]

    def register_worker(
        self,
        worker_id: str,
        hostname: str,
        pid: int,
        labels: Optional[List[str]] = None,
    ) -> QueueWorkerRecord:
        if not worker_id.strip():
            raise QueueStoreError("worker_id must not be empty")
        now = self._clock()
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO queue_workers (
                    worker_id, hostname, pid, state, current_job_id, labels_json,
                    started_at, last_heartbeat, stopped_at
                ) VALUES (?, ?, ?, ?, NULL, ?, ?, ?, NULL)
                ON CONFLICT(worker_id) DO UPDATE SET
                    hostname = excluded.hostname,
                    pid = excluded.pid,
                    state = excluded.state,
                    current_job_id = NULL,
                    labels_json = excluded.labels_json,
                    started_at = excluded.started_at,
                    last_heartbeat = excluded.last_heartbeat,
                    stopped_at = NULL
                """,
                (
                    worker_id,
                    hostname,
                    pid,
                    WorkerState.IDLE.value,
                    json.dumps(
                        list(labels or []),
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    now.isoformat(),
                    now.isoformat(),
                ),
            )
        return self.get_worker(worker_id)

    def heartbeat_worker(
        self,
        worker_id: str,
        state: WorkerState,
        current_job_id: Optional[str] = None,
    ) -> QueueWorkerRecord:
        now = self._clock()
        with self._connection() as connection:
            updated = connection.execute(
                """
                UPDATE queue_workers
                SET state = ?, current_job_id = ?, last_heartbeat = ?
                WHERE worker_id = ?
                """,
                (
                    state.value,
                    current_job_id,
                    now.isoformat(),
                    worker_id,
                ),
            )
        if updated.rowcount != 1:
            raise QueueStoreError(f"worker is not registered: {worker_id}")
        return self.get_worker(worker_id)

    def mark_worker_offline(self, worker_id: str) -> QueueWorkerRecord:
        now = self._clock()
        with self._connection() as connection:
            updated = connection.execute(
                """
                UPDATE queue_workers
                SET state = ?, current_job_id = NULL,
                    last_heartbeat = ?, stopped_at = ?
                WHERE worker_id = ?
                """,
                (
                    WorkerState.OFFLINE.value,
                    now.isoformat(),
                    now.isoformat(),
                    worker_id,
                ),
            )
        if updated.rowcount != 1:
            raise QueueStoreError(f"worker is not registered: {worker_id}")
        return self.get_worker(worker_id)

    def get_worker(self, worker_id: str) -> QueueWorkerRecord:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM queue_workers WHERE worker_id = ?",
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
            query += " WHERE last_heartbeat >= ?"
            values = (
                datetime.fromtimestamp(
                    cutoff,
                    tz=timezone.utc,
                ).isoformat(),
            )
        query += " ORDER BY last_heartbeat DESC, worker_id ASC"
        with self._connection() as connection:
            rows = connection.execute(query, values).fetchall()
        return [self._worker_from_row(row) for row in rows]

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
        owner_clause = ""
        values = [
            state.value,
            now.isoformat(),
            now.isoformat(),
            report_path,
            error,
            job_id,
            QueueState.RUNNING.value,
        ]
        if worker_id is not None:
            owner_clause = " AND worker_id = ?"
            values.append(worker_id)

        with self._connection() as connection:
            updated = connection.execute(
                f"""
                UPDATE queue_jobs
                SET state = ?, finished_at = ?, updated_at = ?,
                    report_path = ?, error = ?
                WHERE job_id = ? AND state = ?{owner_clause}
                """,
                tuple(values),
            )
        if updated.rowcount != 1:
            raise QueueStoreError(
                f"queue job is not running: {job_id}"
            )
        return self.get(job_id)

    def _initialize(self) -> None:
        with self._connection() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS queue_jobs (
                    job_id TEXT PRIMARY KEY,
                    target_type TEXT NOT NULL,
                    target_path TEXT NOT NULL,
                    parameters_json TEXT NOT NULL,
                    permissions_json TEXT NOT NULL,
                    required_labels_json TEXT NOT NULL DEFAULT '[]',
                    state TEXT NOT NULL,
                    priority INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    started_at TEXT,
                    claimed_at TEXT,
                    worker_id TEXT,
                    finished_at TEXT,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    recovery_count INTEGER NOT NULL DEFAULT 0,
                    report_path TEXT,
                    error TEXT
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS queue_workers (
                    worker_id TEXT PRIMARY KEY,
                    hostname TEXT NOT NULL,
                    pid INTEGER NOT NULL,
                    state TEXT NOT NULL,
                    current_job_id TEXT,
                    labels_json TEXT NOT NULL DEFAULT '[]',
                    started_at TEXT NOT NULL,
                    last_heartbeat TEXT NOT NULL,
                    stopped_at TEXT
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_queue_pending
                ON queue_jobs (state, priority DESC, created_at, job_id)
                """
            )
            columns = {
                row["name"]
                for row in connection.execute(
                    "PRAGMA table_info(queue_jobs)"
                ).fetchall()
            }
            migrations = {
                "claimed_at": "ALTER TABLE queue_jobs ADD COLUMN claimed_at TEXT",
                "permissions_json": (
                    "ALTER TABLE queue_jobs ADD COLUMN "
                    "permissions_json TEXT NOT NULL DEFAULT '{}'"
                ),
                "required_labels_json": (
                    "ALTER TABLE queue_jobs ADD COLUMN "
                    "required_labels_json TEXT NOT NULL DEFAULT '[]'"
                ),
                "worker_id": (
                    "ALTER TABLE queue_jobs ADD COLUMN worker_id TEXT"
                ),
                "attempts": (
                    "ALTER TABLE queue_jobs ADD COLUMN "
                    "attempts INTEGER NOT NULL DEFAULT 0"
                ),
                "recovery_count": (
                    "ALTER TABLE queue_jobs ADD COLUMN "
                    "recovery_count INTEGER NOT NULL DEFAULT 0"
                ),
            }
            for column, statement in migrations.items():
                if column not in columns:
                    connection.execute(statement)
            worker_columns = {
                row["name"]
                for row in connection.execute(
                    "PRAGMA table_info(queue_workers)"
                ).fetchall()
            }
            if "labels_json" not in worker_columns:
                connection.execute(
                    "ALTER TABLE queue_workers ADD COLUMN "
                    "labels_json TEXT NOT NULL DEFAULT '[]'"
                )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.database_path,
            timeout=30,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=30000")
        return connection

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

    @staticmethod
    def _to_row(job: QueueJob):
        return (
            job.job_id,
            job.target_type.value,
            job.target_path,
            json.dumps(
                job.parameters,
                ensure_ascii=False,
                sort_keys=True,
            ),
            job.permissions.model_dump_json(),
            json.dumps(
                job.required_labels,
                ensure_ascii=False,
                sort_keys=True,
            ),
            job.state.value,
            job.priority,
            job.created_at.isoformat(),
            job.updated_at.isoformat(),
            job.started_at.isoformat() if job.started_at else None,
            job.claimed_at.isoformat() if job.claimed_at else None,
            job.worker_id,
            job.finished_at.isoformat() if job.finished_at else None,
            job.attempts,
            job.recovery_count,
            job.report_path,
            job.error,
        )

    @staticmethod
    def _from_row(row: sqlite3.Row) -> QueueJob:
        return QueueJob(
            job_id=row["job_id"],
            target_type=DatasetTargetType(row["target_type"]),
            target_path=row["target_path"],
            parameters=json.loads(row["parameters_json"]),
            permissions=ExecutionPermissions.model_validate_json(
                row["permissions_json"]
            ),
            required_labels=json.loads(row["required_labels_json"]),
            state=QueueState(row["state"]),
            priority=row["priority"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            started_at=(
                datetime.fromisoformat(row["started_at"])
                if row["started_at"]
                else None
            ),
            claimed_at=(
                datetime.fromisoformat(row["claimed_at"])
                if row["claimed_at"]
                else None
            ),
            worker_id=row["worker_id"],
            finished_at=(
                datetime.fromisoformat(row["finished_at"])
                if row["finished_at"]
                else None
            ),
            attempts=row["attempts"],
            recovery_count=row["recovery_count"],
            report_path=row["report_path"],
            error=row["error"],
        )

    @staticmethod
    def _worker_from_row(row: sqlite3.Row) -> QueueWorkerRecord:
        return QueueWorkerRecord(
            worker_id=row["worker_id"],
            hostname=row["hostname"],
            pid=row["pid"],
            state=WorkerState(row["state"]),
            current_job_id=row["current_job_id"],
            labels=json.loads(row["labels_json"]),
            started_at=datetime.fromisoformat(row["started_at"]),
            last_heartbeat=datetime.fromisoformat(
                row["last_heartbeat"]
            ),
            stopped_at=(
                datetime.fromisoformat(row["stopped_at"])
                if row["stopped_at"]
                else None
            ),
        )
