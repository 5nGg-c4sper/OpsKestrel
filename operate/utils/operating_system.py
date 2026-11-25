import pyautogui
import platform
import time
import math
import pyperclip
import subprocess
import os

from operate.utils.misc import convert_percent_to_decimal


class OperatingSystem:
    def open_app(self, app_name):
        try:
            if platform.system() == "Darwin":
                normalized_name = app_name.strip().lower()
                app_paths = {
                    "calculator": "/System/Applications/Calculator.app",
                    "计算器": "/System/Applications/Calculator.app",
                    "textedit": "/System/Applications/TextEdit.app",
                    "text editor": "/System/Applications/TextEdit.app",
                    "文本编辑": "/System/Applications/TextEdit.app",
                    "safari": "/System/Volumes/Preboot/Cryptexes/App/System/Applications/Safari.app",
                    "safari浏览器": "/System/Volumes/Preboot/Cryptexes/App/System/Applications/Safari.app",
                    "notes": "/System/Applications/Notes.app",
                    "备忘录": "/System/Applications/Notes.app",
                    "finder": "/System/Library/CoreServices/Finder.app",
                    "访达": "/System/Library/CoreServices/Finder.app",
                }
                app_path = app_paths.get(normalized_name)
                command = (
                    ["open", app_path]
                    if app_path and os.path.exists(app_path)
                    else ["open", "-a", app_name]
                )
                subprocess.run(
                    command,
                    check=True,
                    capture_output=True,
                    text=True,
                )
                self._activate_macos_app(app_name, app_path)
            else:
                raise RuntimeError("open_app is currently supported on macOS only")
        except Exception as e:
            print("[OperatingSystem][open_app] error:", e)

    def activate_app(self, app_name):
        self.open_app(app_name)

    def _activate_macos_app(self, app_name, app_path):
        try:
            from AppKit import (
                NSApplicationActivateIgnoringOtherApps,
                NSRunningApplication,
                NSWorkspace,
            )
            from Foundation import NSBundle

            workspace = NSWorkspace.sharedWorkspace()
            bundle = (
                NSBundle.bundleWithPath_(app_path)
                if app_path
                else None
            )
            bundle_id = bundle.bundleIdentifier() if bundle else None

            running_apps = []
            if bundle_id:
                running_apps = list(
                    NSRunningApplication
                    .runningApplicationsWithBundleIdentifier_(bundle_id)
                )
            else:
                running_apps = [
                    app
                    for app in workspace.runningApplications()
                    if app.localizedName() == app_name
                ]

            if not running_apps and app_path:
                launched = workspace.launchApplication_(app_path)
                if launched is not None:
                    running_apps = [launched]

            for app in running_apps:
                app.activateWithOptions_(
                    NSApplicationActivateIgnoringOtherApps
                )
            time.sleep(0.2)
        except Exception as activation_error:
            print(
                "[OperatingSystem][activate_app] error:",
                activation_error,
            )

    def write(self, content):
        try:
            content = content.replace("\\n", "\n")

            normalized_math = content.translate(
                str.maketrans(
                    {
                        "×": "*",
                        "÷": "/",
                        "−": "-",
                        "–": "-",
                        "＝": "=",
                    }
                )
            )
            if (
                normalized_math != content
                and normalized_math.isascii()
                and all(
                    char in "0123456789+-*/().,= \t\r\n%"
                    for char in normalized_math
                )
            ):
                content = normalized_math

            # PyAutoGUI can only type characters present in the keyboard map.
            # On macOS, post native Unicode keyboard events for non-ASCII text.
            if any(ord(char) > 127 for char in content):
                if platform.system() == "Darwin":
                    try:
                        import Quartz

                        for char in content:
                            utf16_length = len(char.encode("utf-16-le")) // 2
                            key_down = Quartz.CGEventCreateKeyboardEvent(
                                None, 0, True
                            )
                            key_up = Quartz.CGEventCreateKeyboardEvent(
                                None, 0, False
                            )
                            Quartz.CGEventKeyboardSetUnicodeString(
                                key_down, utf16_length, char
                            )
                            Quartz.CGEventPost(Quartz.kCGHIDEventTap, key_down)
                            Quartz.CGEventPost(Quartz.kCGHIDEventTap, key_up)
                            time.sleep(0.05)
                        return
                    except Exception as unicode_error:
                        print(
                            "[OperatingSystem][write] Unicode event error:",
                            unicode_error,
                        )

                # Fallback for platforms that support Unicode clipboard paste.
                previous_clipboard = pyperclip.paste()
                pyperclip.copy(content)
                time.sleep(0.1)
                pyautogui.hotkey("ctrl", "v")
                time.sleep(0.2)
                pyperclip.copy(previous_clipboard)
                return

            for char in content:
                pyautogui.write(char)
                time.sleep(0.05)
        except Exception as e:
            print("[OperatingSystem][write] error:", e)

    def press(self, keys):
        try:
            # PyAutoGUI releases combination keys in reverse order, which is
            # required for shortcuts such as Command+Tab.
            pyautogui.hotkey(*keys, interval=0.05)
        except Exception as e:
            print("[OperatingSystem][press] error:", e)

    def mouse(self, click_detail):
        try:
            x = convert_percent_to_decimal(click_detail.get("x"))
            y = convert_percent_to_decimal(click_detail.get("y"))

            if click_detail and isinstance(x, float) and isinstance(y, float):
                self.click_at_percentage(x, y)

        except Exception as e:
            print("[OperatingSystem][mouse] error:", e)

    def click_at_percentage(
        self,
        x_percentage,
        y_percentage,
        duration=0.1,
        circle_radius=50,
        circle_duration=0.05,
    ):
        try:
            x_percentage = float(x_percentage)
            y_percentage = float(y_percentage)
            if not (0 <= x_percentage <= 1 and 0 <= y_percentage <= 1):
                raise ValueError(
                    f"click coordinates must be between 0 and 1: "
                    f"x={x_percentage}, y={y_percentage}"
                )

            screen_width, screen_height = pyautogui.size()
            x_pixel = min(screen_width - 1, int(screen_width * x_percentage))
            y_pixel = min(screen_height - 1, int(screen_height * y_percentage))

            pyautogui.moveTo(x_pixel, y_pixel, duration=duration)

            start_time = time.time()
            while time.time() - start_time < circle_duration:
                angle = ((time.time() - start_time) / circle_duration) * 2 * math.pi
                x = x_pixel + math.cos(angle) * circle_radius
                y = y_pixel + math.sin(angle) * circle_radius
                pyautogui.moveTo(x, y, duration=0.1)

            pyautogui.click(x_pixel, y_pixel)
        except Exception as e:
            print("[OperatingSystem][click_at_percentage] error:", e)
