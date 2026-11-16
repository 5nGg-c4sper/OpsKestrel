import pyautogui
import platform
import time
import math
import pyperclip

from operate.utils.misc import convert_percent_to_decimal


class OperatingSystem:
    def write(self, content):
        try:
            content = content.replace("\\n", "\n")

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
            for key in keys:
                pyautogui.keyDown(key)
            time.sleep(0.1)
            for key in keys:
                pyautogui.keyUp(key)
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
