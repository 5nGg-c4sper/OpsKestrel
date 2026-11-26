"""Versioned SQLite migrations for queue storage."""

import sqlite3
from datetime import datetime, timezone
from typing import Callable, Dict, List, Tuple


Migration = Tuple[str, Callable[[sqlite3.Connection], None]]


def apply_sqlite_migrations(
    connection: sqlite3.Connection,
    clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
) -> List[str]:
    """Apply pending migrations and return their identifiers."""
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS queue_schema_migrations (
            migration_id TEXT PRIMARY KEY,
            applied_at TEXT NOT NULL
        )
        """
    )
    applied = {
        row["migration_id"]
        for row in connection.execute(
            "SELECT migration_id FROM queue_schema_migrations"
        ).fetchall()
    }

    newly_applied = []
    for migration_id, migration in MIGRATIONS:
        if migration_id in applied:
            continue
        migration(connection)
        connection.execute(
            """
            INSERT INTO queue_schema_migrations (
                migration_id, applied_at
            ) VALUES (?, ?)
            """,
            (migration_id, clock().isoformat()),
        )
        newly_applied.append(migration_id)
    return newly_applied


def _create_queue_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS queue_jobs (
            job_id TEXT PRIMARY KEY,
            target_type TEXT NOT NULL,
            target_path TEXT NOT NULL,
            parameters_json TEXT NOT NULL,
            permissions_json TEXT NOT NULL DEFAULT '{}',
            required_labels_json TEXT NOT NULL DEFAULT '[]',
            parallel_safe INTEGER NOT NULL DEFAULT 0,
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
            max_concurrency INTEGER NOT NULL DEFAULT 1,
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


def _add_queue_columns(connection: sqlite3.Connection) -> None:
    _add_missing_columns(
        connection,
        "queue_jobs",
        {
            "claimed_at": "TEXT",
            "permissions_json": "TEXT NOT NULL DEFAULT '{}'",
            "required_labels_json": (
                "TEXT NOT NULL DEFAULT '[]'"
            ),
            "parallel_safe": "INTEGER NOT NULL DEFAULT 0",
            "worker_id": "TEXT",
            "attempts": "INTEGER NOT NULL DEFAULT 0",
            "recovery_count": "INTEGER NOT NULL DEFAULT 0",
        },
    )


def _add_worker_columns(connection: sqlite3.Connection) -> None:
    _add_missing_columns(
        connection,
        "queue_workers",
        {
            "labels_json": "TEXT NOT NULL DEFAULT '[]'",
            "max_concurrency": "INTEGER NOT NULL DEFAULT 1",
        },
    )


def _add_missing_columns(
    connection: sqlite3.Connection,
    table: str,
    columns: Dict[str, str],
) -> None:
    existing = {
        row["name"]
        for row in connection.execute(
            f"PRAGMA table_info({table})"
        ).fetchall()
    }
    for column, definition in columns.items():
        if column not in existing:
            connection.execute(
                f"ALTER TABLE {table} ADD COLUMN "
                f"{column} {definition}"
            )


MIGRATIONS: List[Migration] = [
    ("001_create_queue_schema", _create_queue_schema),
    ("002_add_queue_runtime_columns", _add_queue_columns),
    ("003_add_worker_registry_columns", _add_worker_columns),
]
