"""Tests for package and command-line entry points."""

import ast
import subprocess
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class EntryPointTests(unittest.TestCase):
    def test_python_module_help_runs_without_desktop_access(self):
        result = subprocess.run(
            [sys.executable, "-m", "opskestrel", "--help"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("usage: opskestrel", result.stdout)
        self.assertIn("run", result.stdout)
        self.assertIn("suite", result.stdout)

    def test_setup_preserves_operate_and_adds_opskestrel(self):
        setup_tree = ast.parse(
            (PROJECT_ROOT / "setup.py").read_text(encoding="utf-8")
        )
        setup_call = next(
            node
            for node in ast.walk(setup_tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "setup"
        )
        entry_points = next(
            keyword.value
            for keyword in setup_call.keywords
            if keyword.arg == "entry_points"
        )
        console_scripts_node = next(
            value
            for key, value in zip(entry_points.keys, entry_points.values)
            if isinstance(key, ast.Constant) and key.value == "console_scripts"
        )
        console_scripts = [
            element.value for element in console_scripts_node.elts
        ]

        self.assertIn("operate=operate.main:main_entry", console_scripts)
        self.assertIn("opskestrel=opskestrel.cli:main", console_scripts)


if __name__ == "__main__":
    unittest.main()
