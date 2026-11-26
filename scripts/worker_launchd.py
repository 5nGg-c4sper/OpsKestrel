#!/usr/bin/env python3
"""Install and manage the SOC Agent launchd worker."""

import argparse
import os
import plistlib
import subprocess
import sys
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from soc_agent.launchd import (
    WorkerLaunchConfig,
    build_launch_agent_plist,
    service_label,
    write_launch_agent_plist,
)


def build_parser():
    parser = argparse.ArgumentParser(
        description="Manage the SOC Agent macOS launchd worker",
    )
    parser.add_argument(
        "command",
        choices=("install", "uninstall", "restart", "status", "render"),
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        default=PROJECT_ROOT,
    )
    parser.add_argument(
        "--python",
        type=Path,
        default=Path(sys.executable),
    )
    parser.add_argument("--worker-id", default=os.uname().nodename)
    parser.add_argument("--queue-db", default="reports/queue.db")
    parser.add_argument("--label", action="append", default=[])
    parser.add_argument("--poll-interval", type=float, default=2.0)
    parser.add_argument("--max-concurrency", type=int, default=1)
    parser.add_argument("--reports-dir", default="reports")
    parser.add_argument("--stale-after-seconds", type=float, default=3600.0)
    parser.add_argument("--max-attempts", type=int, default=3)
    parser.add_argument("--non-interactive", action="store_true")
    parser.add_argument("--output", type=Path, default=None)
    return parser


def make_config(args) -> WorkerLaunchConfig:
    return WorkerLaunchConfig(
        project_root=args.project_root,
        python_path=args.python,
        worker_id=args.worker_id,
        queue_db=args.queue_db,
        labels=args.label,
        poll_interval=args.poll_interval,
        max_concurrency=args.max_concurrency,
        reports_dir=args.reports_dir,
        stale_after_seconds=args.stale_after_seconds,
        max_attempts=args.max_attempts,
        non_interactive=args.non_interactive,
    )


def default_plist_path(config: WorkerLaunchConfig) -> Path:
    return (
        Path.home()
        / "Library"
        / "LaunchAgents"
        / f"{service_label(config.worker_id)}.plist"
    )


def launchctl(*args) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["launchctl", *args],
        check=False,
        capture_output=True,
        text=True,
    )


def gui_domain() -> str:
    return f"gui/{os.getuid()}"


def service_target(label: str) -> str:
    return f"{gui_domain()}/{label}"


def wait_until_unloaded(target: str, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while True:
        result = launchctl("print", target)
        if result.returncode != 0:
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.1)


def install(config: WorkerLaunchConfig) -> int:
    plist_path = write_launch_agent_plist(
        default_plist_path(config),
        config,
        create_log_dir=True,
    )
    label = service_label(config.worker_id)
    target = service_target(label)
    launchctl("bootout", target)
    if not wait_until_unloaded(target):
        print(f"Existing service did not unload: {label}")
        return 1
    result = launchctl(
        "bootstrap",
        gui_domain(),
        str(plist_path),
    )
    if result.returncode != 0:
        print(result.stderr.strip() or result.stdout.strip())
        return result.returncode
    launchctl("enable", f"{gui_domain()}/{label}")
    launchctl("kickstart", "-k", f"{gui_domain()}/{label}")
    print(f"Installed: {plist_path}")
    print(f"Service: {label}")
    return 0


def uninstall(config: WorkerLaunchConfig) -> int:
    label = service_label(config.worker_id)
    result = launchctl("bootout", service_target(label))
    plist_path = default_plist_path(config)
    if plist_path.exists():
        plist_path.unlink()
    if result.returncode not in (0, 3):
        print(result.stderr.strip() or result.stdout.strip())
        return result.returncode
    print(f"Uninstalled: {label}")
    return 0


def status(config: WorkerLaunchConfig) -> int:
    label = service_label(config.worker_id)
    result = launchctl(
        "print",
        f"{gui_domain()}/{label}",
    )
    if result.stdout:
        print(result.stdout)
    if result.stderr:
        print(result.stderr, file=sys.stderr)
    return result.returncode


def render(config: WorkerLaunchConfig, output: Path) -> int:
    path = write_launch_agent_plist(output, config)
    print(path)
    return 0


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    config = make_config(args)
    if args.command == "install":
        return install(config)
    if args.command == "uninstall":
        return uninstall(config)
    if args.command == "restart":
        result = install(config)
        return result
    if args.command == "status":
        return status(config)

    output = args.output or (
        Path.home()
        / "Library"
        / "LaunchAgents"
        / f"{service_label(config.worker_id)}.plist"
    )
    return render(config, output)


if __name__ == "__main__":
    raise SystemExit(main())
