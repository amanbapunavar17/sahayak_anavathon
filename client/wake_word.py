"""
SAHAYAK — macOS Desktop Client v3.0
Tagline: Your Voice. Your Freedom.

Provides:
  - Free-first voice triggering (Microphone VAD / Push-to-Talk / Optional Porcupine)
  - Spoken audio feedback via macOS native TTS
  - Fullscreen activity border overlay (AppKit NSPanel)
  - Native screen capture with logical point downsampling
  - OS-level input execution (PyAutoGUI + AppleScript)
  - Realtime WebSocket streaming to SAHAYAK Server (ws://localhost:8080/ws/agent)
"""

import asyncio
import base64
import io
import json
import logging
import math
import os
import queue
import signal
import struct
import subprocess
import sys
import tempfile
import threading
import time
from typing import Callable, Optional, Tuple

from dotenv import load_dotenv
from PIL import Image

load_dotenv()

# AppKit & Quartz macOS UI frameworks
objc = None
NSApp = NSApplication = NSApplicationActivationPolicyProhibited = None
NSBezierPath = NSColor = NSMakeRect = NSObject = None
NSFloatingWindowLevel = NSPanel = NSScreen = NSScreenSaverWindowLevel = None
NSTimer = NSView = None
NSWindowCollectionBehaviorCanJoinAllSpaces = None
NSWindowCollectionBehaviorFullScreenAuxiliary = None
NSWindowCollectionBehaviorStationary = None
NSWindowStyleMaskBorderless = None

try:
    if sys.platform == "darwin":
        import objc
        from AppKit import (
            NSApp,
            NSApplication,
            NSApplicationActivationPolicyProhibited,
            NSBezierPath,
            NSColor,
            NSMakeRect,
            NSObject,
            NSFloatingWindowLevel,
            NSPanel,
            NSScreen,
            NSScreenSaverWindowLevel,
            NSTimer,
            NSView,
            NSWindowCollectionBehaviorCanJoinAllSpaces,
            NSWindowCollectionBehaviorFullScreenAuxiliary,
            NSWindowCollectionBehaviorStationary,
            NSWindowStyleMaskBorderless,
        )
        import Quartz
        _HAS_QUARTZ = True
    else:
        _HAS_QUARTZ = False
except Exception:
    _HAS_QUARTZ = False

import pyautogui

# Sounddevice / PyAudio for microphone capture
_AUDIO_BACKEND = "none"
try:
    import sounddevice as sd
    _AUDIO_BACKEND = "sounddevice"
except ImportError:
    try:
        import pyaudio
        _AUDIO_BACKEND = "pyaudio"
    except ImportError:
        pass

# Optional Porcupine wake word
_HAS_PORCUPINE = False
try:
    import pvporcupine
    _HAS_PORCUPINE = True
except ImportError:
    pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("sahayak-client")


def speak_local(text: str) -> None:
    """Non-blocking local spoken announcement via macOS say."""
    try:
        subprocess.Popen(
            ["say", "-v", "Samantha", "-r", "190", text],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass


def get_logical_screen_size() -> Tuple[int, int]:
    try:
        if sys.platform == "darwin" and NSScreen is not None:
            frame = NSScreen.mainScreen().frame()
            w, h = int(frame.size.width), int(frame.size.height)
            if w > 0 and h > 0:
                return w, h
    except Exception:
        pass
    return pyautogui.size()


def capture_screen_sync() -> dict:
    file_path = os.path.join(tempfile.gettempdir(), "sahayak_client_capture.png")
    canvas_w, canvas_h = get_logical_screen_size()
    try:
        subprocess.run(["screencapture", "-x", "-C", file_path], check=True, timeout=5)
        with Image.open(file_path) as img:
            native_w, native_h = img.size
            resized = img.resize((canvas_w, canvas_h), Image.Resampling.LANCZOS)
            buf = io.BytesIO()
            resized.convert("RGB").save(buf, format="JPEG", quality=85)
            b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
        if os.path.exists(file_path):
            os.remove(file_path)
        return {"image_base64": b64, "width": canvas_w, "height": canvas_h}
    except Exception as exc:
        logger.error(f"Screen capture failed: {exc}")
        return {"error": str(exc), "image_base64": "", "width": canvas_w, "height": canvas_h}


def get_active_app_context_sync() -> dict:
    ctx = {"app_name": "Finder", "tab_url": "", "tab_title": ""}
    try:
        r = subprocess.run(
            ["osascript", "-e", 'tell application "System Events" to return name of first application process whose frontmost is true'],
            capture_output=True, text=True, timeout=2,
        )
        ctx["app_name"] = r.stdout.strip() or "Finder"
    except Exception:
        pass
    return ctx


# ---------------------------------------------------------------------------
# Activity Overlay (AppKit Neon Border)
# ---------------------------------------------------------------------------
class ActivityOverlay:
    def __init__(self):
        self._cmd_queue: "queue.Queue[tuple[str, Optional[bool]]]" = queue.Queue()
        self._thread: Optional[threading.Thread] = None
        self._enabled = sys.platform == "darwin" and objc is not None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, name="SahayakOverlay", daemon=True)
        self._thread.start()

    def run_forever(self) -> None:
        if not self._enabled:
            logger.info("Activity overlay disabled (headless or pyobjc absent).")
            while True:
                time.sleep(1)
        self._run()

    def set_active(self, active: bool) -> None:
        self._cmd_queue.put(("active", active))

    def suspend(self) -> None:
        self._cmd_queue.put(("suspend", True))

    def resume(self) -> None:
        self._cmd_queue.put(("suspend", False))

    def shutdown(self) -> None:
        self._cmd_queue.put(("shutdown", None))

    def _run(self) -> None:
        if not self._enabled:
            return

        class _OverlayView(NSView):
            def initWithFrame_(self, frame):
                self = objc.super(_OverlayView, self).initWithFrame_(frame)
                if self is None:
                    return None
                self._active = False
                self._suspended = False
                self._phase = 0.0
                return self

            def update_state(self, state):
                self._active = bool(state.get("active"))
                self._suspended = bool(state.get("suspended"))

            def step_(self, _timer):
                if self._active and not self._suspended:
                    self._phase = (self._phase + 0.08) % (2 * math.pi)
                self.setNeedsDisplay_(True)

            def drawRect_(self, rect):
                if not self._active or self._suspended:
                    return
                bounds = self.bounds()
                inset = 12.0
                corner = 20.0
                path_rect = NSMakeRect(
                    bounds.origin.x + inset,
                    bounds.origin.y + inset,
                    bounds.size.width - (inset * 2),
                    bounds.size.height - (inset * 2),
                )
                path = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(path_rect, corner, corner)
                t = (math.sin(self._phase) + 1.0) / 2.0
                base = (0.2 + 0.4 * t, 0.7 + 0.3 * (1 - t), 1.0, 0.9)
                glow = NSColor.colorWithCalibratedRed_green_blue_alpha_(base[0], base[1], base[2], 0.3)
                glow.setStroke()
                glow_path = path.copy()
                glow_path.setLineWidth_(14.0)
                glow_path.stroke()
                stroke = NSColor.colorWithCalibratedRed_green_blue_alpha_(base[0], base[1], base[2], 0.95)
                stroke.setStroke()
                path.setLineWidth_(7.0)
                path.stroke()

        class _NonActivatingPanel(NSPanel):
            def canBecomeKeyWindow(self):
                return False
            def canBecomeMainWindow(self):
                return False

        ns_app = NSApplication.sharedApplication()
        ns_app.setActivationPolicy_(NSApplicationActivationPolicyProhibited)
        screen = NSScreen.mainScreen()
        frame = screen.frame()
        panel = _NonActivatingPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            frame, NSWindowStyleMaskBorderless, 2, False
        )
        panel.setOpaque_(False)
        panel.setBackgroundColor_(NSColor.clearColor())
        panel.setHasShadow_(False)
        panel.setIgnoresMouseEvents_(True)
        panel.setLevel_(NSFloatingWindowLevel)
        panel.setCollectionBehavior_(
            NSWindowCollectionBehaviorCanJoinAllSpaces
            | NSWindowCollectionBehaviorFullScreenAuxiliary
            | NSWindowCollectionBehaviorStationary
        )

        view = _OverlayView.alloc().initWithFrame_(frame)
        panel.setContentView_(view)
        panel.orderOut_(None)

        state = {"active": False, "suspended": False}

        def _poll_commands(_timer):
            try:
                while True:
                    cmd, val = self._cmd_queue.get_nowait()
                    if cmd == "active":
                        state["active"] = bool(val)
                        if state["active"]:
                            panel.orderFront_(None)
                        else:
                            panel.orderOut_(None)
                    elif cmd == "suspend":
                        state["suspended"] = bool(val)
                    elif cmd == "shutdown":
                        panel.orderOut_(None)
                        ns_app.stop_(None)
                        return
            except queue.Empty:
                pass
            view.update_state(state)
            if state["active"]:
                panel.orderFront_(None)
                panel.displayIfNeeded()

        NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(0.05, view, "step:", None, True)
        NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(0.05, view, "step:", None, True)
        ns_app.run()


# ---------------------------------------------------------------------------
# Free-First Voice Streamer
# ---------------------------------------------------------------------------
async def client_voice_stream(overlay: ActivityOverlay, stop_event: threading.Event):
    import websockets
    uri = os.getenv("SAHAYAK_SERVER_WS_URL", "ws://localhost:8080/ws/agent")

    logger.info(f"Connecting to SAHAYAK server at {uri}...")
    speak_local("SAHAYAK desktop assistant ready.")

    while not stop_event.is_set():
        try:
            async with websockets.connect(uri) as ws:
                logger.info("Connected to SAHAYAK Server.")
                # Send handshake
                await ws.send(json.dumps({
                    "event": "wake_word_detected",
                    "timestamp": time.time(),
                }))

                async for message in ws:
                    if stop_event.is_set():
                        break

                    if isinstance(message, str):
                        data = json.loads(message)
                        cmd = data.get("command")

                        if cmd == "set_activity":
                            overlay.set_active(data.get("state") == "active")

                        elif cmd == "capture_screen":
                            overlay.suspend()
                            try:
                                cap = capture_screen_sync()
                                ctx = get_active_app_context_sync()
                                await ws.send(json.dumps({
                                    "event": "screen_captured",
                                    "image_base64": cap["image_base64"],
                                    "width": cap["width"],
                                    "height": cap["height"],
                                    "app_context": ctx,
                                }))
                            finally:
                                overlay.resume()

                        elif cmd == "click":
                            x, y = data.get("x"), data.get("y")
                            if x is not None and y is not None:
                                from action_executor import execute_click
                                execute_click(int(x), int(y))

                        elif cmd == "scroll":
                            from action_executor import execute_scroll
                            execute_scroll(int(data.get("amount", -10)))

                        elif cmd == "type_text":
                            from action_executor import execute_type_spotlight
                            execute_type_spotlight(data.get("text", ""))

                        elif cmd == "keyboard_type":
                            from action_executor import execute_keyboard_type
                            execute_keyboard_type(data.get("text", ""))

                        elif cmd == "open_url":
                            from action_executor import execute_open_url
                            execute_open_url(data.get("url", ""))

                        elif cmd == "press_hotkey":
                            from action_executor import execute_hotkey
                            execute_hotkey(data.get("keys", []))

                        elif cmd == "speak":
                            speak_local(data.get("text", ""))

        except (websockets.ConnectionClosed, ConnectionRefusedError) as e:
            logger.info("Server disconnected, retrying in 3 seconds...")
            await asyncio.sleep(3)
        except Exception as exc:
            logger.error(f"Client streaming exception: {exc}")
            await asyncio.sleep(3)


def _run_async_thread(overlay: ActivityOverlay, stop_event: threading.Event):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(client_voice_stream(overlay, stop_event))
    finally:
        loop.close()


if __name__ == "__main__":
    overlay = ActivityOverlay()
    stop_event = threading.Event()

    # Import and start Global Wake Word Service & Floating Popup
    try:
        from client.wake_word_service import wake_service, play_chime
        from client.floating_popup import floating_popup

        def _on_wake():
            logger.info("HELLO SAHAY wake word activated!")
            overlay.set_active(True)
            floating_popup.show()
            floating_popup.update_state(mic="Listening...")

        def _on_command(cmd_text: str):
            logger.info(f"Executing voice command: '{cmd_text}'")
            floating_popup.update_state(query=cmd_text, mic="Processing...")
            try:
                import httpx
                api_url = os.getenv("SAHAYAK_SERVER_URL", "http://localhost:8080/api/chat")
                res = httpx.post(api_url, json={"message": cmd_text}, timeout=30.0)
                if res.status_code == 200:
                    d = res.json()
                    floating_popup.update_state(response=d.get("spoken_response", "Action completed."), mic="Idle")
                else:
                    floating_popup.update_state(response=f"Server returned {res.status_code}", mic="Idle")
            except Exception as e:
                logger.error(f"Command execution error: {e}")
                floating_popup.update_state(response=str(e), mic="Idle")
            finally:
                time.sleep(2.0)
                overlay.set_active(False)

        wake_service.on_wake = _on_wake
        wake_service.on_command = _on_command
        wake_service.start()
        floating_popup.start()
        logger.info("Global Wake Word Service ('HELLO SAHAY') and Floating Assistant active.")
    except Exception as exc:
        logger.warning(f"Could not initialize background wake-word/floating popup: {exc}")

    def _sigint(sig, frame):
        logger.info("Shutdown requested.")
        stop_event.set()
        try:
            wake_service.stop()
            floating_popup.hide()
        except Exception:
            pass
        overlay.shutdown()

    signal.signal(signal.SIGINT, _sigint)

    worker = threading.Thread(target=_run_async_thread, args=(overlay, stop_event), daemon=True)
    worker.start()

    logger.info("SAHAYAK macOS Desktop Client started.")
    try:
        overlay.run_forever()
    except KeyboardInterrupt:
        stop_event.set()
