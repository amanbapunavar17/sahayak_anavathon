"""
SAHAYAK — Screen Understanding & Perception Engine
Handles:
  1. High-resolution screen capture mapped to logical coordinate points.
  2. Local, zero-latency on-device OCR via Apple Silicon Vision framework.
  3. Active application context (App name, window title, browser URL).
  4. Ruler annotation for visual coordinate reasoning.
"""

import base64
import io
import logging
import os
import subprocess
import sys
import tempfile
import typing
from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger("sahayak-screen")

# Optional macOS AppKit / Quartz / Vision imports
_HAS_VISION = False
_HAS_QUARTZ = False
NSScreen = None

try:
    if sys.platform == "darwin":
        from AppKit import NSScreen
        import Quartz
        _HAS_QUARTZ = True
        import Vision
        import Cocoa
        _HAS_VISION = True
except Exception as exc:
    logger.warning(f"Native macOS frameworks partial import: {exc}")


def get_logical_screen_size() -> tuple[int, int]:
    """
    Return primary display's logical dimensions (points, not Retina physical pixels).
    """
    try:
        if sys.platform == "darwin" and NSScreen is not None:
            frame = NSScreen.mainScreen().frame()
            w = int(frame.size.width)
            h = int(frame.size.height)
            if w > 0 and h > 0:
                return w, h
    except Exception as exc:
        logger.debug(f"NSScreen query: {exc}")

    # Fallback to pyautogui or default standard macOS resolution
    try:
        import pyautogui
        return pyautogui.size()
    except Exception:
        return 1440, 900


def capture_screen_image() -> dict:
    """
    Captures the desktop screen cleanly via screencapture, downsamples to
    logical resolution, and returns JPEG base64 and dimension metadata.
    """
    temp_path = os.path.join(tempfile.gettempdir(), "sahayak_screen_capture.png")
    canvas_w, canvas_h = get_logical_screen_size()

    try:
        # -x: mute sound, -C: capture cursor
        subprocess.run(["screencapture", "-x", "-C", temp_path], check=True, timeout=5)

        with Image.open(temp_path) as img:
            native_w, native_h = img.size
            resized = img.resize((canvas_w, canvas_h), Image.Resampling.LANCZOS)
            buf = io.BytesIO()
            resized.convert("RGB").save(buf, format="JPEG", quality=85)
            b64_data = base64.b64encode(buf.getvalue()).decode("utf-8")

        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass

        return {
            "image_base64": b64_data,
            "width": canvas_w,
            "height": canvas_h,
            "native_width": native_w,
            "native_height": native_h,
        }
    except Exception as exc:
        logger.error(f"Screen capture failed: {exc}")
        return {"error": str(exc), "image_base64": None, "width": canvas_w, "height": canvas_h}


def perform_local_ocr_on_screen() -> list[dict]:
    """
    Performs fast local OCR on the screen using Apple's Vision framework.
    Runs on the Apple Silicon Neural Engine in milliseconds without external APIs.
    Returns detected text snippets with approximate bounding boxes.
    """
    if not _HAS_VISION:
        return []

    temp_path = os.path.join(tempfile.gettempdir(), "sahayak_ocr_temp.png")
    try:
        subprocess.run(["screencapture", "-x", temp_path], check=True, timeout=4)
        image_url = Cocoa.NSURL.fileURLWithPath_(temp_path)
        handler = Vision.VNImageRequestHandler.alloc().initWithURL_options_(image_url, None)
        request = Vision.VNRecognizeTextRequest.alloc().init()
        request.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
        request.setUsesLanguageCorrection_(True)

        success = handler.performRequests_error_([request], None)
        results = request.results()

        text_blocks = []
        if results:
            for item in results:
                candidates = item.topCandidates_(1)
                if candidates:
                    text_str = candidates[0].string()
                    # Bounding box is in normalized coordinates (bottom-left origin in Vision)
                    bbox = item.boundingBox()
                    text_blocks.append({
                        "text": text_str,
                        "confidence": float(candidates[0].confidence()),
                        "x": float(bbox.origin.x),
                        "y": float(1.0 - bbox.origin.y),  # flip to top-left origin
                        "w": float(bbox.size.width),
                        "h": float(bbox.size.height),
                    })

        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass

        logger.info(f"Local Vision OCR extracted {len(text_blocks)} text segments.")
        return text_blocks
    except Exception as exc:
        logger.warning(f"perform_local_ocr_on_screen error: {exc}")
        return []


def get_active_app_context() -> dict:
    """
    Extracts the currently active foreground application, window title,
    and if a browser is active, the tab URL and title via AppleScript.
    """
    context = {"app_name": "Finder", "tab_url": "", "tab_title": ""}
    if sys.platform != "darwin":
        return context

    try:
        script = (
            'tell application "System Events"\n'
            '    set frontApp to name of first application process whose frontmost is true\n'
            '    return frontApp\n'
            'end tell'
        )
        r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=2)
        app_name = r.stdout.strip()
        if app_name:
            context["app_name"] = app_name

        # Browser tab info if applicable
        url_script = None
        title_script = None
        if app_name in ("Google Chrome", "Chromium"):
            url_script = 'tell application "Google Chrome" to return URL of active tab of front window'
            title_script = 'tell application "Google Chrome" to return title of active tab of front window'
        elif app_name == "Safari":
            url_script = 'tell application "Safari" to return URL of front document'
            title_script = 'tell application "Safari" to return name of front document'
        elif app_name == "Arc":
            url_script = 'tell application "Arc" to return URL of active tab of front window'
            title_script = 'tell application "Arc" to return title of active tab of front window'

        if url_script:
            u_res = subprocess.run(["osascript", "-e", url_script], capture_output=True, text=True, timeout=2)
            context["tab_url"] = u_res.stdout.strip()
        if title_script:
            t_res = subprocess.run(["osascript", "-e", title_script], capture_output=True, text=True, timeout=2)
            context["tab_title"] = t_res.stdout.strip()
    except Exception as exc:
        logger.debug(f"get_active_app_context error: {exc}")

    return context


def annotate_screenshot_ruler(image_b64: str, last_action: typing.Optional[dict] = None) -> str:
    """
    Draw ruler ticks along the edges and optional crosshair marker
    for model spatial calibration (normalized [0, 1000] scale).
    """
    try:
        img = Image.open(io.BytesIO(base64.b64decode(image_b64))).convert("RGB")
        draw = ImageDraw.Draw(img)
        w, h = img.size

        try:
            font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 13)
        except Exception:
            font = ImageFont.load_default()

        TICK_LEN = 12
        LABEL_PAD = 2
        TICK_STEPS = 5
        TICK_COLOR = (255, 60, 60)
        LABEL_COLOR = (255, 255, 255)
        step_norm = 1000 // TICK_STEPS

        for i in range(1, TICK_STEPS + 1):
            norm = i * step_norm
            # Top-edge (X)
            px = int(round((norm / 1000) * w))
            draw.line([(px, 0), (px, TICK_LEN)], fill=TICK_COLOR, width=2)
            draw.text((px + LABEL_PAD, LABEL_PAD), str(norm), fill=LABEL_COLOR, font=font)
            # Left-edge (Y)
            py = int(round((norm / 1000) * h))
            draw.line([(0, py), (TICK_LEN, py)], fill=TICK_COLOR, width=2)
            draw.text((LABEL_PAD, py + LABEL_PAD), str(norm), fill=LABEL_COLOR, font=font)

        # Crosshair at last action if click
        if last_action and last_action.get("command") == "click":
            norm_x = float(last_action.get("x", 0))
            norm_y = float(last_action.get("y", 0))
            px = int(round((norm_x / 1000) * w))
            py = int(round((norm_y / 1000) * h))
            r = 18
            draw.ellipse([px - r, py - r, px + r, py + r], outline="lime", width=3)
            draw.line([px - r * 2, py, px + r * 2, py], fill="lime", width=2)
            draw.line([px, py - r * 2, px, py + r * 2], fill="lime", width=2)
            draw.text((px + r + 5, py - 10), f"CLICK ({int(norm_x)},{int(norm_y)})", fill="lime", font=font)

        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        return base64.b64encode(buf.getvalue()).decode("utf-8")
    except Exception as exc:
        logger.error(f"annotate_screenshot_ruler error: {exc}")
        return image_b64

