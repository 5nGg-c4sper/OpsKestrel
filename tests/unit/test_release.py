"""Tests for offline release-readiness checks."""

import unittest
from pathlib import Path

from soc_agent.release import run_release_checks


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class ReleaseCheckTests(unittest.TestCase):
    def test_project_passes_offline_release_checks(self):
        payload = run_release_checks(PROJECT_ROOT)
        checks = {
            check["name"]: check for check in payload["checks"]
        }

        self.assertTrue(payload["ready"])
        self.assertEqual(payload["summary"]["failed"], 0)
        self.assertEqual(
            checks["fixture_reconciliation"]["status"],
            "passed",
        )
        self.assertEqual(
            checks["env_ignored"]["status"],
            "passed",
        )
        self.assertEqual(
            checks["entry_points"]["status"],
            "passed",
        )


if __name__ == "__main__":
    unittest.main()
