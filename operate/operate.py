import sys
import os
import time
import asyncio
import subprocess
from prompt_toolkit.shortcuts import message_dialog
from prompt_toolkit import prompt
from operate.exceptions import ModelNotRecognizedException
import platform

from dotenv import load_dotenv

# from operate.models.prompts import USER_QUESTION, get_system_prompt
from operate.models.prompts import (
    USER_QUESTION,
    get_system_prompt,
)
from operate.config import Config
from operate.utils.style import (
    ANSI_GREEN,
    ANSI_RESET,
    ANSI_YELLOW,
    ANSI_RED,
    ANSI_BRIGHT_MAGENTA,
    ANSI_BLUE,
    style,
)
from operate.utils.operating_system import OperatingSystem
from operate.models.apis import get_next_action

# Load configuration
config = Config()
operating_system = OperatingSystem()

SCREENSHOT_SCALE = 0.5
ACTION_SETTLE_DELAY = 0.6
MAX_LOOPS = 6
MAX_RUNTIME_SECONDS = 90


def finish_run(message):
    """Show a terminal completion signal and bring Terminal to the front."""
    print(f"\n{ANSI_BLUE}[Self-Operating Computer]{ANSI_RESET} {message}\n")
    sys.stdout.write("\a")
    sys.stdout.flush()

    if platform.system() != "Darwin":
        return

    try:
        subprocess.Popen(
            ["open", "-a", "Terminal"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as e:
        print("[Self-Operating Computer] Could not activate Terminal:", e)

    try:
        notification_script = (
            "on run argv\n"
            'display notification (item 1 of argv) '
            'with title "Self-Operating Computer"\n'
            "end run"
        )
        subprocess.Popen(
            ["osascript", "-e", notification_script, "--", message],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as e:
        print("[Self-Operating Computer] Could not send notification:", e)


def main(model, terminal_prompt, voice_mode=False, verbose_mode=False):
    """
    Main function for the Self-Operating Computer.

    Parameters:
    - model: The model used for generating responses.
    - terminal_prompt: A string representing the prompt provided in the terminal.
    - voice_mode: A boolean indicating whether to enable voice mode.

    Returns:
    None
    """

    load_dotenv()
    model = os.getenv("MODEL", model)

    mic = None
    # Initialize `WhisperMic`, if `voice_mode` is True

    config.verbose = verbose_mode
    config.validation(model, voice_mode)

    if voice_mode:
        try:
            from whisper_mic import WhisperMic

            # Initialize WhisperMic if import is successful
            mic = WhisperMic()
        except ImportError:
            print(
                "Voice mode requires the 'whisper_mic' module. Please install it using 'pip install -r requirements-audio.txt'"
            )
            sys.exit(1)

    # Skip message dialog if prompt was given directly
    if not terminal_prompt:
        message_dialog(
            title="Self-Operating Computer",
            text="An experimental framework to enable multimodal models to operate computers",
            style=style,
        ).run()

    else:
        print("Running direct prompt...")

    # # Clear the console
    if platform.system() == "Windows":
        os.system("cls")
    else:
        print("\033c", end="")

    if terminal_prompt:  # Skip objective prompt if it was given as an argument
        objective = terminal_prompt
    elif voice_mode:
        print(
            f"{ANSI_GREEN}[Self-Operating Computer]{ANSI_RESET} Listening for your command... (speak now)"
        )
        try:
            objective = mic.listen()
        except Exception as e:
            print(f"{ANSI_RED}Error in capturing voice input: {e}{ANSI_RESET}")
            return  # Exit if voice input fails
    else:
        print(
            f"[{ANSI_GREEN}Self-Operating Computer {ANSI_RESET}|{ANSI_BRIGHT_MAGENTA} {model}{ANSI_RESET}]\n{USER_QUESTION}"
        )
        print(f"{ANSI_YELLOW}[User]{ANSI_RESET}")
        objective = prompt(style=style)

    system_prompt = get_system_prompt(model, objective)
    system_message = {"role": "system", "content": system_prompt}
    messages = [system_message]

    loop_count = 0
    start_time = time.monotonic()
    previous_operation_signature = None
    repeated_action_count = 0

    session_id = None

    while True:
        elapsed_seconds = time.monotonic() - start_time
        if elapsed_seconds >= MAX_RUNTIME_SECONDS:
            print(
                f"{ANSI_GREEN}[Self-Operating Computer]{ANSI_RED}"
                f"[Error] Task timed out after {MAX_RUNTIME_SECONDS} seconds."
                f"{ANSI_RESET}"
            )
            finish_run(f"Task timed out after {MAX_RUNTIME_SECONDS} seconds.")
            break

        if config.verbose:
            print(
                "[Self Operating Computer] loop_count",
                loop_count,
                "elapsed_seconds",
                round(elapsed_seconds, 2),
            )
        try:
            operations, session_id = asyncio.run(
                get_next_action(
                    model,
                    messages,
                    objective,
                    session_id,
                    scale=SCREENSHOT_SCALE,
                )
            )

            operation_signature = [
                {
                    key: value
                    for key, value in operation.items()
                    if key != "thought"
                }
                for operation in operations
            ]
            if (
                operation_signature
                and operation_signature == previous_operation_signature
            ):
                repeated_action_count += 1
            else:
                repeated_action_count = 0
            previous_operation_signature = operation_signature

            if repeated_action_count == 1:
                print(
                    f"{ANSI_GREEN}[Self-Operating Computer]{ANSI_YELLOW}"
                    "[Warning] Repeated action skipped; requesting an alternative approach."
                    f"{ANSI_RESET}"
                )
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "Operator feedback: the previous action produced no "
                            "visible screen change. Do not repeat the same action. "
                            "Use a different target, keyboard input, or another "
                            "safe method."
                        ),
                    }
                )
                loop_count += 1
                if loop_count >= MAX_LOOPS:
                    print(
                        f"{ANSI_GREEN}[Self-Operating Computer]{ANSI_RED}"
                        f"[Error] Maximum loop count ({MAX_LOOPS}) reached."
                        f"{ANSI_RESET}"
                    )
                    finish_run(f"Task stopped after {MAX_LOOPS} steps.")
                    break
                continue

            if repeated_action_count >= 2:
                print(
                    f"{ANSI_GREEN}[Self-Operating Computer]{ANSI_RED}"
                    "[Error] Repeated action detected; stopping to avoid an action loop."
                    f"{ANSI_RESET}"
                )
                finish_run(
                    "Task stopped because the same action was repeated."
                )
                break

            stop = operate(operations, model)
            if stop:
                break

            loop_count += 1
            if loop_count >= MAX_LOOPS:
                print(
                    f"{ANSI_GREEN}[Self-Operating Computer]{ANSI_RED}"
                    f"[Error] Maximum loop count ({MAX_LOOPS}) reached."
                    f"{ANSI_RESET}"
                )
                finish_run(f"Task stopped after {MAX_LOOPS} steps.")
                break
        except ModelNotRecognizedException as e:
            print(
                f"{ANSI_GREEN}[Self-Operating Computer]{ANSI_RED}[Error] -> {e} {ANSI_RESET}"
            )
            finish_run("Task stopped because the model was not recognized.")
            break
        except Exception as e:
            print(
                f"{ANSI_GREEN}[Self-Operating Computer]{ANSI_RED}[Error] -> {e} {ANSI_RESET}"
            )
            finish_run("Task stopped because of an error.")
            break


def operate(operations, model):
    if config.verbose:
        print("[Self Operating Computer][operate]")
    for operation in operations:
        if config.verbose:
            print("[Self Operating Computer][operate] operation", operation)
        operate_type = operation.get("operation").lower()
        operate_thought = operation.get("thought")
        operate_detail = ""
        if config.verbose:
            print("[Self Operating Computer][operate] operate_type", operate_type)

        if operate_type == "press" or operate_type == "hotkey":
            keys = operation.get("keys")
            operate_detail = keys
            operating_system.press(keys)
            time.sleep(ACTION_SETTLE_DELAY)
        elif operate_type == "write":
            content = operation.get("content")
            operate_detail = content
            operating_system.write(content)
        elif operate_type == "click":
            x = operation.get("x")
            y = operation.get("y")
            click_detail = {"x": x, "y": y}
            operate_detail = click_detail

            operating_system.mouse(click_detail)
            time.sleep(ACTION_SETTLE_DELAY)
        elif operate_type == "done":
            summary = operation.get("summary")

            print(
                f"[{ANSI_GREEN}Self-Operating Computer {ANSI_RESET}|{ANSI_BRIGHT_MAGENTA} {model}{ANSI_RESET}]"
            )
            print(f"{ANSI_BLUE}Objective Complete: {ANSI_RESET}{summary}\n")
            finish_run("Task completed.")
            return True

        else:
            print(
                f"{ANSI_GREEN}[Self-Operating Computer]{ANSI_RED}[Error] unknown operation response :({ANSI_RESET}"
            )
            print(
                f"{ANSI_GREEN}[Self-Operating Computer]{ANSI_RED}[Error] AI response {ANSI_RESET}{operation}"
            )
            finish_run(
                "Task stopped because the model returned an unknown operation."
            )
            return True

        print(
            f"[{ANSI_GREEN}Self-Operating Computer {ANSI_RESET}|{ANSI_BRIGHT_MAGENTA} {model}{ANSI_RESET}]"
        )
        print(f"{operate_thought}")
        print(f"{ANSI_BLUE}Action: {ANSI_RESET}{operate_type} {operate_detail}\n")

    return False
