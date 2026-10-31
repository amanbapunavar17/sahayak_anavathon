"""
SAHAYAK — Safe Computer Action Execution Engine
Executes verified macOS OS-level primitives:
  - Coordinate clicks (normalized [0, 1000] mapping to logical screen)
  - macOS Spotlight application launches
  - macOS Spotlight local system / file search (system_search)
  - Browser web search (browser_search)
  - Website-specific search with verification (website_search)
  - Direct website navigation (open_website)
  - In-field text typing (clipboard verification before Cmd+V)
  - Keyboard shortcuts / hotkeys
  - Scrolling
  - Sensitive action interception & guarded execution
"""

import logging
import os
import subprocess
import sys
import time
import typing
import pyautogui

from browser_engine import browser_engine, BrowserTaskResult
import app_target_manager
import macos_automator
from mouse_controller import mouse_controller

logger = logging.getLogger("sahayak-executor")

# Configure PyAutoGUI safety defaults
pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.05


def _poll_until(condition: typing.Callable[[], bool], timeout: float, interval: float = 0.05) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if condition():
                return True
        except Exception:
            pass
        time.sleep(interval)
    return False


def _get_clipboard_text() -> str:
    try:
        r = subprocess.run(["pbpaste"], capture_output=True, text=True, timeout=2)
        return r.stdout
    except Exception:
        return ""


def execute_click(x: int, y: int) -> dict:
    """
    Click at normalized coordinates [0, 1000] mapped to logical screen points.
    Glides mouse cursor arrow smoothly across screen before clicking.
    """
    nx = max(0.0, min(1000.0, float(x)))
    ny = max(0.0, min(1000.0, float(y)))

    screen_w, screen_h = pyautogui.size()
    px = int(round((nx / 1000.0) * (screen_w - 1)))
    py = int(round((ny / 1000.0) * (screen_h - 1)))

    logger.info(f"CLICK: norm=({x},{y}) -> pixel=({px},{py}) [display {screen_w}x{screen_h}]")
    res = mouse_controller.click_at(px, py, click_type="single", duration=0.3)
    return {
        "status": "success",
        "command": "click",
        "x": px,
        "y": py,
        "spoken_feedback": f"Clicked at coordinate {px}, {py}."
    }


def execute_click_element(
    target_element: typing.Optional[str] = None,
    click_type: str = "single",
    button: str = "left",
    x: typing.Optional[int] = None,
    y: typing.Optional[int] = None,
    ocr_blocks: typing.Optional[list[dict]] = None,
) -> dict:
    """
    Smoothly glides mouse cursor arrow to target button or coordinate and performs click.
    """
    logger.info(f"EXECUTE CLICK ELEMENT: target='{target_element}', type='{click_type}', btn='{button}', coords=({x},{y})")
    return mouse_controller.click_element(
        target_element=target_element,
        click_type=click_type,
        button=button,
        x=x,
        y=y,
        ocr_blocks=ocr_blocks,
    )


def execute_mouse_move(
    target: typing.Optional[str] = None,
    x: typing.Optional[int] = None,
    y: typing.Optional[int] = None,
) -> dict:
    """
    Smoothly glides mouse cursor arrow across screen to target landmark, button, or coordinates.
    """
    logger.info(f"EXECUTE MOUSE MOVE: target='{target}', coords=({x},{y})")
    return mouse_controller.move_mouse(target=target, x=x, y=y)


def execute_double_click(
    x: typing.Optional[int] = None,
    y: typing.Optional[int] = None,
    target_element: typing.Optional[str] = None,
    ocr_blocks: typing.Optional[list[dict]] = None,
) -> dict:
    """
    Double clicks target element or screen coordinate.
    """
    return execute_click_element(
        target_element=target_element,
        click_type="double",
        button="left",
        x=x,
        y=y,
        ocr_blocks=ocr_blocks,
    )


def execute_right_click(
    x: typing.Optional[int] = None,
    y: typing.Optional[int] = None,
    target_element: typing.Optional[str] = None,
    ocr_blocks: typing.Optional[list[dict]] = None,
) -> dict:
    """
    Right clicks target element or screen coordinate.
    """
    return execute_click_element(
        target_element=target_element,
        click_type="right",
        button="right",
        x=x,
        y=y,
        ocr_blocks=ocr_blocks,
    )


def execute_scroll(amount: int) -> dict:
    """Scroll vertically by the specified amount."""
    logger.info(f"SCROLL: amount={amount}")
    pyautogui.scroll(amount)
    return {"status": "success", "command": "scroll", "amount": amount}


def execute_system_search(query: str) -> dict:
    """
    Search specifically for local files, documents, or content on macOS via Spotlight.
    Does NOT use a browser.
    """
    logger.info(f"SYSTEM SEARCH (Spotlight): '{query}'")
    # Open Spotlight
    pyautogui.keyDown("command")
    time.sleep(0.02)
    pyautogui.press("space")
    time.sleep(0.02)
    pyautogui.keyUp("command")

    time.sleep(0.2)
    # Clear existing
    pyautogui.hotkey("command", "a")
    pyautogui.press("backspace")
    time.sleep(0.05)

    # Type file search query
    pyautogui.write(query, interval=0.03)
    time.sleep(0.4)

    feedback = f"Searching your Mac for '{query}' using Spotlight."
    return {
        "status": "success",
        "command": "system_search",
        "query": query,
        "spoken_feedback": feedback,
    }


def execute_type_spotlight(text: str) -> dict:
    """
    Open Spotlight search, clear any existing text, type app name, and launch.
    """
    logger.info(f"SPOTLIGHT APP LAUNCH: '{text}'")
    pyautogui.keyDown("command")
    time.sleep(0.02)
    pyautogui.press("space")
    time.sleep(0.02)
    pyautogui.keyUp("command")

    time.sleep(0.2)
    pyautogui.hotkey("command", "a")
    pyautogui.press("backspace")
    time.sleep(0.05)

    pyautogui.write(text, interval=0.04)
    time.sleep(0.4)
    pyautogui.press("enter")
    time.sleep(0.1)
    pyautogui.press("enter")
    return {"status": "success", "command": "type_text", "text": text}


def execute_open_application(app_name: str) -> dict:
    """
    Autonomously resolves, launches, activates and verifies a macOS application.
    Never blindly types the app name into active cursor fields.
    """
    logger.info(f"OPEN APPLICATION: '{app_name}'")
    lower = app_name.lower().strip()
    if lower in ["browser", "default browser", "web browser"]:
        return execute_open_url("https://google.com")

    info = app_target_manager.resolve_target_application(app_name)
    target_name = info.get("name", app_name)

    # Autonomously activate and bring to front
    success = app_target_manager.activate_and_focus_application(target_name, timeout=3.5)
    if success:
        return {
            "status": "success",
            "command": "open_application",
            "app_name": target_name,
            "bundle_id": info.get("bundle_id"),
            "spoken_feedback": f"Opening {target_name}.",
        }

    # Attempt fallback open -a
    try:
        r = subprocess.run(["open", "-a", target_name], capture_output=True, timeout=2.5)
        if r.returncode == 0:
            return {
                "status": "success",
                "command": "open_application",
                "app_name": target_name,
                "bundle_id": info.get("bundle_id"),
                "spoken_feedback": f"Opening {target_name}.",
            }
    except Exception:
        pass

    # Truthful failure reporting — DO NOT type into random fields!
    return {
        "status": "failed",
        "command": "open_application",
        "app_name": target_name,
        "spoken_feedback": f"Could not open application {target_name} on your Mac.",
    }


def execute_take_photo(restore_previous: bool = False) -> dict:
    """
    Autonomous camera capture via Photo Booth with verification.
    """
    logger.info("EXECUTING CAMERA CAPTURE WORKFLOW")
    res = app_target_manager.execute_camera_capture(restore_previous=restore_previous)
    return {
        "status": "success" if res.get("success") else "failed",
        "command": "take_photo",
        "photo_path": res.get("photo_path"),
        "photo_filename": res.get("photo_filename"),
        "file_size": res.get("file_size"),
        "app_used": res.get("app_used", "Photo Booth"),
        "spoken_feedback": res.get("spoken_feedback", "Picture captured."),
        "error": res.get("error"),
    }


def execute_website_search(target_website: str, query: str) -> dict:
    """
    Navigates to the specified website, executes the search query,
    and verifies that search results are displayed.
    """
    result: BrowserTaskResult = browser_engine.execute_website_search(target_website, query)
    return {
        "status": "success" if result.success else "warning",
        "command": "website_search",
        "target_website": result.target_website,
        "query": query,
        "url": result.target_url,
        "verified": result.success,
        "stage_reached": result.stage_reached,
        "spoken_feedback": result.spoken_feedback,
        "evidence": result.evidence,
        "error_detail": result.error_detail,
    }


def execute_browser_search(query: str) -> dict:
    """
    Searches the internet via the web browser and verifies results.
    """
    result: BrowserTaskResult = browser_engine.execute_browser_search(query)
    return {
        "status": "success" if result.success else "warning",
        "command": "browser_search",
        "query": query,
        "url": result.target_url,
        "verified": result.success,
        "spoken_feedback": result.spoken_feedback,
        "evidence": result.evidence,
    }


def execute_open_website(target: str) -> dict:
    """
    Navigates directly to a website.
    """
    result: BrowserTaskResult = browser_engine.execute_open_website(target)
    return {
        "status": "success" if result.success else "warning",
        "command": "open_website",
        "url": result.target_url,
        "verified": result.success,
        "spoken_feedback": result.spoken_feedback,
    }


def execute_open_file(file_path: str, reveal: bool = False) -> dict:
    """
    Opens a file using its default macOS application, or reveals it in Finder.
    """
    logger.info(f"OPEN FILE: '{file_path}' (reveal={reveal})")
    if reveal:
        success, msg = macos_automator.reveal_in_finder(file_path)
    else:
        success, msg = macos_automator.open_file(file_path)
    return {
        "status": "success" if success else "failed",
        "command": "open_file",
        "file_path": file_path,
        "spoken_feedback": msg,
    }


def execute_find_latest_file(directory: str = "downloads", extension: typing.Optional[str] = None) -> dict:
    """
    Finds the most recently modified non-hidden file in the target directory.
    """
    logger.info(f"FIND LATEST FILE: dir='{directory}', ext={extension}")
    path = macos_automator.find_latest_file(directory, extension)
    if path:
        return {
            "status": "success",
            "command": "find_latest_file",
            "directory": directory,
            "file_path": path,
            "spoken_feedback": f"Found latest file: {os.path.basename(path)}",
        }
    return {
        "status": "failed",
        "command": "find_latest_file",
        "directory": directory,
        "spoken_feedback": f"Could not find any files in {directory}.",
    }


def execute_create_folder(folder_name: str, parent_dir: typing.Optional[str] = None) -> dict:
    """
    Creates a folder in the specified directory (defaults to Desktop).
    """
    logger.info(f"CREATE FOLDER: name='{folder_name}', parent='{parent_dir}'")
    success, msg, path = macos_automator.create_folder(folder_name, parent_dir)
    return {
        "status": "success" if success else "failed",
        "command": "create_folder",
        "folder_name": folder_name,
        "parent_dir": parent_dir,
        "created_path": path,
        "spoken_feedback": msg,
    }


def execute_move_files(source_paths: list[str], target_folder: str) -> dict:
    """
    Moves specified files into the target folder.
    """
    logger.info(f"MOVE FILES: count={len(source_paths)} -> '{target_folder}'")
    success, msg, moved = macos_automator.move_files(source_paths, target_folder)
    return {
        "status": "success" if success else "failed",
        "command": "move_files",
        "target_folder": target_folder,
        "moved_files": moved,
        "spoken_feedback": msg,
    }


def execute_system_settings(
    pane_query: str = "settings",
    setting_type: typing.Optional[str] = None,
    delta: int = 0,
    level: typing.Optional[int] = None,
    mute: typing.Optional[bool] = None,
) -> dict:
    """
    Adjusts macOS system settings (Displays/Brightness, Sound/Volume, or opens settings pane).
    """
    logger.info(f"SYSTEM SETTINGS: pane='{pane_query}', type='{setting_type}', delta={delta}, level={level}")
    stype = (setting_type or pane_query or "").lower()
    if "bright" in stype or "display" in stype:
        success, msg = macos_automator.change_display_brightness(delta=delta, level=level)
    elif "sound" in stype or "volume" in stype or "audio" in stype or mute is not None:
        success, msg = macos_automator.change_sound_volume(level=level, delta=delta if delta != 0 else None, mute=mute)
    else:
        success, msg = macos_automator.open_system_settings_pane(pane_query)
    return {
        "status": "success" if success else "failed",
        "command": "system_settings",
        "pane_query": pane_query,
        "setting_type": setting_type,
        "spoken_feedback": msg,
    }


def execute_keyboard_type(text: str, target_app: typing.Optional[str] = None) -> dict:
    """
    Type text into application ONLY after confirming the destination application or focus.
    Never blindly types unrequested instructions into random fields.
    """
    logger.info(f"KEYBOARD TYPE: '{text[:40]}...', target_app={target_app}")
    success, msg = macos_automator.safe_keyboard_type(text, target_app=target_app)
    return {
        "status": "success" if success else "failed",
        "command": "keyboard_type",
        "text": text,
        "target_app": target_app,
        "spoken_feedback": msg,
    }


def execute_hotkey(keys: list[str]) -> dict:
    """Press keyboard shortcut (e.g. ['command', 'n'] or ['command', 'w'])."""
    logger.info(f"HOTKEY: {keys}")
    pyautogui.hotkey(*keys)
    return {"status": "success", "command": "press_hotkey", "keys": keys}


def execute_open_url(url: str) -> dict:
    """Open URL in active browser or default browser."""
    return execute_open_website(url)


def execute_sensitive_action(action: dict) -> dict:
    """
    Executes a sensitive operation that has already been explicitly confirmed by user.
    """
    cmd = action.get("command")
    logger.warning(f"EXECUTING CONFIRMED SENSITIVE ACTION: {action}")

    if cmd == "delete_file":
        target = action.get("target") or action.get("path")
        if target and os.path.exists(target):
            script = f'tell application "Finder" to delete POSIX file "{target}"'
            subprocess.run(["osascript", "-e", script], capture_output=True)
            return {"status": "success", "message": f"File {target} moved to Trash."}
        else:
            pyautogui.hotkey("command", "backspace")
            return {"status": "success", "message": "Delete shortcut executed in active application."}

    elif cmd == "submit_form" or cmd == "purchase":
        pyautogui.press("enter")
        return {"status": "success", "message": "Submission confirmed and executed."}

    elif cmd == "send_message":
        pyautogui.hotkey("command", "enter")
        return {"status": "success", "message": "Message sent."}

    elif cmd == "click":
        return execute_click(action.get("x", 500), action.get("y", 500))

    return {"status": "success", "message": "Action executed."}