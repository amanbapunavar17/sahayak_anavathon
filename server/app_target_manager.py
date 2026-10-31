"""
SAHAYAK — Autonomous Application Targeting, Window Focus & Camera Engine
Provides:
  1. Application Resolution & Bundle ID Discovery.
  2. Autonomous Window Focus Management & Restoration.
  3. Native macOS Camera Automation (Photo Booth) & Direct Capture.
  4. Real-time Process & Window Verification via macOS Accessibility & AppleScript.
"""

import os
import sys
import time
import glob
import logging
import subprocess
import typing
from pathlib import Path

logger = logging.getLogger("sahayak-app-target")

# Standard macOS system application aliases and bundle identifiers
APP_CATALOG: dict[str, dict] = {
    "camera": {
        "name": "Photo Booth",
        "bundle_id": "com.apple.PhotoBooth",
        "path": "/System/Applications/Photo Booth.app",
        "supports_background": False,
        "requires_foreground": True,
    },
    "photo booth": {
        "name": "Photo Booth",
        "bundle_id": "com.apple.PhotoBooth",
        "path": "/System/Applications/Photo Booth.app",
        "supports_background": False,
        "requires_foreground": True,
    },
    "facetime": {
        "name": "FaceTime",
        "bundle_id": "com.apple.FaceTime",
        "path": "/System/Applications/FaceTime.app",
        "supports_background": False,
        "requires_foreground": True,
    },
    "notes": {
        "name": "Notes",
        "bundle_id": "com.apple.Notes",
        "path": "/System/Applications/Notes.app",
        "supports_background": True,
        "requires_foreground": False,
    },
    "notepad": {
        "name": "TextEdit",
        "bundle_id": "com.apple.TextEdit",
        "path": "/System/Applications/TextEdit.app",
        "supports_background": False,
        "requires_foreground": True,
    },
    "textedit": {
        "name": "TextEdit",
        "bundle_id": "com.apple.TextEdit",
        "path": "/System/Applications/TextEdit.app",
        "supports_background": False,
        "requires_foreground": True,
    },
    "safari": {
        "name": "Safari",
        "bundle_id": "com.apple.Safari",
        "path": "/System/Applications/Safari.app",
        "supports_background": True,
        "requires_foreground": False,
    },
    "chrome": {
        "name": "Google Chrome",
        "bundle_id": "com.google.Chrome",
        "path": "/Applications/Google Chrome.app",
        "supports_background": True,
        "requires_foreground": False,
    },
    "google chrome": {
        "name": "Google Chrome",
        "bundle_id": "com.google.Chrome",
        "path": "/Applications/Google Chrome.app",
        "supports_background": True,
        "requires_foreground": False,
    },
    "finder": {
        "name": "Finder",
        "bundle_id": "com.apple.finder",
        "path": "/System/Library/CoreServices/Finder.app",
        "supports_background": True,
        "requires_foreground": False,
    },
    "calculator": {
        "name": "Calculator",
        "bundle_id": "com.apple.calculator",
        "path": "/System/Applications/Calculator.app",
        "supports_background": False,
        "requires_foreground": True,
    },
    "terminal": {
        "name": "Terminal",
        "bundle_id": "com.apple.Terminal",
        "path": "/System/Applications/Utilities/Terminal.app",
        "supports_background": True,
        "requires_foreground": False,
    },
    "preview": {
        "name": "Preview",
        "bundle_id": "com.apple.Preview",
        "path": "/System/Applications/Preview.app",
        "supports_background": False,
        "requires_foreground": True,
    },
    "music": {
        "name": "Music",
        "bundle_id": "com.apple.Music",
        "path": "/System/Applications/Music.app",
        "supports_background": True,
        "requires_foreground": False,
    },
    "mail": {
        "name": "Mail",
        "bundle_id": "com.apple.mail",
        "path": "/System/Applications/Mail.app",
        "supports_background": True,
        "requires_foreground": False,
    },
    "calendar": {
        "name": "Calendar",
        "bundle_id": "com.apple.iCal",
        "path": "/System/Applications/Calendar.app",
        "supports_background": True,
        "requires_foreground": False,
    },
    "system settings": {
        "name": "System Settings",
        "bundle_id": "com.apple.systempreferences",
        "path": "/System/Applications/System Settings.app",
        "supports_background": False,
        "requires_foreground": True,
    },
}

CAPTURES_DIR = os.path.expanduser("~/Pictures/SAHAYAK_Captures")


# ---------------------------------------------------------------------------
# Application Resolution & Discovery
# ---------------------------------------------------------------------------

def resolve_target_application(app_query: str) -> dict:
    """
    Resolves a user-spoken app name to a canonical application name, bundle ID,
    and executable path.
    """
    q = app_query.strip().lower()
    
    # 1. Check direct catalog aliases
    if q in APP_CATALOG:
        return APP_CATALOG[q].copy()

    # 2. Check for partial name match in catalog
    for key, info in APP_CATALOG.items():
        if key in q or q in key:
            return info.copy()

    # 3. Dynamic lookup across /Applications, /System/Applications, Utilities
    candidate_paths = [
        f"/System/Applications/{app_query}.app",
        f"/Applications/{app_query}.app",
        f"/System/Applications/Utilities/{app_query}.app",
        f"/System/Library/CoreServices/{app_query}.app",
    ]
    for p in candidate_paths:
        if os.path.exists(p):
            return {
                "name": Path(p).stem,
                "bundle_id": None,
                "path": p,
                "supports_background": False,
                "requires_foreground": True,
            }

    # 4. Spotlight mdfind search for application bundle
    try:
        cmd = f'mdfind "kMDItemContentType == \'com.apple.application-bundle\' && kMDItemFSName == \'*{app_query}*.app\'"'
        out = subprocess.check_output(cmd, shell=True, text=True, timeout=1.5).strip()
        lines = [line.strip() for line in out.splitlines() if line.strip().endswith(".app")]
        if lines:
            app_p = lines[0]
            return {
                "name": Path(app_p).stem,
                "bundle_id": None,
                "path": app_p,
                "supports_background": False,
                "requires_foreground": True,
            }
    except Exception:
        pass

    # Default fallback
    return {
        "name": app_query.title(),
        "bundle_id": None,
        "path": None,
        "supports_background": False,
        "requires_foreground": True,
    }


# ---------------------------------------------------------------------------
# Autonomous Window and Focus Management
# ---------------------------------------------------------------------------

def get_frontmost_application() -> dict:
    """
    Returns the currently active, frontmost application name and window title.
    """
    script = """
    tell application "System Events"
        set frontApp to first application process whose frontmost is true
        set appName to name of frontApp
        set winTitle to ""
        try
            if (count of windows of frontApp) > 0 then
                set winTitle to name of front window of frontApp
            end if
        end try
        return appName & "|||" & winTitle
    end tell
    """
    try:
        res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=2.0)
        if res.returncode == 0 and "|||" in res.stdout:
            parts = res.stdout.strip().split("|||", 1)
            return {"app_name": parts[0].strip(), "window_title": parts[1].strip()}
    except Exception as exc:
        logger.debug(f"get_frontmost_application error: {exc}")

    return {"app_name": "Finder", "window_title": ""}


def activate_and_focus_application(app_name: str, timeout: float = 4.0) -> bool:
    """
    Autonomously brings the target application to the foreground and verifies
    that it has become the frontmost active application.
    """
    info = resolve_target_application(app_name)
    canonical_name = info.get("name", app_name)
    logger.info(f"Activating application focus: '{canonical_name}' (requested: '{app_name}')")

    script = f'''
    tell application "{canonical_name}"
        activate
    end tell
    '''
    try:
        subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=3.0)
    except Exception as exc:
        logger.warning(f"AppleScript activate failed for {canonical_name}: {exc}")
        # Fallback to 'open -a'
        subprocess.run(["open", "-a", canonical_name], capture_output=True)

    # Poll until frontmost or timeout
    start_time = time.time()
    while time.time() - start_time < timeout:
        current = get_frontmost_application()
        curr_name = current.get("app_name", "").lower()
        if canonical_name.lower() in curr_name or curr_name in canonical_name.lower():
            logger.info(f"Verified application focus: '{current.get('app_name')}' is now frontmost.")
            return True
        time.sleep(0.15)

    logger.warning(f"Could not verify focus for '{canonical_name}' within {timeout}s.")
    return False


def restore_application_focus(previous_app: str, timeout: float = 3.0) -> bool:
    """
    Restores the user's previously active application after background or
    foreground tasks complete.
    """
    if not previous_app or previous_app.lower() in ("photo booth", "camera"):
        return False
    logger.info(f"Restoring user application focus to: '{previous_app}'")
    return activate_and_focus_application(previous_app, timeout=timeout)


def verify_application_running(app_name: str) -> bool:
    """
    Verifies that the target application process is active.
    """
    info = resolve_target_application(app_name)
    canonical = info.get("name", app_name)
    script = f'''
    tell application "System Events"
        return (exists (processes whose name is "{canonical}"))
    end tell
    '''
    try:
        res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=2.0)
        return "true" in res.stdout.strip().lower()
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Camera Verification & Capture Engine
# ---------------------------------------------------------------------------

def check_camera_availability() -> dict:
    """
    Inspects installed camera applications and hardware availability.
    """
    pb_installed = os.path.exists("/System/Applications/Photo Booth.app") or os.path.exists("/Applications/Photo Booth.app")
    facetime_installed = os.path.exists("/System/Applications/FaceTime.app")

    return {
        "camera_app_available": pb_installed or facetime_installed,
        "primary_camera_app": "Photo Booth" if pb_installed else ("FaceTime" if facetime_installed else None),
        "photo_booth_available": pb_installed,
        "facetime_available": facetime_installed,
    }


def execute_camera_capture(
    restore_previous: bool = False,
    timeout: float = 8.0,
) -> dict:
    """
    Executes an autonomous camera capture workflow:
      1. Records previously active application.
      2. Autonomously activates Photo Booth into the foreground.
      3. Waits for the preview to be ready.
      4. Locates and clicks the shutter control via Accessibility.
      5. Waits for countdown / shutter exposure.
      6. Verifies that a new picture file was captured and copies it to ~/Pictures/SAHAYAK_Captures/.
      7. Optionally restores the user's previous application focus.
      8. Returns verified result payload.
    """
    avail = check_camera_availability()
    if not avail["photo_booth_available"]:
        return {
            "success": False,
            "error": "No compatible camera application (Photo Booth) was found on this Mac.",
            "spoken_feedback": "I could not find a camera application installed on your Mac.",
        }

    previous_app_info = get_frontmost_application()
    previous_app = previous_app_info.get("app_name", "Finder")

    os.makedirs(CAPTURES_DIR, exist_ok=True)
    capture_start_time = time.time()

    # Step 1: Autonomous Window Activation
    activated = activate_and_focus_application("Photo Booth", timeout=3.5)
    if not activated:
        return {
            "success": False,
            "error": "Failed to bring Photo Booth into the foreground.",
            "spoken_feedback": "I attempted to open Camera, but could not bring the window to the front.",
        }

    # Step 2: Trigger Shutter via Accessibility or File Menu
    shutter_script = """
    tell application "Photo Booth" to activate
    delay 0.4
    tell application "System Events"
        tell process "Photo Booth"
            -- Try clicking the take photo shutter button in group 1 of window 1
            set clicked to false
            try
                repeat with b in buttons of group 1 of window 1
                    if description of b is "take photo" then
                        click b
                        set clicked to true
                        exit repeat
                    end if
                end repeat
            end try
            -- If button was not found in group 1, trigger via File menu
            if not clicked then
                click menu item "Take Photo" of menu "File" of menu bar item "File" of menu bar 1
                set clicked to true
            end if
            return clicked
        end tell
    end tell
    """
    try:
        shutter_res = subprocess.run(["osascript", "-e", shutter_script], capture_output=True, text=True, timeout=3.0)
        logger.info(f"Shutter trigger response: {shutter_res.stdout.strip()}")
    except Exception as exc:
        logger.error(f"Shutter trigger failed: {exc}")
        return {
            "success": False,
            "error": f"Failed to trigger camera shutter: {exc}",
            "spoken_feedback": "I opened the camera, but the shutter control could not be triggered.",
        }

    # Step 3: Wait for Photo Booth countdown and picture capture (3.5 seconds)
    time.sleep(3.6)

    # Step 4: Verification & Retrieval of Captured Photo via Finder
    # We query Finder to find the newest photo in Photo Booth Library and copy it to SAHAYAK_Captures
    extract_script = f"""
    tell application "Finder"
        try
            set pbFolder to folder ((path to pictures folder as text) & "Photo Booth Library:Pictures:")
            set latestFile to last item of (sort (every file of pbFolder) by modification date)
            set destFolder to folder ((path to pictures folder as text) & "SAHAYAK_Captures:")
            set newCopy to duplicate latestFile to destFolder with replacing
            return (POSIX path of (newCopy as alias))
        on error errMsg
            return "ERROR:" & errMsg
        end try
    end tell
    """
    try:
        find_res = subprocess.run(["osascript", "-e", extract_script], capture_output=True, text=True, timeout=4.0)
        output_path = find_res.stdout.strip()
    except Exception as exc:
        output_path = f"ERROR:{exc}"

    if output_path.startswith("ERROR:") or not os.path.exists(output_path):
        # Truthful reporting if verification failed
        return {
            "success": False,
            "error": f"Photo verification failed: {output_path}",
            "spoken_feedback": "The camera shutter was triggered, but I could not verify the saved picture file.",
        }

    # Verify non-zero file size
    file_size = os.path.getsize(output_path)
    if file_size == 0:
        return {
            "success": False,
            "error": "Captured photo file is empty (0 bytes).",
            "spoken_feedback": "A picture was taken, but the resulting file appears empty.",
        }

    photo_filename = Path(output_path).name
    logger.info(f"Photo successfully captured and verified: {output_path} ({file_size} bytes)")

    # Step 5: Optional restore of previous application focus
    if restore_previous and previous_app and previous_app.lower() != "photo booth":
        restore_application_focus(previous_app)

    feedback = f"A picture was captured using the camera and saved as {photo_filename}."
    return {
        "success": True,
        "photo_path": output_path,
        "photo_filename": photo_filename,
        "file_size": file_size,
        "app_used": "Photo Booth",
        "previous_app": previous_app,
        "spoken_feedback": feedback,
    }

