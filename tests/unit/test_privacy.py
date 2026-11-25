"""Tests for screenshot redaction and privacy handling."""

import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image
from pydantic import ValidationError

from soc_agent.actions.executor import ActionExecutor
from soc_agent.cli import run_task
from soc_agent.privacy import (
    ScreenshotRedactionError,
    capture_screenshot,
    redact_image_file,
)
from soc_agent.reporting.report import ReportWriter
from soc_agent.task_models import RedactionRegion, TaskStatus


class PixelEnvironment:
    def __init__(self, color=(255, 0, 0)):
        self.color = color
        self.calls = []

    def screenshot(self, output_path):
        path = Path(output_path)
        Image.new("RGB", (100, 50), self.color).save(path)
        self.calls.append(str(path))
        return path


class InspectingVisionProvider:
    def __init__(self):
        self.snapshots = []

    def verify(self, image_path, statement):
        with Image.open(image_path) as image:
            self.snapshots.append(image.copy())
        return True


class PrivacyTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)

    def test_redaction_region_validates_bounds(self):
        RedactionRegion(x=0.1, y=0.2, width=0.3, height=0.4)

        invalid_regions = (
            {"x": 0.8, "width": 0.3},
            {"y": 0.8, "height": 0.3},
            {"width": 0},
            {"x": -0.1},
        )
        for values in invalid_regions:
            with self.subTest(values=values):
                payload = {
                    "x": 0,
                    "y": 0,
                    "width": 0.5,
                    "height": 0.5,
                    **values,
                }
                with self.assertRaises(ValidationError):
                    RedactionRegion.model_validate(payload)

    def test_redact_image_fills_normalized_regions(self):
        image_path = self.root / "screen.png"
        Image.new("RGB", (100, 50), (255, 0, 0)).save(image_path)

        redact_image_file(
            image_path,
            [
                RedactionRegion(
                    x=0,
                    y=0,
                    width=0.5,
                    height=1,
                )
            ],
        )

        with Image.open(image_path) as image:
            self.assertEqual(image.getpixel((10, 10)), (0, 0, 0))
            self.assertEqual(image.getpixel((90, 10)), (255, 0, 0))

    def test_capture_failure_removes_unredacted_temporary_file(self):
        class InvalidEnvironment:
            def screenshot(self, output_path):
                Path(output_path).write_bytes(b"not-an-image")

        output_path = self.root / "redacted.png"

        with self.assertRaises(ScreenshotRedactionError):
            capture_screenshot(
                InvalidEnvironment(),
                output_path,
                [RedactionRegion(x=0, y=0, width=1, height=1)],
            )

        self.assertFalse(output_path.exists())
        self.assertEqual(
            list(self.root.glob(".*-*.png")),
            [],
        )

    def test_run_task_redacts_before_upload_and_artifact_copy(self):
        task_path = self.root / "redacted_task.json"
        task_path.write_text(
            json.dumps(
                {
                    "name": "redacted_task",
                    "redaction_regions": [
                        {
                            "x": 0,
                            "y": 0,
                            "width": 0.5,
                            "height": 1,
                        }
                    ],
                    "steps": [
                        {
                            "type": "verify_vision",
                            "prompt": "页面是否正常？",
                        },
                        {"type": "done", "summary": "finished"},
                    ],
                }
            ),
            encoding="utf-8",
        )
        environment = PixelEnvironment()
        provider = InspectingVisionProvider()
        reporter = ReportWriter(self.root / "reports")
        screenshot_path = self.root / "verification.png"

        result = run_task(
            task_path,
            environment,
            ActionExecutor(environment, settle_delay=0),
            provider,
            reporter,
            screenshot_path=screenshot_path,
        )

        self.assertEqual(result.status, TaskStatus.PASSED)
        uploaded = provider.snapshots[0]
        self.assertEqual(uploaded.getpixel((10, 10)), (0, 0, 0))
        self.assertEqual(uploaded.getpixel((90, 10)), (255, 0, 0))

        artifact_path = reporter.output_dir / result.steps[0].screenshot
        with Image.open(artifact_path) as artifact:
            self.assertEqual(artifact.getpixel((10, 10)), (0, 0, 0))
            self.assertEqual(artifact.getpixel((90, 10)), (255, 0, 0))


if __name__ == "__main__":
    unittest.main()
