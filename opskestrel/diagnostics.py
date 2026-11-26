"""Read-only runtime diagnostics for OpsKestrel deployments."""

import os
import platform
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable, Dict, List, Mapping, Optional

from opskestrel.config import AgentConfig
from opskestrel.queue_backend import create_queue_store


class DiagnosticStatus(str, Enum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"


@dataclass(frozen=True)
class DiagnosticCheck:
    name: str
    status: DiagnosticStatus
    message: str

    def to_dict(self) -> Dict[str, str]:
        return {
            "name": self.name,
            "status": self.status.value,
            "message": self.message,
        }


@dataclass(frozen=True)
class DiagnosticReport:
    checks: List[DiagnosticCheck]

    @property
    def healthy(self) -> bool:
        return not any(
            check.status == DiagnosticStatus.FAIL
            for check in self.checks
        )

    def to_dict(self) -> Dict:
        return {
            "status": "pass" if self.healthy else "fail",
            "checks": [check.to_dict() for check in self.checks],
        }


def default_macos_permissions():
    try:
        import ApplicationServices
        import Quartz
    except ImportError as error:
        raise RuntimeError(
            "PyObjC Quartz is required for macOS permission checks"
        ) from error

    accessibility = bool(ApplicationServices.AXIsProcessTrusted())
    screen_recording = None
    probe = getattr(Quartz, "CGPreflightScreenCaptureAccess", None)
    if probe is not None:
        screen_recording = bool(probe())
    return accessibility, screen_recording


def default_report_directory_probe(path: str) -> None:
    report_path = Path(path)
    report_path.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        dir=report_path,
        prefix=".opskestrel-doctor-",
        delete=True,
    ):
        pass


class DiagnosticsRunner:
    """Evaluate runtime prerequisites with injectable platform probes."""

    def __init__(
        self,
        env: Optional[Mapping[str, str]] = None,
        platform_name: Optional[str] = None,
        macos_permission_probe: Optional[Callable] = None,
        command_runner: Optional[Callable] = None,
        queue_store_factory: Optional[Callable] = None,
        report_directory_probe: Optional[Callable[[str], None]] = None,
        uid: Optional[int] = None,
    ):
        self.env = dict(os.environ if env is None else env)
        self.platform_name = platform_name or platform.system()
        self.macos_permission_probe = (
            macos_permission_probe or default_macos_permissions
        )
        self.command_runner = command_runner or subprocess.run
        self.queue_store_factory = queue_store_factory or create_queue_store
        self.report_directory_probe = (
            report_directory_probe or default_report_directory_probe
        )
        self.uid = os.getuid() if uid is None else uid

    def run(
        self,
        queue_db: str = "reports/queue.db",
        reports_dir: Optional[str] = None,
        worker_id: Optional[str] = None,
        online_within_seconds: float = 300,
    ) -> DiagnosticReport:
        if online_within_seconds <= 0:
            raise ValueError(
                "online_within_seconds must be greater than 0"
            )

        checks = [
            self._check_python(),
            self._check_platform(),
            self._check_config(),
        ]

        if self.platform_name == "Darwin":
            checks.append(self._check_gui_session())
            checks.extend(self._check_macos_permissions())
        else:
            checks.append(
                DiagnosticCheck(
                    "gui_session",
                    DiagnosticStatus.FAIL,
                    "macOS GUI session check requires Darwin",
                )
            )

        checks.append(
            self._check_reports_directory(reports_dir)
        )
        store, queue_check = self._check_queue_backend(queue_db)
        checks.append(queue_check)
        checks.append(
            self._check_worker(
                store,
                worker_id=worker_id,
                online_within_seconds=online_within_seconds,
            )
        )
        return DiagnosticReport(checks)

    @staticmethod
    def _check_python() -> DiagnosticCheck:
        version = platform.python_version()
        if sys.version_info < (3, 9):
            return DiagnosticCheck(
                "python",
                DiagnosticStatus.FAIL,
                f"Python {version} is unsupported; Python 3.9+ required",
            )
        return DiagnosticCheck(
            "python",
            DiagnosticStatus.PASS,
            f"Python {version}",
        )

    def _check_platform(self) -> DiagnosticCheck:
        if self.platform_name == "Darwin":
            return DiagnosticCheck(
                "platform",
                DiagnosticStatus.PASS,
                "macOS",
            )
        return DiagnosticCheck(
            "platform",
            DiagnosticStatus.FAIL,
            f"expected Darwin, got {self.platform_name}",
        )

    def _check_config(self) -> DiagnosticCheck:
        try:
            config = AgentConfig.from_env(self.env)
        except Exception as error:
            return DiagnosticCheck(
                "configuration",
                DiagnosticStatus.FAIL,
                str(error),
            )
        return DiagnosticCheck(
            "configuration",
            DiagnosticStatus.PASS,
            f"model={config.model}",
        )

    def _check_gui_session(self) -> DiagnosticCheck:
        result = self.command_runner(
            ["launchctl", "print", f"gui/{self.uid}"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            return DiagnosticCheck(
                "gui_session",
                DiagnosticStatus.PASS,
                f"gui/{self.uid} is available",
            )
        detail = (result.stderr or result.stdout or "").strip()
        return DiagnosticCheck(
            "gui_session",
            DiagnosticStatus.FAIL,
            detail or f"gui/{self.uid} is unavailable",
        )

    def _check_macos_permissions(self):
        try:
            accessibility, screen_recording = (
                self.macos_permission_probe()
            )
        except Exception as error:
            message = str(error)
            return [
                DiagnosticCheck(
                    "accessibility",
                    DiagnosticStatus.FAIL,
                    message,
                ),
                DiagnosticCheck(
                    "screen_recording",
                    DiagnosticStatus.FAIL,
                    message,
                ),
            ]

        accessibility_status = (
            DiagnosticStatus.PASS
            if accessibility
            else DiagnosticStatus.FAIL
        )
        screen_status = (
            DiagnosticStatus.FAIL
            if screen_recording is False
            else DiagnosticStatus.PASS
        )
        return [
            DiagnosticCheck(
                "accessibility",
                accessibility_status,
                (
                    "current process is trusted"
                    if accessibility
                    else (
                        "current process lacks Accessibility; permissions "
                        "apply to the app that launches OpsKestrel"
                    )
                ),
            ),
            DiagnosticCheck(
                "screen_recording",
                screen_status,
                (
                    "current process is permitted"
                    if screen_recording is True
                    else (
                        "probe unavailable"
                        if screen_recording is None
                        else (
                            "current process lacks Screen Recording; "
                            "permissions apply to the launching app"
                        )
                    )
                ),
            ),
        ]

    def _check_reports_directory(
        self,
        reports_dir: Optional[str],
    ) -> DiagnosticCheck:
        path = (
            reports_dir
            or self.env.get("REPORTS_DIR")
            or "reports"
        )
        try:
            self.report_directory_probe(path)
        except Exception as error:
            return DiagnosticCheck(
                "reports_directory",
                DiagnosticStatus.FAIL,
                f"{path}: {error}",
            )
        return DiagnosticCheck(
            "reports_directory",
            DiagnosticStatus.PASS,
            f"{path} is writable",
        )

    def _check_queue_backend(self, queue_db: str):
        try:
            store = self.queue_store_factory(queue_db)
            store.list_jobs()
        except Exception as error:
            return None, DiagnosticCheck(
                "queue_backend",
                DiagnosticStatus.FAIL,
                f"{queue_db}: {error}",
            )
        return store, DiagnosticCheck(
            "queue_backend",
            DiagnosticStatus.PASS,
            queue_db,
        )

    def _check_worker(
        self,
        store,
        worker_id: Optional[str],
        online_within_seconds: float,
    ) -> DiagnosticCheck:
        if store is None:
            return DiagnosticCheck(
                "worker",
                DiagnosticStatus.FAIL,
                "queue backend is unavailable",
            )
        try:
            workers = store.list_workers(
                online_within_seconds=online_within_seconds
            )
        except Exception as error:
            return DiagnosticCheck(
                "worker",
                DiagnosticStatus.FAIL,
                str(error),
            )

        if worker_id is not None:
            matching = [
                worker
                for worker in workers
                if worker.worker_id == worker_id
            ]
            if not matching:
                return DiagnosticCheck(
                    "worker",
                    DiagnosticStatus.FAIL,
                    f"worker is not online: {worker_id}",
                )
            return DiagnosticCheck(
                "worker",
                DiagnosticStatus.PASS,
                (
                    f"{worker_id} is {matching[0].state.value} "
                    f"with pid {matching[0].pid}"
                ),
            )

        if not workers:
            return DiagnosticCheck(
                "worker",
                DiagnosticStatus.WARN,
                "no Worker heartbeat in the online window",
            )
        return DiagnosticCheck(
            "worker",
            DiagnosticStatus.PASS,
            f"{len(workers)} Worker(s) online",
        )
