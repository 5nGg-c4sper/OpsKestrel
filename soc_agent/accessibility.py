"""Find and normalize macOS accessibility elements."""

from dataclasses import dataclass
from collections import Counter
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
        observed_roles = Counter()
        role_match_count = 0
        queue = [(root, 0)]
        visited = 0
        while queue and visited < max_nodes:
            element, depth = queue.pop(0)
            visited += 1
            role = self.adapter.role(element)
            title = self.adapter.title(element)
            description = self.adapter.description(element)
            value = self.adapter.value(element)
            observed_roles[role or "<none>"] += 1
            if (
                locator.role is None
                or (
                    role is not None
                    and role.casefold() == locator.role.casefold()
                )
            ):
                role_match_count += 1

            if self._matches_values(
                role,
                title,
                description,
                value,
                locator,
            ):
                frame = self.adapter.frame(element)
                if frame is not None:
                    x, y, width, height = frame
                    if width > 0 and height > 0:
                        matches.append(
                            UIElementMatch(
                                role=role,
                                title=title,
                                description=description,
                                value=value,
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
                f"matches={len(matches)}, visited_nodes={visited}, "
                f"role_match_count={role_match_count}, "
                f"observed_roles={dict(observed_roles.most_common(12))}"
            )
        return matches[locator.match_index]

    def _matches_values(
        self,
        role,
        title,
        description,
        value,
        locator: UIElementLocator,
    ) -> bool:
        comparisons = (
            ("role", role),
            ("title", title),
            ("description", description),
            ("value", value),
        )
        for field_name, actual in comparisons:
            expected = getattr(locator, field_name)
            if expected is None:
                continue
            if actual is None:
                return False
            if actual.casefold() != expected.casefold():
                return False
        if locator.text is not None:
            expected_text = locator.text.casefold()
            if not any(
                actual is not None
                and actual.casefold() == expected_text
                for actual in (title, description, value)
            ):
                return False
        return True


class PyObjCAccessibilityAdapter:
    """Minimal PyObjC bridge for accessibility inspection."""

    def __init__(self):
        try:
            import ApplicationServices
            from AppKit import NSWorkspace
        except ImportError as error:
            raise AccessibilityLookupError(
                "macOS accessibility support requires PyObjC"
            ) from error

        self._ax = ApplicationServices
        self._workspace = NSWorkspace.sharedWorkspace()

    def root_for_app(self, app_name: str):
        normalized = app_name.strip().casefold()
        applications = [
            app
            for app in self._workspace.runningApplications()
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
        children = list(value or [])
        if children or self.role(element) != "AXApplication":
            return children

        windows = self._copy_attribute(
            element,
            self._ax.kAXWindowsAttribute,
        )
        menu_bar = self._copy_attribute(
            element,
            self._ax.kAXMenuBarAttribute,
        )
        children.extend(windows or [])
        if menu_bar is not None:
            children.append(menu_bar)
        return children

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
        point_x, point_y = self._pair_values(point, "x", "y")
        width, height = self._pair_values(
            dimensions,
            "width",
            "height",
        )
        return (
            point_x,
            point_y,
            width,
            height,
        )

    @classmethod
    def _pair_values(cls, value, first, second):
        if hasattr(value, first) and hasattr(value, second):
            return (
                float(getattr(value, first)),
                float(getattr(value, second)),
            )
        if isinstance(value, (tuple, list)):
            if len(value) == 1:
                return cls._pair_values(value[0], first, second)
            if len(value) >= 2:
                if (
                    isinstance(value[0], (tuple, list))
                    and len(value[0]) >= 2
                ):
                    return cls._pair_values(
                        value[0],
                        first,
                        second,
                    )
                if (
                    len(value) == 2
                    and isinstance(value[1], (tuple, list))
                ):
                    return cls._pair_values(
                        value[1],
                        first,
                        second,
                    )
                return float(value[0]), float(value[1])
        raise AccessibilityLookupError(
            f"invalid AX value for {first}/{second}: {value!r}"
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
