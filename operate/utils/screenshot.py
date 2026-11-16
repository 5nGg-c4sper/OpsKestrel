import os
import platform
import subprocess
import pyautogui
from PIL import Image, ImageDraw, ImageGrab


def scale_coordinates(x, y, scale):
    scale = float(scale)
    if scale <= 0:
        raise ValueError("scale must be greater than 0")
    return int(round(x * scale)), int(round(y * scale))


def unscale_coordinates(x, y, scale):
    scale = float(scale)
    if scale <= 0:
        raise ValueError("scale must be greater than 0")
    return int(round(x / scale)), int(round(y / scale))


def capture_screen_with_cursor(file_path, scale=1.0):
    scale = float(scale)
    if scale <= 0:
        raise ValueError("scale must be greater than 0")

    user_platform = platform.system()

    if user_platform == "Windows":
        screenshot = pyautogui.screenshot()
    elif user_platform == "Linux":
        # Use xlib to prevent scrot dependency for Linux
        import Xlib.display
        import Xlib.X
        import Xlib.Xutil

        screen = Xlib.display.Display().screen()
        size = screen.width_in_pixels, screen.height_in_pixels
        screenshot = ImageGrab.grab(bbox=(0, 0, size[0], size[1]))
    elif user_platform == "Darwin":  # (Mac OS)
        # Capture without the system cursor; a red cursor marker is drawn below.
        subprocess.run(["screencapture", "-x", file_path], check=True)
        with Image.open(file_path) as captured:
            screenshot = captured.copy()
    else:
        raise RuntimeError(
            f"The platform you're using ({user_platform}) is not currently supported"
        )

    target_size = (
        max(1, int(round(screenshot.width * scale))),
        max(1, int(round(screenshot.height * scale))),
    )
    if target_size != screenshot.size:
        screenshot = screenshot.resize(target_size, Image.Resampling.LANCZOS)

    try:
        screen_width, screen_height = pyautogui.size()
        cursor_x, cursor_y = pyautogui.position()
        image_x = round(cursor_x * screenshot.width / screen_width)
        image_y = round(cursor_y * screenshot.height / screen_height)

        if 0 <= image_x < screenshot.width and 0 <= image_y < screenshot.height:
            radius = 6
            draw = ImageDraw.Draw(screenshot)
            draw.ellipse(
                (
                    image_x - radius,
                    image_y - radius,
                    image_x + radius,
                    image_y + radius,
                ),
                fill=(255, 0, 0),
            )
    except Exception as e:
        print("[capture_screen_with_cursor] cursor marker error:", e)

    screenshot.save(file_path)


def compress_screenshot(raw_screenshot_filename, screenshot_filename):
    with Image.open(raw_screenshot_filename) as img:
        # Check if the image has an alpha channel (transparency)
        if img.mode in ('RGBA', 'LA') or (img.mode == 'P' and 'transparency' in img.info):
            # Create a white background image
            background = Image.new('RGB', img.size, (255, 255, 255))
            # Paste the image onto the background, using the alpha channel as mask
            background.paste(img, mask=img.split()[3])  # 3 is the alpha channel
            # Save the result as JPEG
            background.save(screenshot_filename, 'JPEG', quality=85)  # Adjust quality as needed
        else:
            # If no alpha channel, simply convert and save
            img.convert('RGB').save(screenshot_filename, 'JPEG', quality=85)
