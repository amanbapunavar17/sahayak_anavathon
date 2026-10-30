"""
SAHAYAK — Global Floating Assistant & Global Shortcut Engine
Tagline: Your Voice. Your Freedom.
Platform: macOS (Apple Silicon M4)

Provides:
  1. Lightweight, always-on-top floating popup window (AppKit NSPanel at NSFloatingWindowLevel)
     - Visible over Safari, Chrome, YouTube, Finder, Notes, and all normal apps
     - Identity, Gemini online/offline pill, Mic state, Conversation transcript, Task progress
     - Stop/Cancel button, Hide button, Typed command input
     - Non-activating by default so it never steals focus from the user's active workflow
  2. Configurable Global Keyboard Shortcut (Option + Space)
     - Summons SAHAYAK from anywhere on macOS without requiring dashboard or terminal
     - Plays activation sound and activates listening / input
"""

import logging
import os
import subprocess
import sys
import threading
import time
import typing
from pathlib import Path

# Add project root to sys.path
_PROJECT_DIR = Path(__file__).resolve().parent.parent
if str(_PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(_PROJECT_DIR))
_SERVER_DIR = _PROJECT_DIR / "server"
if str(_SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(_SERVER_DIR))

logger = logging.getLogger("sahayak-popup")

# Check macOS AppKit availability
_HAS_APPKIT = False
if sys.platform == "darwin":
    try:
        import objc
        from AppKit import (
            NSApplication,
            NSApplicationActivationPolicyProhibited,
            NSPanel,
            NSWindow,
            NSScreen,
            NSView,
            NSTextField,
            NSButton,
            NSColor,
            NSFont,
            NSMakeRect,
            NSFloatingWindowLevel,
            NSWindowStyleMaskTitled,
            NSWindowStyleMaskClosable,
            NSWindowStyleMaskNonactivatingPanel,
            NSWindowCollectionBehaviorCanJoinAllSpaces,
            NSWindowCollectionBehaviorFullScreenAuxiliary,
            NSWindowCollectionBehaviorStationary,
            NSEvent,
            NSKeyDownMask,
            NSAlternateKeyMask,
            NSTimer,
            NSBezelStyleRounded,
        )
        _HAS_APPKIT = True
    except Exception as exc:
        logger.warning(f"AppKit UI unavailable ({exc}). Using web popup companion.")


class FloatingPopupController:
    """
    Manages the floating macOS overlay panel and global hotkey listener.
    """

    def __init__(self):
        self._panel = None
        self._app = None
        self._status_label = None
        self._task_label = None
        self._transcript_label = None
        self._input_field = None
        self._hotkey_monitor = None
        
        self.is_visible = False
        self.shortcut_desc = "Option + Space"
        self._thread: typing.Optional[threading.Thread] = None
        self._lock = threading.Lock()
        
        # State values
        self.gemini_status = "Online AI"
        self.mic_status = "Idle"
        self.task_progress = "Idle"
        self.latest_query = "Ready to assist."
        self.latest_response = "Say 'HELLO SAHAY' or press Option+Space."

    def start(self) -> None:
        """Starts the floating popup manager in a dedicated AppKit thread."""
        if not _HAS_APPKIT:
            logger.info("Floating popup: AppKit not available, relying on http://localhost:8080/popup.")
            return

        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._thread = threading.Thread(target=self._run_appkit_loop, name="SahayakPopupThread", daemon=True)
            self._thread.start()
            logger.info("FloatingPopupController started.")

    def show(self) -> None:
        """Shows the floating panel over active applications."""
        if self._panel:
            try:
                self._panel.orderFrontRegardless()
                self.is_visible = True
            except Exception as e:
                logger.debug(f"Panel show error: {e}")

    def hide(self) -> None:
        """Hides the floating panel."""
        if self._panel:
            try:
                self._panel.orderOut_(None)
                self.is_visible = False
            except Exception as e:
                logger.debug(f"Panel hide error: {e}")

    def toggle(self) -> None:
        """Toggles visibility of the floating popup."""
        if self.is_visible:
            self.hide()
        else:
            self.show()

    def update_state(
        self,
        gemini: typing.Optional[str] = None,
        mic: typing.Optional[str] = None,
        task: typing.Optional[str] = None,
        query: typing.Optional[str] = None,
        response: typing.Optional[str] = None,
    ) -> None:
        """Updates UI status pills and conversation text."""
        if gemini:
            self.gemini_status = gemini
        if mic:
            self.mic_status = mic
        if task:
            self.task_progress = task
        if query:
            self.latest_query = query
        if response:
            self.latest_response = response

        self._refresh_ui_labels()

    def _refresh_ui_labels(self) -> None:
        """Applies updated text to AppKit controls."""
        if not _HAS_APPKIT:
            return
        try:
            if self._status_label:
                self._status_label.setStringValue_(f"AI: {self.gemini_status}  |  Mic: {self.mic_status}")
            if self._task_label:
                self._task_label.setStringValue_(f"Task: {self.task_progress}")
            if self._transcript_label:
                self._transcript_label.setStringValue_(f"User: {self.latest_query}\nSAHAYAK: {self.latest_response}")
        except Exception:
            pass

    def _on_global_hotkey(self, event) -> None:
        """
        Global keydown callback. Intercepts Option + Space (keyCode 49 with Alt mask).
        """
        try:
            flags = event.modifierFlags()
            key_code = event.keyCode()
            # 49 is Spacebar keycode on macOS
            is_alt = bool(flags & NSAlternateKeyMask)
            if is_alt and key_code == 49:
                logger.info("Global shortcut triggered: Option + Space!")
                # Play chime and summon popup
                from client.wake_word_service import play_chime, wake_service
                play_chime()
                self.show()
                self.update_state(mic="Listening...")
                wake_service.trigger_wake()
        except Exception as e:
            logger.debug(f"Global hotkey handler exception: {e}")

    def _run_appkit_loop(self) -> None:
        """Initializes NSPanel and runs Cocoa event loop."""
        try:
            self._app = NSApplication.sharedApplication()
            self._app.setActivationPolicy_(NSApplicationActivationPolicyProhibited)

            # Calculate top-right position
            screen = NSScreen.mainScreen()
            frame = screen.frame() if screen else NSMakeRect(0, 0, 1440, 900)
            panel_w = 400.0
            panel_h = 240.0
            panel_x = frame.size.width - panel_w - 24.0
            panel_y = frame.size.height - panel_h - 48.0

            content_rect = NSMakeRect(panel_x, panel_y, panel_w, panel_h)
            style_mask = (
                NSWindowStyleMaskTitled
                | NSWindowStyleMaskClosable
                | NSWindowStyleMaskNonactivatingPanel
            )

            self._panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
                content_rect, style_mask, 2, False
            )
            self._panel.setTitle_("SAHAYAK — Your Voice. Your Freedom.")
            self._panel.setLevel_(NSFloatingWindowLevel)
            self._panel.setOpaque_(False)
            self._panel.setBackgroundColor_(NSColor.colorWithCalibratedRed_green_blue_alpha_(0.10, 0.11, 0.14, 0.94))
            self._panel.setCollectionBehavior_(
                NSWindowCollectionBehaviorCanJoinAllSpaces
                | NSWindowCollectionBehaviorFullScreenAuxiliary
                | NSWindowCollectionBehaviorStationary
            )

            content_view = self._panel.contentView()

            # Status pill label
            self._status_label = NSTextField.alloc().initWithFrame_(NSMakeRect(16, 175, 368, 22))
            self._status_label.setEditable_(False)
            self._status_label.setSelectable_(False)
            self._status_label.setBezeled_(False)
            self._status_label.setDrawsBackground_(False)
            self._status_label.setTextColor_(NSColor.colorWithCalibratedRed_green_blue_alpha_(0.3, 0.9, 0.4, 1.0))
            self._status_label.setFont_(NSFont.boldSystemFontOfSize_(12))
            content_view.addSubview_(self._status_label)

            # Task progress label
            self._task_label = NSTextField.alloc().initWithFrame_(NSMakeRect(16, 150, 368, 20))
            self._task_label.setEditable_(False)
            self._task_label.setSelectable_(False)
            self._task_label.setBezeled_(False)
            self._task_label.setDrawsBackground_(False)
            self._task_label.setTextColor_(NSColor.colorWithCalibratedRed_green_blue_alpha_(0.9, 0.8, 0.2, 1.0))
            self._task_label.setFont_(NSFont.systemFontOfSize_(11))
            content_view.addSubview_(self._task_label)

            # Transcript text area
            self._transcript_label = NSTextField.alloc().initWithFrame_(NSMakeRect(16, 50, 368, 90))
            self._transcript_label.setEditable_(False)
            self._transcript_label.setSelectable_(True)
            self._transcript_label.setBezeled_(False)
            self._transcript_label.setDrawsBackground_(False)
            self._transcript_label.setTextColor_(NSColor.whiteColor())
            self._transcript_label.setFont_(NSFont.systemFontOfSize_(12))
            content_view.addSubview_(self._transcript_label)

            # Hide button
            hide_btn = NSButton.alloc().initWithFrame_(NSMakeRect(300, 12, 84, 28))
            hide_btn.setTitle_("Hide")
            hide_btn.setBezelStyle_(NSBezelStyleRounded)
            hide_btn.setTarget_(self)
            hide_btn.setAction_("hideAction:")
            content_view.addSubview_(hide_btn)

            # Cancel button
            cancel_btn = NSButton.alloc().initWithFrame_(NSMakeRect(200, 12, 95, 28))
            cancel_btn.setTitle_("Cancel Task")
            cancel_btn.setBezelStyle_(NSBezelStyleRounded)
            cancel_btn.setTarget_(self)
            cancel_btn.setAction_("cancelAction:")
            content_view.addSubview_(cancel_btn)

            # Initial values
            self._refresh_ui_labels()

            # Register Global Hotkey Monitor (Option + Space)
            self._hotkey_monitor = NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(
                NSKeyDownMask, self._on_global_hotkey
            )

            # Keep panel hidden initially until summoned
            self._panel.orderOut_(None)
            self.is_visible = False

            logger.info("Floating popup & Option+Space global shortcut initialized.")
            self._app.run()

        except Exception as e:
            logger.warning(f"AppKit run loop error: {e}")

    def hideAction_(self, sender):
        """AppKit button action: Hide."""
        self.hide()

    def cancelAction_(self, sender):
        """AppKit button action: Cancel Task."""
        try:
            from server.task_engine import task_engine
            task_engine.cancel_active_task()
            self.update_state(task="Cancelled")
        except Exception:
            pass


# Global Singleton
floating_popup = FloatingPopupController()

