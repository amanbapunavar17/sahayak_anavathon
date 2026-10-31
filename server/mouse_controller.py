"""
SAHAYAK — Mouse & Cursor Arrow Automatic Control Subsystem
Tagline: Your Voice. Your Freedom.
Platform: macOS (Apple Silicon M4)

Provides human-visible, automatic mouse cursor control:
  1. Smooth visual cursor arrow movement (glides across screen with natural easing).
  2. Multi-strategy button & element locator:
     - Apple Silicon Vision Local OCR bounding box extraction.
     - AppleScript macOS Accessibility (AXUIElement / System Events).
     - Screen landmark navigation (center, corners, traffic lights).
  3. Precision coordinate clicking (normalized [0, 1000] and absolute pixels).
  4. Specialized mouse actions: Single Click, Double Click, Right Click, Hover, Drag & Drop.
  5. Informative spoken feedback for blind and low-vision users.
"""

import logging
import math
import os
import re
import subprocess
import time
import typing
from pathlib import Path

import pyautogui

logger = logging.getLogger("sahayak-mouse")

# Configure PyAutoGUI safety and smooth movement defaults
pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.04

# Common UI screen landmarks
LANDMARKS = {
    "center": (0.5, 0.5),
    "middle": (0.5, 0.5),
    "center of screen": (0.5, 0.5),
    "top left": (0.05, 0.05),
    "top right": (0.95, 0.05),
    "bottom left": (0.05, 0.95),
    "bottom right": (0.95, 0.95),
    "top center": (0.5, 0.05),
    "bottom center": (0.5, 0.95),
    "close button": (0.015, 0.035),      # macOS traffic light red
    "minimize button": (0.025, 0.035),   # macOS traffic light yellow
    "zoom button": (0.035, 0.035),       # macOS traffic light green
    "traffic lights": (0.025, 0.035),
    "apple menu": (0.015, 0.012),
    "first video": (0.42, 0.28),
    "1st video": (0.42, 0.28),
    "second video": (0.42, 0.42),
    "2nd video": (0.42, 0.42),
    "third video": (0.42, 0.58),
    "3rd video": (0.42, 0.58),
}


class MouseController:
    """
    Autonomous mouse cursor controller providing visible, smooth arrow gliding
    and multi-strategy UI element clicking.
    """

    def __init__(self):
        self.screen_w, self.screen_h = pyautogui.size()
        logger.info(f"MouseController initialized for display {self.screen_w}x{self.screen_h}")

    def refresh_screen_size(self):
        """Updates display bounds dynamically."""
        self.screen_w, self.screen_h = pyautogui.size()

    def get_position(self) -> tuple[int, int]:
        """Returns the current pixel coordinates of the mouse cursor arrow."""
        pos = pyautogui.position()
        return pos.x, pos.y

    def get_normalized_position(self) -> tuple[int, int]:
        """Returns the current cursor position in normalized [0, 1000] space."""
        x, y = self.get_position()
        nx = int(round((x / max(1, self.screen_w - 1)) * 1000))
        ny = int(round((y / max(1, self.screen_h - 1)) * 1000))
        return nx, ny

    # -----------------------------------------------------------------------
    # 1. Smooth Visual Cursor Movement
    # -----------------------------------------------------------------------
    def move_cursor_to(
        self,
        pixel_x: int,
        pixel_y: int,
        duration: float = 0.35,
        smooth: bool = True,
    ) -> tuple[int, int]:
        """
        Smoothly glides the mouse cursor arrow to (pixel_x, pixel_y).
        Uses easeInOutQuad tweening so the user visibly sees the cursor arrow move.
        """
        self.refresh_screen_size()
        # Keep cursor slightly off (0,0) to prevent triggering PyAutoGUI failsafe
        clamped_x = max(2, min(self.screen_w - 2, int(round(pixel_x))))
        clamped_y = max(2, min(self.screen_h - 2, int(round(pixel_y))))

        curr_x, curr_y = self.get_position()
        distance = math.hypot(clamped_x - curr_x, clamped_y - curr_y)

        # Dynamically scale duration based on distance so short moves are snappy
        # while long diagonal movements glide visibly across the Mac screen.
        try:
            if smooth and distance > 10:
                effective_duration = max(0.18, min(0.55, distance / 1800.0 * 0.45 + 0.18))
                logger.info(f"GLIDE CURSOR: ({curr_x},{curr_y}) -> ({clamped_x},{clamped_y}) [dist={distance:.1f}px, duration={effective_duration:.2f}s]")
                pyautogui.moveTo(clamped_x, clamped_y, duration=effective_duration, tween=pyautogui.easeInOutQuad)
            else:
                pyautogui.moveTo(clamped_x, clamped_y)
        except Exception as e:
            logger.warning(f"Cursor movement exception: {e}")

        return clamped_x, clamped_y

    def move_cursor_norm(self, norm_x: int, norm_y: int, duration: float = 0.35) -> tuple[int, int]:
        """Moves cursor to coordinates specified in normalized [0, 1000] space."""
        self.refresh_screen_size()
        px = int(round((max(0, min(1000, norm_x)) / 1000.0) * (self.screen_w - 1)))
        py = int(round((max(0, min(1000, norm_y)) / 1000.0) * (self.screen_h - 1)))
        return self.move_cursor_to(px, py, duration=duration)

    # -----------------------------------------------------------------------
    # 2. Click Primitives
    # -----------------------------------------------------------------------
    def click_at(
        self,
        pixel_x: int,
        pixel_y: int,
        click_type: str = "single",
        button: str = "left",
        duration: float = 0.3,
    ) -> dict:
        """
        Moves mouse cursor visibly to (pixel_x, pixel_y), pauses briefly for hover effect,
        and performs the requested click (single, double, right).
        """
        target_x, target_y = self.move_cursor_to(pixel_x, pixel_y, duration=duration)
        time.sleep(0.06)  # Visual hover stabilization

        c_type = click_type.lower().strip()
        btn = button.lower().strip()

        try:
            if c_type in ("double", "double_click"):
                logger.info(f"DOUBLE CLICK: at ({target_x}, {target_y})")
                pyautogui.doubleClick(target_x, target_y, button=btn)
                feedback = f"Double-clicked at screen coordinate ({target_x}, {target_y})."
            elif c_type in ("right", "right_click") or btn == "right":
                logger.info(f"RIGHT CLICK: at ({target_x}, {target_y})")
                pyautogui.rightClick(target_x, target_y)
                feedback = f"Right-clicked at screen coordinate ({target_x}, {target_y})."
            elif c_type in ("triple", "triple_click"):
                logger.info(f"TRIPLE CLICK: at ({target_x}, {target_y})")
                pyautogui.tripleClick(target_x, target_y, button=btn)
                feedback = f"Triple-clicked at screen coordinate ({target_x}, {target_y})."
            else:
                logger.info(f"SINGLE CLICK: at ({target_x}, {target_y}) with {btn} button")
                pyautogui.click(target_x, target_y, button=btn)
                feedback = f"Clicked at screen coordinate ({target_x}, {target_y})."

            return {
                "status": "success",
                "command": "click",
                "click_type": c_type,
                "button": btn,
                "pixel_x": target_x,
                "pixel_y": target_y,
                "spoken_feedback": feedback,
            }
        except Exception as e:
            logger.error(f"Click execution error: {e}")
            return {
                "status": "failed",
                "command": "click",
                "error": str(e),
                "spoken_feedback": f"Could not perform click at coordinate ({target_x}, {target_y}).",
            }

    def click_current(self, click_type: str = "single", button: str = "left") -> dict:
        """Clicks at whatever position the mouse cursor arrow is currently resting."""
        curr_x, curr_y = self.get_position()
        return self.click_at(curr_x, curr_y, click_type=click_type, button=button, duration=0.0)

    def drag_and_drop(self, start_x: int, start_y: int, end_x: int, end_y: int, duration: float = 0.5) -> dict:
        """Drags mouse from (start_x, start_y) to (end_x, end_y)."""
        self.move_cursor_to(start_x, start_y, duration=0.2)
        time.sleep(0.05)
        pyautogui.dragTo(end_x, end_y, duration=duration, button="left")
        return {
            "status": "success",
            "command": "drag_and_drop",
            "from": (start_x, start_y),
            "to": (end_x, end_y),
            "spoken_feedback": f"Dragged from ({start_x}, {start_y}) to ({end_x}, {end_y}).",
        }

    # -----------------------------------------------------------------------
    # 3. Multi-Strategy Element Locating
    # -----------------------------------------------------------------------
    def find_element_on_screen(
        self,
        query: str,
        ocr_blocks: typing.Optional[list[dict]] = None,
    ) -> tuple[bool, typing.Optional[dict], str]:
        """
        Locates a button or interactive UI element on the screen matching `query`.
        Uses a 3-tier cascade:
          1. Landmark keywords (center, top right, traffic lights, etc.)
          2. Apple Silicon Vision Neural Engine local OCR bounding boxes.
          3. Native macOS AppleScript Accessibility UI element lookup.
        """
        if not query:
            return False, None, "No element query provided"

        clean_q = query.lower().strip()
        # Strip filler words: "the", "button", "named", "icon", "on", "at"
        clean_q = re.sub(r"^(?:on\s+|at\s+)?(?:the\s+)?", "", clean_q)
        clean_q = re.sub(r"\s+(?:button|icon|tab|link|field|box)$", "", clean_q)
        clean_q = re.sub(r"^(?:button\s+named|button\s+called|button)\s+", "", clean_q)
        clean_q = clean_q.strip(" '\"`")

        self.refresh_screen_size()

        # Strategy 1: Common Screen Landmarks
        if clean_q in LANDMARKS:
            norm_x, norm_y = LANDMARKS[clean_q]
            px = int(round(norm_x * (self.screen_w - 1)))
            py = int(round(norm_y * (self.screen_h - 1)))
            logger.info(f"MATCHED LANDMARK: '{clean_q}' -> pixel=({px}, {py})")
            return True, {
                "text": clean_q.title(),
                "pixel_x": px,
                "pixel_y": py,
                "norm_x": int(norm_x * 1000),
                "norm_y": int(norm_y * 1000),
                "match_type": "landmark",
                "confidence": 1.0,
            }, f"Found landmark '{clean_q}'"

        # Strategy 2: Apple Silicon Vision Neural Engine Local OCR
        if ocr_blocks is None:
            try:
                from screen_engine import perform_local_ocr_on_screen
                ocr_blocks = perform_local_ocr_on_screen()
            except Exception as e:
                logger.warning(f"Could not fetch OCR blocks: {e}")
                ocr_blocks = []

        if ocr_blocks:
            matched = self._match_ocr_block(clean_q, ocr_blocks)
            if matched:
                return True, matched, f"Located '{matched['text']}' on screen"

        # Strategy 3: Native macOS Accessibility (AppleScript System Events)
        ax_result = self._find_element_via_accessibility(clean_q)
        if ax_result:
            return True, ax_result, f"Located '{clean_q}' via macOS Accessibility"

        # List sample visible labels for helpful diagnostic feedback
        sample_texts = [b.get("text", "") for b in ocr_blocks[:4] if len(b.get("text", "")) > 2]
        samples_str = f" Visible items include: {', '.join(sample_texts)}." if sample_texts else ""
        return False, None, f"Could not find button or element '{query}' on screen.{samples_str}"

    def _match_ocr_block(self, query: str, blocks: list[dict]) -> typing.Optional[dict]:
        """Matches a search query against extracted OCR blocks with confidence scoring."""
        self.refresh_screen_size()
        q = query.lower().strip()

        best_block = None
        best_score = 0.0

        for b in blocks:
            text = b.get("text", "").strip()
            if not text:
                continue
            lower_text = text.lower()

            # Score calculation
            score = 0.0
            if lower_text == q:
                score = 1.0  # Exact match
            elif q in [w.strip(" .,;:-_!?()[]") for w in lower_text.split()]:
                score = 0.9  # Whole word match
            elif q in lower_text:
                # Substring match, penalize if length difference is huge
                score = 0.75 * (len(q) / max(len(q), len(lower_text)))
            elif any(w in lower_text for w in q.split() if len(w) > 2):
                score = 0.5  # Partial token match

            if score > best_score:
                best_score = score
                best_block = b

        if best_block and best_score >= 0.4:
            # Check if block already contains pre-calculated pixel coordinates from screen_engine
            if "pixel_x" in best_block and "pixel_y" in best_block:
                px = int(round(best_block["pixel_x"]))
                py = int(round(best_block["pixel_y"]))
                nx = int(round(best_block.get("center_norm_x", (px / max(1, self.screen_w - 1)) * 1000.0)))
                ny = int(round(best_block.get("center_norm_y", (py / max(1, self.screen_h - 1)) * 1000.0)))
            else:
                # Calculate exact center pixel coordinates
                # In Vision OCR: x, y, w, h are normalized [0, 1]
                bx = best_block.get("x", 0.0)
                bw = best_block.get("w", 0.0)
                bh = best_block.get("h", 0.0)
                by = best_block.get("y", 0.0)

                # Center X
                cx = bx + (bw / 2.0)
                # Center Y in top-down coordinates
                # screen_engine stores y as top-down baseline; center is y - bh/2.0
                cy = by - (bh / 2.0) if by > bh else by + (bh / 2.0)

                px = int(round(cx * (self.screen_w - 1)))
                py = int(round(cy * (self.screen_h - 1)))
                nx = int(round(cx * 1000.0))
                ny = int(round(cy * 1000.0))

            logger.info(f"OCR MATCHED '{query}' -> '{best_block.get('text')}' (score={best_score:.2f}) at pixel=({px}, {py})")
            return {
                "text": best_block.get("text"),
                "pixel_x": px,
                "pixel_y": py,
                "norm_x": nx,
                "norm_y": ny,
                "match_type": "ocr",
                "confidence": best_score,
            }

        return None

    def _find_element_via_accessibility(self, query: str) -> typing.Optional[dict]:
        """Queries macOS Accessibility (System Events) for button positions in the frontmost window."""
        safe_q = query.replace('"', '\\"')
        script = f"""
        tell application "System Events"
            set frontProc to first application process whose frontmost is true
            tell frontProc
                repeat with w in windows
                    try
                        set btnList to (every button of w whose name contains "{safe_q}" or description contains "{safe_q}")
                        if (count of btnList) > 0 then
                            set b to item 1 of btnList
                            set bPos to position of b
                            set bSize to size of b
                            return (item 1 of bPos) & "," & (item 2 of bPos) & "," & (item 1 of bSize) & "," & (item 2 of bSize)
                        end if
                    end try
                end repeat
            end tell
        end tell
        """
        try:
            r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=2.0)
            if r.returncode == 0 and r.stdout.strip():
                parts = [float(p.strip()) for p in r.stdout.strip().split(",")]
                if len(parts) >= 4:
                    bx, by, bw, bh = parts[0], parts[1], parts[2], parts[3]
                    center_x = int(round(bx + bw / 2.0))
                    center_y = int(round(by + bh / 2.0))
                    logger.info(f"ACCESSIBILITY MATCHED '{query}' at pixel=({center_x}, {center_y})")
                    return {
                        "text": query.title(),
                        "pixel_x": center_x,
                        "pixel_y": center_y,
                        "norm_x": int(round((center_x / max(1, self.screen_w - 1)) * 1000)),
                        "norm_y": int(round((center_y / max(1, self.screen_h - 1)) * 1000)),
                        "match_type": "accessibility",
                        "confidence": 0.95,
                    }
        except Exception as e:
            logger.debug(f"Accessibility lookup for '{query}' failed: {e}")
        return None

    # -----------------------------------------------------------------------
    # 4. High-Level Element Clicking
    # -----------------------------------------------------------------------
    def click_element(
        self,
        target_element: typing.Optional[str] = None,
        click_type: str = "single",
        button: str = "left",
        x: typing.Optional[int] = None,
        y: typing.Optional[int] = None,
        ocr_blocks: typing.Optional[list[dict]] = None,
    ) -> dict:
        """
        Autonomous button & element clicking:
          1. If coordinates (x, y) provided, moves cursor arrow visibly and clicks.
          2. If target_element provided, locates the button on screen, moves cursor arrow to it, and clicks.
          3. If neither provided, clicks at current cursor position.
        """
        # Coordinate-based click
        if x is not None and y is not None:
            # Determine if coordinates are normalized [0, 1000] or absolute pixels
            if x <= 1000 and y <= 1000 and (self.screen_w > 1000 or self.screen_h > 1000):
                px = int(round((x / 1000.0) * (self.screen_w - 1)))
                py = int(round((y / 1000.0) * (self.screen_h - 1)))
            else:
                px, py = int(x), int(y)
            return self.click_at(px, py, click_type=click_type, button=button)

        # Target element lookup
        if target_element:
            found, elem_info, msg = self.find_element_on_screen(target_element, ocr_blocks=ocr_blocks)
            if found and elem_info:
                px = elem_info["pixel_x"]
                py = elem_info["pixel_y"]
                label = elem_info.get("text", target_element)

                # Move cursor arrow visibly to button and click
                res = self.click_at(px, py, click_type=click_type, button=button)
                c_verb = "Double-clicked" if click_type in ("double", "double_click") else ("Right-clicked" if click_type in ("right", "right_click") else "Clicked")
                feedback = f"{c_verb} button '{label}'."
                res["spoken_feedback"] = feedback
                res["target_element"] = label
                return res
            else:
                logger.warning(f"Could not locate element: '{target_element}'")
                return {
                    "status": "failed",
                    "command": "click_element",
                    "target_element": target_element,
                    "spoken_feedback": msg,
                }

        # Current cursor click
        return self.click_current(click_type=click_type, button=button)

    def move_mouse(
        self,
        target: typing.Optional[str] = None,
        x: typing.Optional[int] = None,
        y: typing.Optional[int] = None,
    ) -> dict:
        """
        Moves the mouse cursor arrow to a target element, landmark, or coordinates.
        """
        if x is not None and y is not None:
            px = int(round((x / 1000.0) * (self.screen_w - 1))) if x <= 1000 and y <= 1000 else int(x)
            py = int(round((y / 1000.0) * (self.screen_h - 1))) if x <= 1000 and y <= 1000 else int(y)
            final_x, final_y = self.move_cursor_to(px, py)
            return {
                "status": "success",
                "command": "move_mouse",
                "pixel_x": final_x,
                "pixel_y": final_y,
                "spoken_feedback": f"Moved cursor to ({final_x}, {final_y}).",
            }

        if target:
            found, elem_info, msg = self.find_element_on_screen(target)
            if found and elem_info:
                px = elem_info["pixel_x"]
                py = elem_info["pixel_y"]
                final_x, final_y = self.move_cursor_to(px, py)
                label = elem_info.get("text", target)
                return {
                    "status": "success",
                    "command": "move_mouse",
                    "target": label,
                    "pixel_x": final_x,
                    "pixel_y": final_y,
                    "spoken_feedback": f"Moved cursor to '{label}'.",
                }
            return {
                "status": "failed",
                "command": "move_mouse",
                "target": target,
                "spoken_feedback": msg,
            }

        # Default center
        cx = self.screen_w // 2
        cy = self.screen_h // 2
        final_x, final_y = self.move_cursor_to(cx, cy)
        return {
            "status": "success",
            "command": "move_mouse",
            "pixel_x": final_x,
            "pixel_y": final_y,
            "spoken_feedback": f"Moved cursor to screen center ({final_x}, {final_y}).",
        }


# Global Singleton Instance
mouse_controller = MouseController()
