"""macOS screen, application, keyboard, and mouse operations."""

import time
from pathlib import Path
from typing import Callable, List, Optional


class MacOSEnvironment:
    """Thin adapter around the existing macOS automation primitives."""

    def __init__(
        self,
        system=None,
        screenshot_capture: Optional[Callable] = None,
        scale: float = 0.5,
        sleep_fn: Optional[Callable[[float], None]] = None,
    ):
        scale = float(scale)
        if scale <= 0:
            raise ValueError("scale must be greater than 0")

        self.scale = scale
        self._system = system
        self._screenshot_capture = screenshot_capture
        self._sleep = sleep_fn or time.sleep

    def _get_system(self):
        if self._system is None:
            from operate.utils.operating_system import OperatingSystem

            self._system = OperatingSystem()
        return self._system

    def _get_screenshot_capture(self):
        if self._screenshot_capture is None:
            from operate.utils.screenshot import capture_screen_with_cursor

            self._screenshot_capture = capture_screen_with_cursor
        return self._screenshot_capture

    def open_app(self, app_name: str) -> None:
        if not app_name or not app_name.strip():
            raise ValueError("app_name must not be empty")
        self._get_system().open_app(app_name)

    def activate_app(self, app_name: str) -> None:
        if not app_name or not app_name.strip():
            raise ValueError("app_name must not be empty")
        self._get_system().activate_app(app_name)

    def write(self, content: str) -> None:
        if content is None:
            raise ValueError("content must not be None")
        self._get_system().write(content)

    def press(self, keys: List[str]) -> None:
        if not keys:
            raise ValueError("keys must not be empty")
        self._get_system().press(keys)

    def click(self, x: float, y: float) -> None:
        x = float(x)
        y = float(y)
        if not 0 <= x <= 1 or not 0 <= y <= 1:
            raise ValueError("click coordinates must be between 0 and 1")
        self._get_system().mouse({"x": x, "y": y})

    def wait(self, seconds: float) -> None:
        seconds = float(seconds)
        if seconds <= 0:
            raise ValueError("wait duration must be greater than 0")
        self._sleep(seconds)

    def screenshot(self, output_path) -> Path:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._get_screenshot_capture()(str(path), scale=self.scale)
        return path
