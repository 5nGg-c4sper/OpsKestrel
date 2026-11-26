"""Tests for queue backend selection and schema migrations."""

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from opskestrel.queue_backend import (
    QueueStore,
    QueueStoreBackendError,
    create_queue_store,
)
from opskestrel.postgres_queue_store import (
    POSTGRES_CLAIM_SQL,
    POSTGRES_MIGRATIONS,
)
from opskestrel.queue_store import SQLiteQueueStore
from opskestrel.task_models import DatasetTargetType


class QueueBackendTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)

    def test_plain_path_creates_sqlite_backend(self):
        database_path = self.root / "queue.db"

        store = create_queue_store(database_path)

        self.assertIsInstance(store, SQLiteQueueStore)
        self.assertIsInstance(store, QueueStore)
        job = store.enqueue(
            DatasetTargetType.TASK,
            "task.json",
        )
        self.assertEqual(store.get(job.job_id).job_id, job.job_id)

    def test_sqlite_url_creates_sqlite_backend(self):
        database_path = self.root / "queue.db"

        store = create_queue_store(f"sqlite:///{database_path}")

        self.assertIsInstance(store, SQLiteQueueStore)
        self.assertEqual(store.database_path, database_path)

    def test_unsupported_backend_is_rejected(self):
        with self.assertRaisesRegex(
            QueueStoreBackendError,
            "unsupported queue backend: mysql",
        ):
            create_queue_store(
                "mysql://localhost/self_operating_computer"
            )

    def test_postgres_url_selects_postgres_backend(self):
        sentinel = object()
        with patch(
            "opskestrel.postgres_queue_store.PostgreSQLQueueStore",
            return_value=sentinel,
        ) as backend:
            store = create_queue_store(
                "postgresql://localhost/self_operating_computer"
            )

        self.assertIs(store, sentinel)
        backend.assert_called_once_with(
            "postgresql://localhost/self_operating_computer",
            clock=None,
        )

    def test_postgres_claim_uses_skip_locked_and_label_filter(self):
        self.assertIn("FOR UPDATE SKIP LOCKED", POSTGRES_CLAIM_SQL)
        self.assertIn("required_labels_json <@", POSTGRES_CLAIM_SQL)
        schema_sql = "\n".join(POSTGRES_MIGRATIONS)
        self.assertIn("queue_exclusive_locks", schema_sql)
        self.assertIn("JSONB", schema_sql)

    def test_migrations_are_recorded_once(self):
        database_path = self.root / "queue.db"
        SQLiteQueueStore(database_path)

        with closing(sqlite3.connect(database_path)) as connection:
            first = connection.execute(
                """
                SELECT migration_id
                FROM queue_schema_migrations
                ORDER BY migration_id
                """
            ).fetchall()
        SQLiteQueueStore(database_path)
        with closing(sqlite3.connect(database_path)) as connection:
            second = connection.execute(
                """
                SELECT migration_id
                FROM queue_schema_migrations
                ORDER BY migration_id
                """
            ).fetchall()

        self.assertEqual(first, second)
        self.assertEqual(
            [row[0] for row in first],
            [
                "001_create_queue_schema",
                "002_add_queue_runtime_columns",
                "003_add_worker_registry_columns",
            ],
        )


if __name__ == "__main__":
    unittest.main()
