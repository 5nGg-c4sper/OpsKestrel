"""Tests for run evidence archive creation."""

import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from opskestrel.evidence_bundle import (
    EvidenceBundleError,
    create_evidence_bundle,
)


class EvidenceBundleTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        self.run_dir = self.root / "run-001"
        self.run_dir.mkdir()
        (self.run_dir / "run.json").write_text(
            '{"state": "finished"}\n',
            encoding="utf-8",
        )
        evidence_dir = self.run_dir / "evidence"
        evidence_dir.mkdir()
        (evidence_dir / "invoice.png").write_bytes(b"fake-png")
        (self.run_dir / "run.log").write_text(
            "completed\n",
            encoding="utf-8",
        )
        (self.run_dir / ".evidence-bundle.zip.stale.tmp").write_text(
            "stale",
            encoding="utf-8",
        )

    def test_bundle_contains_manifest_and_all_run_files(self):
        bundle_path = create_evidence_bundle(self.run_dir)

        self.assertEqual(
            bundle_path,
            (self.run_dir / "evidence-bundle.zip").resolve(),
        )
        with zipfile.ZipFile(bundle_path) as archive:
            names = set(archive.namelist())
            self.assertEqual(
                names,
                {
                    "manifest.json",
                    "run.json",
                    "run.log",
                    "evidence/invoice.png",
                },
            )
            manifest = json.loads(
                archive.read("manifest.json").decode("utf-8")
            )
            self.assertEqual(manifest["run"], "run-001")
            self.assertEqual(manifest["algorithm"], "sha256")
            files = {
                item["path"]: item for item in manifest["files"]
            }
            self.assertEqual(
                files["evidence/invoice.png"]["sha256"],
                hashlib.sha256(b"fake-png").hexdigest(),
            )
            self.assertEqual(
                files["run.log"]["size_bytes"],
                len(b"completed\n"),
            )

    def test_rebuilding_bundle_replaces_target_without_nesting_it(self):
        create_evidence_bundle(self.run_dir)
        create_evidence_bundle(self.run_dir)

        with zipfile.ZipFile(
            self.run_dir / "evidence-bundle.zip"
        ) as archive:
            self.assertNotIn(
                "evidence-bundle.zip",
                archive.namelist(),
            )

    def test_missing_run_directory_is_rejected(self):
        with self.assertRaises(EvidenceBundleError):
            create_evidence_bundle(self.run_dir / "missing")


if __name__ == "__main__":
    unittest.main()
