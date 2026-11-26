"""Tests for macOS launchd Worker configuration."""

import importlib.util
import os
import plistlib
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from soc_agent.cli import build_parser
from soc_agent.launchd import (
    WorkerLaunchConfig,
    build_launch_agent_plist,
    build_program_arguments,
    service_label,
    write_launch_agent_plist,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "worker_launchd.py"


def load_worker_launchd_script():
    spec = importlib.util.spec_from_file_location(
        "worker_launchd_script",
        SCRIPT_PATH,
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class WorkerLaunchConfigTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        self.python_path = self.root / "venv" / "bin" / "python"
        self.log_dir = self.root / "logs"
        self.config = WorkerLaunchConfig(
            project_root=self.root,
            python_path=self.python_path,
            worker_id="office-mac-1",
            queue_db="reports/queue.db",
            labels=["office-mac", "high-memory"],
            poll_interval=1.5,
            max_concurrency=2,
            reports_dir="custom-reports",
            non_interactive=True,
            stale_after_seconds=1800,
            max_attempts=4,
            log_dir=self.log_dir,
        )

    def test_service_label_is_stable_and_safe(self):
        self.assertEqual(
            service_label("Office Mac/1"),
            "com.soc-agent.worker.office-mac-1",
        )
        self.assertEqual(
            service_label("..."),
            "com.soc-agent.worker.default",
        )

    def test_program_arguments_include_worker_options(self):
        arguments = build_program_arguments(self.config)

        self.assertEqual(arguments[:5], [
            str(self.python_path),
            "-m",
            "soc_agent.cli",
            "queue",
            "worker",
        ])
        self.assert_option(arguments, "--queue-db", "reports/queue.db")
        self.assert_option(arguments, "--worker-id", "office-mac-1")
        self.assert_option(arguments, "--poll-interval", "1.5")
        self.assert_option(arguments, "--max-concurrency", "2")
        self.assert_option(arguments, "--reports-dir", "custom-reports")
        self.assert_option(arguments, "--stale-after-seconds", "1800")
        self.assert_option(arguments, "--max-attempts", "4")
        self.assertIn("--non-interactive", arguments)
        self.assertEqual(
            self.option_values(arguments, "--label"),
            ["office-mac", "high-memory"],
        )

    def test_program_arguments_are_accepted_by_worker_cli(self):
        arguments = build_program_arguments(self.config)

        parsed = build_parser().parse_args(arguments[3:])

        self.assertEqual(parsed.command, "queue")
        self.assertEqual(parsed.queue_command, "worker")
        self.assertEqual(parsed.poll_interval, 1.5)
        self.assertEqual(parsed.stale_after_seconds, 1800.0)
        self.assertEqual(parsed.max_concurrency, 2)

    def test_launch_agent_plist_uses_absolute_paths_and_aqua_session(self):
        plist = build_launch_agent_plist(self.config)

        self.assertEqual(
            plist["Label"],
            "com.soc-agent.worker.office-mac-1",
        )
        self.assertEqual(
            plist["WorkingDirectory"],
            str(self.root.resolve()),
        )
        self.assertTrue(plist["RunAtLoad"])
        self.assertEqual(
            plist["KeepAlive"],
            {"SuccessfulExit": False},
        )
        self.assertEqual(plist["ProcessType"], "Interactive")
        self.assertEqual(plist["LimitLoadToSessionType"], "Aqua")
        self.assertEqual(
            plist["StandardOutPath"],
            str((self.log_dir / "worker.out.log").resolve()),
        )
        self.assertEqual(
            plist["StandardErrorPath"],
            str((self.log_dir / "worker.err.log").resolve()),
        )
        launch_path = plist["EnvironmentVariables"]["PATH"]
        self.assertTrue(
            launch_path.startswith(str(self.python_path.parent.resolve()))
        )
        self.assertIn("/usr/sbin", launch_path.split(":"))
        self.assertIn("/sbin", launch_path.split(":"))

    def test_plist_does_not_embed_api_credentials(self):
        with patch.dict(
            os.environ,
            {
                "OPENAI_API_KEY": "secret-api-key",
                "OPENAI_BASE_URL": "https://secret.example/v1",
            },
        ):
            plist = build_launch_agent_plist(self.config)

        serialized = plistlib.dumps(plist)
        self.assertNotIn(b"OPENAI_API_KEY", serialized)
        self.assertNotIn(b"secret-api-key", serialized)
        self.assertNotIn(b"OPENAI_BASE_URL", serialized)
        self.assertNotIn(b"secret.example", serialized)

    def test_invalid_worker_options_are_rejected(self):
        invalid_options = (
            ("worker_id", ""),
            ("poll_interval", 0),
            ("max_concurrency", 0),
            ("stale_after_seconds", 0),
            ("max_attempts", 0),
        )

        for option_name, value in invalid_options:
            with self.subTest(option=option_name):
                config = WorkerLaunchConfig(
                    project_root=self.root,
                    python_path=self.python_path,
                    worker_id="office-mac-1",
                )
                object.__setattr__(config, option_name, value)
                with self.assertRaises(ValueError):
                    build_program_arguments(config)

    def test_plist_is_written_atomically_and_can_be_read_back(self):
        output_path = self.root / "LaunchAgents" / "worker.plist"

        result = write_launch_agent_plist(
            output_path,
            self.config,
            create_log_dir=True,
        )

        self.assertEqual(result, output_path.resolve())
        with output_path.open("rb") as plist_file:
            plist = plistlib.load(plist_file)
        self.assertEqual(
            plist["Label"],
            "com.soc-agent.worker.office-mac-1",
        )
        self.assertTrue(self.log_dir.exists())
        self.assertFalse(output_path.with_suffix(".plist.tmp").exists())

    def test_rendering_does_not_create_runtime_log_directory(self):
        output_path = self.root / "Rendered" / "worker.plist"

        write_launch_agent_plist(output_path, self.config)

        self.assertTrue(output_path.exists())
        self.assertFalse(self.log_dir.exists())

    def test_script_install_uses_launchctl_and_writes_plist(self):
        script = load_worker_launchd_script()
        plist_path = self.root / "LaunchAgents" / "worker.plist"
        calls = []

        def fake_launchctl(*arguments):
            calls.append(arguments)
            if arguments[0] == "print":
                return subprocess.CompletedProcess(
                    ["launchctl", *arguments],
                    113,
                    stdout="",
                    stderr="service not found",
                )
            return subprocess.CompletedProcess(
                ["launchctl", *arguments],
                0,
                stdout="",
                stderr="",
            )

        with patch.object(script, "launchctl", side_effect=fake_launchctl), \
                patch.object(
                    script,
                    "default_plist_path",
                    return_value=plist_path,
                ), \
                patch.object(script, "gui_domain", return_value="gui/501"):
            exit_code = script.install(self.config)

        self.assertEqual(exit_code, 0)
        self.assertTrue(plist_path.exists())
        self.assertEqual(
            calls,
            [
                ("bootout", "gui/501/com.soc-agent.worker.office-mac-1"),
                ("print", "gui/501/com.soc-agent.worker.office-mac-1"),
                ("bootstrap", "gui/501", str(plist_path.resolve())),
                ("enable", "gui/501/com.soc-agent.worker.office-mac-1"),
                (
                    "kickstart",
                    "-k",
                    "gui/501/com.soc-agent.worker.office-mac-1",
                ),
            ],
        )

    def test_script_uninstall_tolerates_missing_service(self):
        script = load_worker_launchd_script()
        plist_path = self.root / "LaunchAgents" / "worker.plist"
        write_launch_agent_plist(plist_path, self.config)

        with patch.object(
            script,
            "launchctl",
            return_value=subprocess.CompletedProcess(
                ["launchctl"],
                3,
                stdout="",
                stderr="service not found",
            ),
        ), patch.object(
            script,
            "default_plist_path",
            return_value=plist_path,
        ), patch.object(
            script,
            "gui_domain",
            return_value="gui/501",
        ):
            exit_code = script.uninstall(self.config)

        self.assertEqual(exit_code, 0)
        self.assertFalse(plist_path.exists())

    def test_script_install_stops_when_existing_service_does_not_unload(self):
        script = load_worker_launchd_script()
        plist_path = self.root / "LaunchAgents" / "worker.plist"

        with patch.object(
            script,
            "launchctl",
            return_value=subprocess.CompletedProcess(
                ["launchctl"],
                0,
                stdout="service is still running",
                stderr="",
            ),
        ), patch.object(
            script,
            "default_plist_path",
            return_value=plist_path,
        ), patch.object(
            script,
            "wait_until_unloaded",
            return_value=False,
        ), patch.object(
            script,
            "gui_domain",
            return_value="gui/501",
        ):
            exit_code = script.install(self.config)

        self.assertEqual(exit_code, 1)
        self.assertTrue(plist_path.exists())

    def test_script_status_returns_launchctl_result(self):
        script = load_worker_launchd_script()

        with patch.object(
            script,
            "launchctl",
            return_value=subprocess.CompletedProcess(
                ["launchctl"],
                0,
                stdout="worker is running",
                stderr="",
            ),
        ), patch.object(
            script,
            "gui_domain",
            return_value="gui/501",
        ):
            exit_code = script.status(self.config)

        self.assertEqual(exit_code, 0)

    def assert_option(self, arguments, option, expected):
        index = arguments.index(option)
        self.assertEqual(arguments[index + 1], expected)

    def option_values(self, arguments, option):
        values = []
        for index, argument in enumerate(arguments):
            if argument == option:
                values.append(arguments[index + 1])
        return values
