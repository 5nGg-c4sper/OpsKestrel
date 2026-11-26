"""Build macOS launchd worker configurations."""

import plistlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional


DEFAULT_SERVICE_PREFIX = "com.opskestrel.worker"


@dataclass(frozen=True)
class WorkerLaunchConfig:
    project_root: Path
    python_path: Path
    worker_id: str
    queue_db: str = "reports/queue.db"
    labels: List[str] = field(default_factory=list)
    poll_interval: float = 2.0
    max_concurrency: int = 1
    reports_dir: str = "reports"
    non_interactive: bool = False
    stale_after_seconds: float = 3600.0
    max_attempts: int = 3
    log_dir: Optional[Path] = None


def service_label(worker_id: str) -> str:
    safe_id = re.sub(r"[^A-Za-z0-9.-]+", "-", worker_id).strip(".-")
    safe_id = safe_id.lower() or "default"
    return f"{DEFAULT_SERVICE_PREFIX}.{safe_id}"


def build_program_arguments(config: WorkerLaunchConfig) -> List[str]:
    if not config.worker_id.strip():
        raise ValueError("worker_id must not be empty")
    if config.poll_interval <= 0:
        raise ValueError("poll_interval must be greater than 0")
    if config.max_concurrency < 1:
        raise ValueError("max_concurrency must be at least 1")
    if config.stale_after_seconds <= 0:
        raise ValueError("stale_after_seconds must be greater than 0")
    if config.max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")

    arguments = [
        str(config.python_path),
        "-m",
        "opskestrel.cli",
        "queue",
        "worker",
        "--queue-db",
        config.queue_db,
        "--worker-id",
        config.worker_id,
        "--poll-interval",
        str(config.poll_interval),
        "--max-concurrency",
        str(config.max_concurrency),
        "--reports-dir",
        config.reports_dir,
        "--stale-after-seconds",
        str(config.stale_after_seconds),
        "--max-attempts",
        str(config.max_attempts),
    ]
    for label in config.labels:
        arguments.extend(("--label", label))
    if config.non_interactive:
        arguments.append("--non-interactive")
    return arguments


def build_launch_agent_plist(config: WorkerLaunchConfig) -> Dict:
    project_root = config.project_root.expanduser().resolve()
    log_dir = (
        config.log_dir.expanduser().resolve()
        if config.log_dir is not None
        else Path.home() / "Library" / "Logs" / "OpsKestrel"
    )
    stdout_path = log_dir / "worker.out.log"
    stderr_path = log_dir / "worker.err.log"

    return {
        "Label": service_label(config.worker_id),
        "ProgramArguments": build_program_arguments(config),
        "WorkingDirectory": str(project_root),
        "RunAtLoad": True,
        "KeepAlive": {"SuccessfulExit": False},
        "ProcessType": "Interactive",
        "LimitLoadToSessionType": "Aqua",
        "ThrottleInterval": 10,
        "StandardOutPath": str(stdout_path),
        "StandardErrorPath": str(stderr_path),
        "EnvironmentVariables": {
            "HOME": str(Path.home()),
            "PATH": (
                f"{config.python_path.expanduser().resolve().parent}:"
                "/opt/homebrew/bin:/usr/local/bin:"
                "/usr/bin:/bin:/usr/sbin:/sbin"
            ),
        },
    }


def write_launch_agent_plist(
    path: Path,
    config: WorkerLaunchConfig,
    create_log_dir: bool = False,
) -> Path:
    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    plist = build_launch_agent_plist(config)
    temp_path = path.with_suffix(".plist.tmp")
    with temp_path.open("wb") as plist_file:
        plistlib.dump(plist, plist_file, sort_keys=True)
    temp_path.replace(path)

    if create_log_dir:
        log_dir = Path(plist["StandardOutPath"]).parent
        log_dir.mkdir(parents=True, exist_ok=True)
    return path
