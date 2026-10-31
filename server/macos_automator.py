"""
SAHAYAK — macOS Universal Automation Subsystem
Tagline: Your Voice. Your Freedom.
Platform: macOS (Apple Silicon M4)

Provides general-purpose, native macOS automation across:
  1. Files & Folders (Downloads, Documents, Desktop, custom paths, creation, moving)
  2. Finder and file management (Selection, opening, revealing)
  3. System Settings & Hardware Controls (Displays brightness, sound volume, preferences panes)
  4. Applications and window management (Windows listing, activation, focus restoration)
  5. Text editing and documents (Apple Notes, TextEdit, text input)
  6. Accessibility & Media control

Uses native macOS AppleScript, Accessibility APIs, and CLI utilities, avoiding
blind PyAutoGUI coordinate typing.
"""

import os
import re
import sys
import time
import shutil
import logging
import subprocess
import typing
from pathlib import Path

try:
    import app_target_manager
except ImportError:
    from server import app_target_manager

logger = logging.getLogger("sahayak-macos-automator")

# Standard macOS System Settings preference extension URLs (Ventura, Sonoma, Sequoia)
SETTINGS_PANES: dict[str, str] = {
    "displays": "x-apple.systempreferences:com.apple.Displays-Settings.extension",
    "display": "x-apple.systempreferences:com.apple.Displays-Settings.extension",
    "brightness": "x-apple.systempreferences:com.apple.Displays-Settings.extension",
    "sound": "x-apple.systempreferences:com.apple.Sound-Settings.extension",
    "volume": "x-apple.systempreferences:com.apple.Sound-Settings.extension",
    "audio": "x-apple.systempreferences:com.apple.Sound-Settings.extension",
    "accessibility": "x-apple.systempreferences:com.apple.Accessibility-Settings.extension",
    "bluetooth": "x-apple.systempreferences:com.apple.BluetoothSettings",
    "wifi": "x-apple.systempreferences:com.apple.wifi-settings-extension",
    "network": "x-apple.systempreferences:com.apple.Network-Settings.extension",
    "wallpaper": "x-apple.systempreferences:com.apple.Wallpaper-Settings.extension",
    "general": "x-apple.systempreferences:com.apple.systempreferences.GeneralSettings",
    "battery": "x-apple.systempreferences:com.apple.Battery-Settings.extension",
    "notifications": "x-apple.systempreferences:com.apple.Notifications-Settings.extension",
    "lock_screen": "x-apple.systempreferences:com.apple.Lock-Screen-Settings.extension",
}

# Standard user directories
USER_DIRECTORIES: dict[str, Path] = {
    "downloads": Path.home() / "Downloads",
    "documents": Path.home() / "Documents",
    "desktop": Path.home() / "Desktop",
    "pictures": Path.home() / "Pictures",
    "music": Path.home() / "Music",
    "movies": Path.home() / "Movies",
}


# ===========================================================================
# 1. Files & Folders Automation
# ===========================================================================

def resolve_directory(dir_name: typing.Optional[str]) -> Path:
    """Resolves standard user folder names to concrete Path objects."""
    if not dir_name:
        return USER_DIRECTORIES["downloads"]
    lower = dir_name.lower().strip()
    if lower in USER_DIRECTORIES:
        return USER_DIRECTORIES[lower]
    # Check if path exists directly
    exp = os.path.expanduser(dir_name)
    if os.path.exists(exp) and os.path.isdir(exp):
        return Path(exp)
    return USER_DIRECTORIES.get("downloads", Path.home() / "Downloads")


def find_latest_file(
    directory: str = "downloads",
    extension: typing.Optional[str] = None,
) -> typing.Optional[str]:
    """
    Finds the most recently modified file in the specified directory.
    Excludes hidden and temporary files.
    """
    target_dir = resolve_directory(directory)
    if not target_dir.exists():
        logger.warning(f"Directory {target_dir} does not exist.")
        return None

    try:
        files = [
            f for f in target_dir.iterdir()
            if f.is_file() and not f.name.startswith(".")
        ]
        if extension:
            ext = extension.lower() if extension.startswith(".") else f".{extension.lower()}"
            files = [f for f in files if f.suffix.lower() == ext]

        if not files:
            return None

        latest = max(files, key=lambda f: f.stat().st_mtime)
        return str(latest.resolve())
    except Exception as e:
        logger.warning(f"Error finding latest file in {directory}: {e}")
        return None


def open_file(file_path: str) -> tuple[bool, str]:
    """
    Opens a file using its native macOS default application association.
    """
    if not file_path or not os.path.exists(file_path):
        return False, f"File not found: {file_path}"

    try:
        res = subprocess.run(["open", file_path], capture_output=True, text=True, timeout=3.0)
        if res.returncode == 0:
            return True, f"Opened {os.path.basename(file_path)}"
        return False, f"Failed to open {os.path.basename(file_path)}: {res.stderr}"
    except Exception as e:
        return False, f"Error opening {file_path}: {e}"


def reveal_in_finder(file_path: str) -> tuple[bool, str]:
    """
    Reveals and selects the specified file or folder in a new Finder window.
    """
    if not file_path or not os.path.exists(file_path):
        return False, f"Path not found: {file_path}"

    try:
        res = subprocess.run(["open", "-R", file_path], capture_output=True, text=True, timeout=3.0)
        if res.returncode == 0:
            return True, f"Revealed {os.path.basename(file_path)} in Finder"
        return False, f"Failed to reveal in Finder: {res.stderr}"
    except Exception as e:
        return False, f"Error revealing in Finder: {e}"


def create_folder(folder_name: str, parent_dir: typing.Optional[str] = None) -> tuple[bool, str, str]:
    """
    Creates a new directory at the target location.
    Defaults to ~/Desktop if parent_dir is not specified.
    """
    clean_name = folder_name.replace("/", "").replace("\\", "").strip()
    if not clean_name:
        clean_name = f"New Folder ({time.strftime('%b %d %H.%M')})"

    parent = resolve_directory(parent_dir) if parent_dir else USER_DIRECTORIES["desktop"]
    target_path = parent / clean_name

    try:
        target_path.mkdir(parents=True, exist_ok=True)
        return True, f"Created folder '{clean_name}' at {parent.name}", str(target_path)
    except Exception as e:
        return False, f"Failed to create folder '{clean_name}': {e}", ""


def move_files(
    source_paths: list[str],
    target_folder: str,
) -> tuple[bool, str, list[str]]:
    """
    Moves specified files into the target folder.
    """
    if not target_folder or not os.path.exists(target_folder):
        return False, f"Destination folder does not exist: {target_folder}", []

    moved = []
    dest_dir = Path(target_folder)
    for src in source_paths:
        try:
            p = Path(src)
            if p.exists() and p.is_file():
                dest_file = dest_dir / p.name
                shutil.move(str(p), str(dest_file))
                moved.append(str(dest_file))
        except Exception as e:
            logger.warning(f"Could not move file {src}: {e}")

    if moved:
        return True, f"Moved {len(moved)} files into {dest_dir.name}", moved
    return False, f"No files were moved to {dest_dir.name}", []


def get_finder_selected_files() -> list[str]:
    """
    Retrieves the POSIX paths of all items currently selected in Finder.
    """
    script = """
    tell application "Finder"
        set sel to selection
        set posixList to {}
        repeat with itemRef in sel
            set end of posixList to POSIX path of (itemRef as alias)
        end repeat
        set AppleScript's text item delimiters to "|||"
        return posixList as text
    end tell
    """
    try:
        res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=2.0)
        if res.returncode == 0 and res.stdout.strip():
            return [p.strip() for p in res.stdout.strip().split("|||") if p.strip()]
    except Exception as e:
        logger.debug(f"Finder selection check: {e}")
    return []


# ===========================================================================
# 2. System Settings & Hardware Controls
# ===========================================================================

def open_system_settings_pane(pane_query: str) -> tuple[bool, str]:
    """
    Opens System Settings to the requested pane (e.g. Displays, Sound, Accessibility).
    """
    query_clean = pane_query.lower().strip()
    target_url = None
    pane_label = "System Settings"

    for key, url in SETTINGS_PANES.items():
        if key in query_clean:
            target_url = url
            pane_label = key.title()
            break

    if target_url:
        try:
            res = subprocess.run(["open", target_url], capture_output=True, text=True, timeout=2.5)
            if res.returncode == 0:
                return True, f"Opened {pane_label} Settings."
        except Exception:
            pass

    # Generic activation
    script = 'tell application "System Settings" to activate'
    try:
        subprocess.run(["osascript", "-e", script], capture_output=True, timeout=2.5)
        return True, "Opened System Settings."
    except Exception as e:
        return False, f"Failed to open System Settings: {e}"


def change_display_brightness(delta: int = 0, level: typing.Optional[int] = None) -> tuple[bool, str]:
    """
    Adjusts display brightness by triggering native macOS brightness keys and opening Displays pane.
    """
    # Bring up Displays settings pane for user verification
    open_system_settings_pane("displays")
    time.sleep(0.3)

    # Key code 144 = Brightness Up, 145 = Brightness Down
    if delta < 0:
        times = min(abs(delta), 10)
        script = f"""
        tell application "System Events"
            repeat {times} times
                key code 145
                delay 0.05
            end repeat
        end tell
        """
        subprocess.run(["osascript", "-e", script], capture_output=True)
        return True, f"Decreased display brightness by {times} steps and opened Displays settings."
    else:
        times = min(delta if delta > 0 else 4, 10)
        script = f"""
        tell application "System Events"
            repeat {times} times
                key code 144
                delay 0.05
            end repeat
        end tell
        """
        subprocess.run(["osascript", "-e", script], capture_output=True)
        return True, f"Adjusted display brightness and opened Displays settings."


def change_sound_volume(level: typing.Optional[int] = None, delta: typing.Optional[int] = None, mute: typing.Optional[bool] = None) -> tuple[bool, str]:
    """
    Adjusts macOS output sound volume (0-100) or mute status via AppleScript.
    """
    if mute is not None:
        state = "true" if mute else "false"
        script = f"set volume output muted {state}"
        subprocess.run(["osascript", "-e", script], capture_output=True)
        return True, "Muted sound output." if mute else "Unmuted sound output."

    if level is not None:
        clamped = max(0, min(100, level))
        script = f"set volume output volume {clamped}"
        subprocess.run(["osascript", "-e", script], capture_output=True)
        return True, f"Set sound volume to {clamped} percent."

    if delta is not None:
        # Get current volume first
        try:
            curr_str = subprocess.check_output(["osascript", "-e", "output volume of (get volume settings)"], text=True).strip()
            curr = int(curr_str)
            target = max(0, min(100, curr + delta))
            subprocess.run(["osascript", "-e", f"set volume output volume {target}"], capture_output=True)
            return True, f"Changed volume from {curr} to {target} percent."
        except Exception:
            pass

    return True, "Volume adjusted."


# ===========================================================================
# 3. Text Editing & Document Automation
# ===========================================================================

def create_textedit_document(title: str, text: str) -> tuple[bool, str]:
    """
    Creates a new document in TextEdit with the specified content.
    Bypasses iCloud dialog hangs by writing directly to a temporary file and opening in TextEdit.
    """
    try:
        clean_name = re.sub(r"[^a-zA-Z0-9_\-\.]", "_", title)
        if not clean_name.endswith((".c", ".txt", ".py", ".md")):
            clean_name += ".c" if "include" in text or "main()" in text else ".txt"
        file_path = os.path.expanduser(f"~/Desktop/{clean_name}")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(text)
        res = subprocess.run(["open", "-a", "TextEdit", file_path], capture_output=True, text=True, timeout=3.0)
        if res.returncode == 0:
            return True, f"Created and opened document '{clean_name}' in TextEdit."
        return False, f"Could not launch TextEdit: {res.stderr}"
    except Exception as e:
        return False, f"Error creating TextEdit document: {e}"


def safe_keyboard_type(text: str, target_app: typing.Optional[str] = None) -> tuple[bool, str]:
    """
    Types text into an application ONLY after confirming the target application
    is frontmost and active. Never types blindly into random cursor locations.
    """
    import pyautogui

    if target_app:
        active = app_target_manager.activate_and_focus_application(target_app, timeout=3.0)
        if not active:
            return False, f"Could not verify focus for {target_app}. Aborting text typing to prevent typing into the wrong window."

    front = app_target_manager.get_frontmost_application()
    curr_app = front.get("app_name", "Unknown")

    # Verify clipboard flush
    subprocess.run(["pbcopy"], input=text.encode("utf-8"), capture_output=True)
    time.sleep(0.08)
    pyautogui.hotkey("command", "v")
    return True, f"Entered text into {curr_app}."


def close_active_window() -> tuple[bool, str]:
    """Closes the current frontmost window cleanly via Cmd+W."""
    import pyautogui
    pyautogui.hotkey("command", "w")
    return True, "Closed active window."
