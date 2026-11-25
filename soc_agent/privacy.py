"""Screenshot redaction helpers."""

import os
import tempfile
from pathlib import Path
from typing import Iterable, Union

from PIL import Image, ImageDraw

from soc_agent.task_models import RedactionRegion


class ScreenshotRedactionError(RuntimeError):
    """Raised when a screenshot cannot be safely redacted."""


def capture_screenshot(
    environment,
    output_path,
    redaction_regions: Iterable[RedactionRegion],
) -> Path:
    """Capture a screenshot and redact it before exposing the final file."""
    path = Path(output_path)
    regions = list(redaction_regions)
    if not regions:
        environment.screenshot(path)
        return path

    path.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, raw_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.stem}-",
        suffix=path.suffix or ".png",
    )
    os.close(file_descriptor)
    raw_path = Path(raw_name)

    try:
        environment.screenshot(raw_path)
        redact_image_file(raw_path, regions)
        raw_path.replace(path)
    except Exception as error:
        raise ScreenshotRedactionError(
            f"failed to capture redacted screenshot: {error}"
        ) from error
    finally:
        if raw_path.exists():
            raw_path.unlink()

    return path


def redact_image_file(
    image_path: Union[str, Path],
    redaction_regions: Iterable[RedactionRegion],
) -> Path:
    """Fill configured normalized regions with opaque black."""
    path = Path(image_path)
    regions = list(redaction_regions)
    if not regions:
        return path

    temporary_path = path.with_name(
        f".{path.stem}-redacted{path.suffix or '.png'}"
    )
    try:
        with Image.open(path) as image:
            redacted = image.copy()
            draw = ImageDraw.Draw(redacted)
            for region in regions:
                left = round(region.x * redacted.width)
                top = round(region.y * redacted.height)
                right = min(
                    redacted.width,
                    max(left + 1, round(
                        (region.x + region.width) * redacted.width
                    )),
                )
                bottom = min(
                    redacted.height,
                    max(top + 1, round(
                        (region.y + region.height) * redacted.height
                    )),
                )
                draw.rectangle(
                    (left, top, right, bottom),
                    fill=(0, 0, 0, 255),
                )
            redacted.save(
                temporary_path,
                format=image.format or "PNG",
            )
        temporary_path.replace(path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()

    return path
