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
                    state,
                    priority,
                    created_at,
                    updated_at,
                    started_at,
                    claimed_at,
                    finished_at,
                    attempts,
                    recovery_count,
                    report_path,
                    error
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
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

    def claim_next(self) -> Optional[QueueJob]:
        now = self._clock()
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT job_id
                FROM queue_jobs
                WHERE state = ?
                ORDER BY priority DESC, created_at ASC, job_id ASC
                LIMIT 1
                """,
                (QueueState.PENDING.value,),
            ).fetchone()
            if row is None:
                connection.commit()
                return None

            job_id = row["job_id"]
            updated = connection.execute(
                """
                UPDATE queue_jobs
                SET state = ?, started_at = ?, claimed_at = ?,
                    updated_at = ?, attempts = attempts + 1
                WHERE job_id = ? AND state = ?
                """,
                (
                    QueueState.RUNNING.value,
                    now.isoformat(),
                    now.isoformat(),
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

    def heartbeat(self, job_id: str) -> QueueJob:
        now = self._clock()
        with self._connection() as connection:
            updated = connection.execute(
                """
                UPDATE queue_jobs
                SET claimed_at = ?, updated_at = ?
                WHERE job_id = ? AND state = ?
                """,
                (
                    now.isoformat(),
                    now.isoformat(),
                    job_id,
                    QueueState.RUNNING.value,
                ),
            )
        if updated.rowcount != 1:
            raise QueueStoreError(
                f"queue job is not running: {job_id}"
            )
        return self.get(job_id)

    def recover_stale_jobs(
        self,
        stale_after_seconds: int,
        max_attempts: int = 3,
    ) -> List[QueueJob]:
        if stale_after_seconds < 1:
            raise QueueStoreError(
                "stale_after_seconds must be at least 1"
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

    def complete(
        self,
        job_id: str,
        state: QueueState,
        report_path: Optional[str] = None,
        error: Optional[str] = None,
    ) -> QueueJob:
        if state not in TERMINAL_QUEUE_STATES:
            raise QueueStoreError(
                f"queue job completion requires terminal state: {state}"
            )

        now = self._clock()
        with self._connection() as connection:
            updated = connection.execute(
                """
                UPDATE queue_jobs
                SET state = ?, finished_at = ?, updated_at = ?,
                    report_path = ?, error = ?
                WHERE job_id = ? AND state = ?
                """,
                (
                    state.value,
                    now.isoformat(),
                    now.isoformat(),
                    report_path,
                    error,
                    job_id,
                    QueueState.RUNNING.value,
                ),
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
                    state TEXT NOT NULL,
                    priority INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    started_at TEXT,
                    claimed_at TEXT,
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
            job.state.value,
            job.priority,
            job.created_at.isoformat(),
            job.updated_at.isoformat(),
            job.started_at.isoformat() if job.started_at else None,
            job.claimed_at.isoformat() if job.claimed_at else None,
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
