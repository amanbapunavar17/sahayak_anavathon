"""
SAHAYAK — Mouse Cursor & UI Button Control Test Suite
Tagline: Your Voice. Your Freedom.
Platform: macOS (Apple Silicon M4)

Tests:
  1. Smooth visual cursor arrow movement and position tracking.
  2. Coordinate and landmark element locator.
  3. Vision OCR bounding box button resolution.
  4. Intent classification for single click, double click, right click, mouse move.
  5. Multi-step workflows containing button clicks.
  6. Truthful failure reporting when element is not found on screen.
  7. Full API endpoint integration for button clicking and mouse control.
"""

import asyncio
import os
import sys
import time
from pathlib import Path

# Add project root and server to sys.path
_PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_DIR))
_SERVER_DIR = _PROJECT_DIR / "server"
sys.path.insert(0, str(_SERVER_DIR))

import pytest
from fastapi.testclient import TestClient
from server.main import app
from server.intent_classifier import classify_intent, IntentType
from server.mouse_controller import mouse_controller, MouseController, LANDMARKS
from server.action_executor import execute_click_element, execute_mouse_move, execute_click
from server.task_engine import task_engine, TaskEngine, StepStatus


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client


# ---------------------------------------------------------------------------
# 1. Mouse Controller Primitives & Movement
# ---------------------------------------------------------------------------
def test_mouse_controller_position_and_display():
    """Verifies display dimensions and cursor coordinates."""
    mc = MouseController()
    w, h = mc.screen_w, mc.screen_h
    assert w > 0 and h > 0, "Display dimensions must be positive"

    pos_x, pos_y = mc.get_position()
    assert 0 <= pos_x <= w + 100, f"Cursor X ({pos_x}) within display bounds"
    assert 0 <= pos_y <= h + 100, f"Cursor Y ({pos_y}) within display bounds"

    norm_x, norm_y = mc.get_normalized_position()
    assert 0 <= norm_x <= 1000
    assert 0 <= norm_y <= 1000


def test_mouse_controller_smooth_gliding():
    """Verifies cursor movement clamps and returns target coordinates."""
    mc = MouseController()
    # Move to center
    cx, cy = mc.screen_w // 2, mc.screen_h // 2
    final_x, final_y = mc.move_cursor_to(cx, cy, duration=0.05, smooth=False)
    assert final_x == cx
    assert final_y == cy

    # Move using normalized coordinates
    norm_x, norm_y = 500, 500
    res_x, res_y = mc.move_cursor_norm(norm_x, norm_y, duration=0.05)
    assert abs(res_x - cx) <= 2
    assert abs(res_y - cy) <= 2


def test_mouse_controller_click_primitives():
    """Verifies click primitives return success and truthful feedback."""
    mc = MouseController()
    cx, cy = mc.screen_w // 2, mc.screen_h // 2

    # Single click
    res = mc.click_at(cx, cy, click_type="single", duration=0.01)
    assert res["status"] == "success"
    assert res["command"] == "click"
    assert "Clicked" in res["spoken_feedback"]

    # Double click
    res_double = mc.click_at(cx, cy, click_type="double", duration=0.01)
    assert res_double["status"] == "success"
    assert "Double-clicked" in res_double["spoken_feedback"]

    # Right click
    res_right = mc.click_at(cx, cy, click_type="right", duration=0.01)
    assert res_right["status"] == "success"
    assert "Right-clicked" in res_right["spoken_feedback"]


# ---------------------------------------------------------------------------
# 2. Landmark and OCR Element Locating
# ---------------------------------------------------------------------------
def test_landmark_element_resolution():
    """Verifies common UI landmarks (center, top left, etc.) are resolved."""
    mc = MouseController()
    for landmark in ["center", "top left", "top right", "bottom center"]:
        found, info, msg = mc.find_element_on_screen(landmark)
        assert found is True, f"Landmark '{landmark}' should be found"
        assert info is not None
        assert "pixel_x" in info and "pixel_y" in info
        assert info["match_type"] == "landmark"


def test_ocr_block_matching():
    """Verifies OCR text matching identifies buttons and extracts pixel coordinates."""
    mc = MouseController()
    mock_ocr = [
        {"text": "Submit", "x": 0.5, "y": 0.6, "w": 0.1, "h": 0.04, "pixel_x": 700, "pixel_y": 500},
        {"text": "Cancel", "x": 0.4, "y": 0.6, "w": 0.1, "h": 0.04, "pixel_x": 550, "pixel_y": 500},
        {"text": "Search YouTube", "x": 0.3, "y": 0.1, "w": 0.4, "h": 0.05, "pixel_x": 600, "pixel_y": 80},
    ]

    # Exact match
    found, info, msg = mc.find_element_on_screen("Submit", ocr_blocks=mock_ocr)
    assert found is True
    assert info["text"] == "Submit"
    assert info["pixel_x"] == 700
    assert info["pixel_y"] == 500

    # Case-insensitive with filler word
    found2, info2, msg2 = mc.find_element_on_screen("the cancel button", ocr_blocks=mock_ocr)
    assert found2 is True
    assert info2["text"] == "Cancel"
    assert info2["pixel_x"] == 550

    # Partial / substring match
    found3, info3, msg3 = mc.find_element_on_screen("search", ocr_blocks=mock_ocr)
    assert found3 is True
    assert "Search" in info3["text"]


def test_truthful_failure_when_element_missing():
    """Verifies that missing elements report failure truthfully without blind clicks."""
    mc = MouseController()
    mock_ocr = [
        {"text": "File", "x": 0.1, "y": 0.05, "w": 0.05, "h": 0.02, "pixel_x": 100, "pixel_y": 50},
        {"text": "Edit", "x": 0.15, "y": 0.05, "w": 0.05, "h": 0.02, "pixel_x": 150, "pixel_y": 50},
    ]
    res = mc.click_element(target_element="NonExistentButton999", ocr_blocks=mock_ocr)
    assert res["status"] == "failed"
    assert "Could not find button or element 'NonExistentButton999' on screen" in res["spoken_feedback"]


# ---------------------------------------------------------------------------
# 3. Intent Classification for Click and Mouse Commands
# ---------------------------------------------------------------------------
def test_click_element_intent_parsing():
    """Tests various natural language phrasings for button clicking."""
    cases = [
        ("Click the Submit button", IntentType.CLICK_ELEMENT, "submit", "single"),
        ("Click on Cancel", IntentType.CLICK_ELEMENT, "cancel", "single"),
        ("Click Settings", IntentType.CLICK_ELEMENT, "settings", "single"),
        ("Please click the Save button", IntentType.CLICK_ELEMENT, "save", "single"),
        ("Double click on project.pdf", IntentType.CLICK_ELEMENT, "project.pdf", "double"),
        ("Double click here", IntentType.CLICK_ELEMENT, None, "double"),
        ("Right click on the image", IntentType.CLICK_ELEMENT, "image", "right"),
        ("Right click", IntentType.CLICK_ELEMENT, None, "right"),
        ("Move mouse to the center", IntentType.MOUSE_CONTROL, "center", "single"),
        ("Move the cursor to top right", IntentType.MOUSE_CONTROL, "top right", "single"),
        ("Click at 500, 300", IntentType.CLICK_ELEMENT, None, "single"),
        ("Click", IntentType.CLICK_ELEMENT, None, "single"),
        ("Click here", IntentType.CLICK_ELEMENT, None, "single"),
    ]
    for text, exp_intent, exp_target, exp_type in cases:
        result = classify_intent(text)
        assert result.intent == exp_intent, f"Failed intent for '{text}': got {result.intent}, expected {exp_intent}"
        if exp_target is not None:
            assert result.target_element == exp_target, f"Failed target for '{text}': got '{result.target_element}', expected '{exp_target}'"
        if exp_type is not None:
            assert result.click_type == exp_type, f"Failed click_type for '{text}': got '{result.click_type}', expected '{exp_type}'"


def test_conversational_questions_not_misidentified_as_clicks():
    """Ensures questions about clicking are routed to conversational AI, not mouse clicks."""
    questions = [
        "How do I click a button in Python?",
        "What is the difference between single click and double click?",
        "Explain how mouse events work in JavaScript",
    ]
    for q in questions:
        res = classify_intent(q)
        assert res.intent == IntentType.CONVERSATIONAL_AI, f"'{q}' should be conversational AI, got {res.intent}"


# ---------------------------------------------------------------------------
# 4. Multi-Step Tasks with Button Clicking
# ---------------------------------------------------------------------------
def test_multistep_task_button_clicking_chain():
    """Verifies that multi-step compound commands with click clauses decompose and execute properly."""
    instruction = "Open Notes and click the New Note button"
    res = classify_intent(instruction)
    assert res.intent == IntentType.MULTISTEP_TASK

    steps = task_engine._local_decompose_task(instruction)
    assert len(steps) >= 2
    # Step 1: Open Notes
    assert "Notes" in (steps[0].get("target_app") or steps[0].get("description"))
    # Step 2: Click button
    assert steps[1].get("action_type") in ("click_element", "click_button")
    assert steps[1].get("target_ui_element") == "New Note"


# ---------------------------------------------------------------------------
# 5. REST API Integration
# ---------------------------------------------------------------------------
def test_api_status_reports_mouse_controller(client):
    """Verifies /api/status exposes mouse_controller_available."""
    resp = client.get("/api/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("mouse_controller_available") is True


def test_api_chat_click_element(client):
    """Verifies sending a click command to /api/chat triggers click_element action."""
    resp = client.post("/api/chat", json={"message": "Click center of screen"})
    assert resp.status_code == 200
    data = resp.json()
    action = data.get("action", {})
    assert action.get("command") in ("click_element", "click")
    assert "spoken_response" in data
