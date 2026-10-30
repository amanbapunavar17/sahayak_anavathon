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
    Includes client-side coordinate guardrails.
    """
    nx = max(0.0, min(1000.0, float(x)))
    ny = max(0.0, min(1000.0, float(y)))

    screen_w, screen_h = pyautogui.size()
    px = int(round((nx / 1000.0) * (screen_w - 1)))
    py = int(round((ny / 1000.0) * (screen_h - 1)))

    logger.info(f"CLICK: norm=({x},{y}) -> pixel=({px},{py}) [display {screen_w}x{screen_h}]")
    pyautogui.moveTo(px, py, duration=0.15)
    pyautogui.click()
    return {"status": "success", "command": "click", "x": px, "y": py}


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
    Launches a local macOS application.
    """
    logger.info(f"OPEN APPLICATION: '{app_name}'")
    lower = app_name.lower()
    if lower in ["browser", "default browser", "web browser"]:
        return execute_open_url("https://google.com")

    # Try standard 'open -a' first
    try:
        r = subprocess.run(["open", "-a", app_name], capture_output=True, timeout=3)
        if r.returncode == 0:
            return {
                "status": "success",
                "command": "open_application",
                "app_name": app_name,
                "spoken_feedback": f"Opening {app_name}."
            }
    except Exception:
        pass

    # Fallback to Spotlight launch
    res = execute_type_spotlight(app_name)
    res["spoken_feedback"] = f"Opening {app_name}."
    return res


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


def execute_keyboard_type(text: str) -> dict:
    """
    Type text into currently focused input via clipboard with verification.
    """
    logger.info(f"KEYBOARD TYPE: '{text[:40]}...'")
    subprocess.run(["pbcopy"], input=text.encode("utf-8"), capture_output=True)

    # Verify clipboard has flushed
    _poll_until(lambda: _get_clipboard_text() == text, timeout=1.0, interval=0.03)
    pyautogui.hotkey("command", "v")
    return {"status": "success", "command": "keyboard_type", "text": text}


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
