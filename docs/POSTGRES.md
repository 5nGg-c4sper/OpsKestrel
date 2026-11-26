# PostgreSQL Queue Deployment

PostgreSQL mode is intended for multiple macOS Workers sharing one network
queue. SQLite remains the default for a single machine.

## Local Integration Environment

Requirements:

- Docker with Compose support
- Python integration dependencies

Start PostgreSQL:

```bash
docker compose -f compose.postgres.yml up -d
```

Install dependencies and run integration tests:

```bash
./venv/bin/python -m pip install -r requirements-integration.txt

export OPSKESTREL_TEST_POSTGRES_DSN='postgresql://opskestrel:opskestrel_test@localhost:5432/opskestrel_test'
./venv/bin/python -m unittest discover -s tests/integration -p 'test_*.py' -v
```

Stop and remove the temporary database:

```bash
docker compose -f compose.postgres.yml down -v
```

The Compose database is test-only and uses ephemeral data.

## Production Setup

Use a dedicated database and a least-privilege role:

```text
postgresql://opskestrel:password@db.example.com/opskestrel
```

Recommended controls:

- Require TLS for remote connections.
- Store the DSN in the Worker environment or secret manager, never in Git.
- Restrict database access to known Worker hosts.
- Back up the queue database.
- Apply migrations from one Worker before starting the rest.
- Use stable Worker IDs and capability labels for scheduling.
- Keep non-`parallel_safe` GUI jobs on the default exclusive path.

## Worker Registration

Start each Mac with a stable Worker ID and its capabilities:

```bash
./venv/bin/opskestrel queue run \
  --queue-db 'postgresql://opskestrel:password@db.example.com/opskestrel' \
  --worker-id office-mac-1 \
  --label office-mac \
  --label high-memory \
  --drain
```

Query online Workers:

```bash
./venv/bin/opskestrel queue workers \
  --queue-db 'postgresql://opskestrel:password@db.example.com/opskestrel'
```

## Scheduling Guarantees

- Pending jobs use `FOR UPDATE SKIP LOCKED` so two Workers cannot claim the
  same row.
- Required job labels must be a subset of Worker labels.
- Non-parallel-safe jobs use `queue_exclusive_locks` to serialize GUI work
  across all Workers.
- Explicitly parallel-safe jobs can use additional concurrency slots.
- Worker ownership is checked for heartbeat and completion.
- Expired leases are requeued until `--max-attempts` is exhausted.

## Continuous Integration

`.github/workflows/postgres-integration.yml` starts PostgreSQL 16 on GitHub
Actions and runs the real integration suite on pushes and pull requests.

The integration suite also starts two independent queue-store clients to
verify:

- parallel-safe jobs are claimed without overlap
- GUI jobs remain globally serialized through `queue_exclusive_locks`
- a stale job held by one Worker can be recovered and reclaimed by another
- Worker registry and current-job ownership remain visible across clients
