# macOS launchd Worker

`scripts/worker_launchd.py` installs a long-running SOC Agent queue Worker as
a per-user LaunchAgent. The Worker starts after the user logs in and restarts
after an abnormal exit.

## Prerequisites

- Log in to the macOS graphical session before installing the service.
- Keep the Mac unlocked while GUI jobs can run.
- Grant Accessibility and Screen Recording permission to the process that
  launches the service. Verify the same permission for a normal
  `soc-agent queue worker` run first.
- Install the project in the active virtual environment and keep `.env` in the
  project root. The plist never contains API keys or database credentials.
- Use a stable `--worker-id` and capability labels when multiple Macs share a
  PostgreSQL queue.

## Render Without Installing

Render a plist for inspection without starting a Worker:

```bash
./venv/bin/python scripts/worker_launchd.py render \
  --worker-id office-mac-1 \
  --label office-mac \
  --output /private/tmp/soc-agent-worker.plist
```

The output is an XML plist. Review `ProgramArguments`, `WorkingDirectory`, and
the log paths before installing it.

## Install

For a local SQLite queue:

```bash
./venv/bin/python scripts/worker_launchd.py install \
  --worker-id office-mac-1 \
  --label office-mac
```

For a shared PostgreSQL queue:

```bash
./venv/bin/python scripts/worker_launchd.py install \
  --worker-id office-mac-1 \
  --label office-mac \
  --queue-db 'postgresql://soc_agent:password@db.example.com/soc_agent'
```

The default service name is
`com.soc-agent.worker.<sanitized-worker-id>`. The LaunchAgent plist is stored
under `~/Library/LaunchAgents/`; stdout and stderr are written under
`~/Library/Logs/SOCAgent/`.

The installer does not enable `--non-interactive` automatically. Add it only
when the queue contains tasks whose approval steps are safe to accept without
an operator.

## Status and Lifecycle

```bash
./venv/bin/python scripts/worker_launchd.py status \
  --worker-id office-mac-1

./venv/bin/python scripts/worker_launchd.py restart \
  --worker-id office-mac-1 \
  --label office-mac

./venv/bin/python scripts/worker_launchd.py uninstall \
  --worker-id office-mac-1
```

Check the queue registry and logs after installation:

```bash
./venv/bin/soc-agent queue workers
tail -f ~/Library/Logs/SOCAgent/worker.out.log
tail -f ~/Library/Logs/SOCAgent/worker.err.log
```

The Worker runs inside the `Aqua` login session with `ProcessType=Interactive`.
Normal exit is not restarted; abnormal exit is restarted after the launchd
throttle interval.
