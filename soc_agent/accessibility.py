"""Find and normalize macOS accessibility elements."""

from dataclasses import dataclass
from typing import Any, List, Optional, Tuple

from soc_agent.task_models import UIElementLocator


class AccessibilityLookupError(RuntimeError):
    """Raised when an accessibility element cannot be found."""


@dataclass(frozen=True)
class UIElementMatch:
    role: Optional[str]
    title: Optional[str]
    description: Optional[str]
    value: Optional[str]
    x: float
    y: float
    width: float
    height: float

    @property
    def center_x(self) -> float:
        return self.x + self.width / 2

    @property
    def center_y(self) -> float:
        return self.y + self.height / 2


class AccessibilityLocator:
    """Search an injected accessibility tree."""

    def __init__(self, adapter):
        self.adapter = adapter

    def find(
        self,
        app_name: str,
        locator: UIElementLocator,
        max_depth: int = 12,
        max_nodes: int = 5000,
    ) -> UIElementMatch:
        root = self.adapter.root_for_app(app_name)
        screen_width, screen_height = self.adapter.screen_size()
        if screen_width <= 0 or screen_height <= 0:
            raise AccessibilityLookupError("invalid screen dimensions")

        matches = []
        queue = [(root, 0)]
        visited = 0
        while queue and visited < max_nodes:
            element, depth = queue.pop(0)
            visited += 1
            if self._matches(element, locator):
                frame = self.adapter.frame(element)
                if frame is not None:
                    x, y, width, height = frame
                    if width > 0 and height > 0:
                        matches.append(
                            UIElementMatch(
                                role=self.adapter.role(element),
                                title=self.adapter.title(element),
                                description=self.adapter.description(element),
                                value=self.adapter.value(element),
                                x=max(0.0, min(1.0, x / screen_width)),
                                y=max(0.0, min(1.0, y / screen_height)),
                                width=max(
                                    0.0,
                                    min(1.0, width / screen_width),
                                ),
                                height=max(
                                    0.0,
                                    min(1.0, height / screen_height),
                                ),
                            )
                        )
            if depth < max_depth:
                queue.extend(
                    (child, depth + 1)
                    for child in self.adapter.children(element)
                )

        if locator.match_index >= len(matches):
            raise AccessibilityLookupError(
                "accessibility element not found: "
                f"app={app_name!r}, locator={locator.model_dump()}, "
                f"matches={len(matches)}"
            )
        return matches[locator.match_index]

    def _matches(
        self,
        element,
        locator: UIElementLocator,
    ) -> bool:
        comparisons = (
            ("role", self.adapter.role(element)),
            ("title", self.adapter.title(element)),
            ("description", self.adapter.description(element)),
            ("value", self.adapter.value(element)),
        )
        for field_name, actual in comparisons:
            expected = getattr(locator, field_name)
            if expected is None:
                continue
            if actual is None:
                return False
            if actual.casefold() != expected.casefold():
                return False
        return True


class PyObjCAccessibilityAdapter:
    """Minimal PyObjC bridge for accessibility inspection."""

    def __init__(self):
        try:
            import ApplicationServices
            from AppKit import NSRunningApplication
        except ImportError as error:
            raise AccessibilityLookupError(
                "macOS accessibility support requires PyObjC"
            ) from error

        self._ax = ApplicationServices
        self._running_application = NSRunningApplication

    def root_for_app(self, app_name: str):
        normalized = app_name.strip().casefold()
        applications = [
            app
            for app in self._running_application.runningApplications()
            if (
                (app.localizedName() or "").strip().casefold()
                == normalized
                or (app.bundleIdentifier() or "").strip().casefold()
                == normalized
            )
        ]
        if not applications:
            raise AccessibilityLookupError(
                f"accessibility application is not running: {app_name}"
            )
        pid = applications[0].processIdentifier()
        return self._ax.AXUIElementCreateApplication(pid)

    def screen_size(self) -> Tuple[float, float]:
        import pyautogui

        width, height = pyautogui.size()
        return float(width), float(height)

    def children(self, element) -> List[Any]:
        value = self._copy_attribute(
            element,
            self._ax.kAXChildrenAttribute,
        )
        return list(value or [])

    def role(self, element) -> Optional[str]:
        return self._text_attribute(
            element,
            self._ax.kAXRoleAttribute,
        )

    def title(self, element) -> Optional[str]:
        return self._text_attribute(
            element,
            self._ax.kAXTitleAttribute,
        )

    def description(self, element) -> Optional[str]:
        return self._text_attribute(
            element,
            self._ax.kAXDescriptionAttribute,
        )

    def value(self, element) -> Optional[str]:
        return self._text_attribute(
            element,
            self._ax.kAXValueAttribute,
        )

    def frame(self, element) -> Optional[Tuple[float, float, float, float]]:
        position = self._copy_attribute(
            element,
            self._ax.kAXPositionAttribute,
        )
        size = self._copy_attribute(
            element,
            self._ax.kAXSizeAttribute,
        )
        if position is None or size is None:
            return None

        point = self._ax.AXValueGetValue(
            position,
            self._ax.kAXValueCGPointType,
            None,
        )
        dimensions = self._ax.AXValueGetValue(
            size,
            self._ax.kAXValueCGSizeType,
            None,
        )
        return (
            float(point.x),
            float(point.y),
            float(dimensions.width),
            float(dimensions.height),
        )

    def _copy_attribute(self, element, attribute):
        error, value = self._ax.AXUIElementCopyAttributeValue(
            element,
            attribute,
            None,
        )
        if error != 0:
            return None
        return value

    def _text_attribute(self, element, attribute) -> Optional[str]:
        value = self._copy_attribute(element, attribute)
        if value is None:
            return None
        text = str(value)
        return text if text else None
