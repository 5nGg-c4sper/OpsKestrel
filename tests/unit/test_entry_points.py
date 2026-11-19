"""Tests for package and command-line entry points."""

import os
import runpy
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class EntryPointTests(unittest.TestCase):
    def test_python_module_help_runs_without_desktop_access(self):
        result = subprocess.run(
            [sys.executable, "-m", "soc_agent", "--help"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("usage: soc-agent", result.stdout)
        self.assertIn("run", result.stdout)
        self.assertIn("suite", result.stdout)

    def test_setup_preserves_operate_and_adds_soc_agent(self):
        original_directory = os.getcwd()
        os.chdir(PROJECT_ROOT)
        try:
            with (
                patch("setuptools.find_packages", return_value=[]),
                patch("setuptools.setup") as setup_mock,
            ):
                runpy.run_path(str(PROJECT_ROOT / "setup.py"))
        finally:
            os.chdir(original_directory)

        setup_options = setup_mock.call_args.kwargs
        console_scripts = setup_options["entry_points"]["console_scripts"]
        self.assertIn("operate=operate.main:main_entry", console_scripts)
        self.assertIn("soc-agent=soc_agent.cli:main", console_scripts)


if __name__ == "__main__":
    unittest.main()
