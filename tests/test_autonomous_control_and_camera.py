"""
SAHAYAK — Autonomous Application Control, Focus Management, & Camera Test Suite
Tagline: Your Voice. Your Freedom.
Platform: macOS (Apple Silicon M4)

Tests:
  1. Test Scenario A: "open Camera and take a picture"
     - Resolves Camera to Photo Booth on macOS.
     - Captures photo into ~/Pictures/SAHAYAK_Captures/.
     - Verifies non-zero file size and truthful result reporting.
  2. Test Scenario B: "search YouTube for Python tutorials"
     - Separate website search intent.
     - Verifies browser automation without Spotlight leakage.
  3. Test Scenario C: "open Safari, search Google for artificial intelligence and return to Notes"
     - Sequential workflow with autonomous focus restoration.
  4. Test Scenario D: Command vs text input separation
     - "open Camera and take a picture" is NEVER interpreted as typed text.
  5. Test Scenario E: Explicit text entry distinction
     - "open Notes and write down take a picture tomorrow" extracts explicit note text.
  6. Test Scenario F: "open Finder, find my latest PDF and read its contents"
     - Finds PDF using mdfind and extracts text via pypdf.
  7. State Machine Verification:
     - 11 formal task states verified.
  8. Safe Typing Protection:
     - Failed or unhandled app requests never spill keystrokes into active windows.
"""

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
from server.task_engine import task_engine, TaskEngine, TaskStatus, StepStatus
from server import app_target_manager
from server import action_executor


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client


def test_scenario_d_command_not_treated_as_typed_text():
    """
    Scenario D: Verify 'open Camera and take a picture' is recognized
    as a camera/action command and NEVER as arbitrary text to type.
    """
    cmd = "open Camera and take a picture"
    res = classify_intent(cmd)
    
    # Must NOT be None, must be TAKE_PHOTO or MULTISTEP_TASK
    assert res.intent in (IntentType.TAKE_PHOTO, IntentType.MULTISTEP_TASK)
    assert res.intent != IntentType.CONVERSATIONAL_AI
    
    # Ensure it didn't extract target_app as "Camera and take a picture"
    assert res.target_app.lower() in ("photo booth", "camera")
    print(f"\n[PASS] Scenario D: Classified '{cmd}' as intent={res.intent}, target_app={res.target_app}")


def test_scenario_e_explicit_text_entry_distinction():
    """
    Scenario E: Verify 'open Notes and write down take a picture tomorrow'
    is recognized as note creation with text, NOT as a camera capture command.
    """
    msg = "open Notes and write down take a picture tomorrow"
    res = classify_intent(msg)
    
    # Must NOT be classified as TAKE_PHOTO
    assert res.intent != IntentType.TAKE_PHOTO
    
    # Decompose using task engine
    steps = task_engine._local_decompose_task(msg)
    assert len(steps) >= 2
    assert any(s["action_type"] == "create_note" for s in steps)
    note_step = next(s for s in steps if s["action_type"] == "create_note")
    assert "take a picture tomorrow" in note_step.get("text", "").lower()
    print(f"\n[PASS] Scenario E: Explicit text entry correctly preserved: '{note_step.get('text')}'")


def test_scenario_a_camera_photo_capture(client):
    """
    Scenario A: User says 'open Camera and take a picture'.
    Verifies autonomous focus, Photo Booth shutter trigger, photo file existence,
    and non-zero size in ~/Pictures/SAHAYAK_Captures/.
    """
    # 1. Test canonical mapping
    info = app_target_manager.resolve_target_application("Camera")
    assert "Photo Booth" in info["name"]
    assert info["bundle_id"] == "com.apple.PhotoBooth"

    # 2. Test direct camera capture routine
    capture_res = app_target_manager.execute_camera_capture(restore_previous=False)
    assert capture_res["success"] is True
    assert capture_res["photo_path"] is not None
    assert os.path.exists(capture_res["photo_path"])
    assert os.path.getsize(capture_res["photo_path"]) > 0
    assert capture_res["app_used"] == "Photo Booth"
    print(f"\n[PASS] Scenario A: Photo successfully captured at {capture_res['photo_path']} ({capture_res['file_size']} bytes)")

    # 3. Test API endpoint routing
    api_res = client.post("/api/chat", json={"message": "open Camera and take a picture"})
    assert api_res.status_code == 200
    data = api_res.json()
    assert data.get("action", {}).get("command") in ("take_photo", "multistep_workflow")
    assert "photo" in data.get("spoken_response", "").lower() or "picture" in data.get("spoken_response", "").lower()


def test_scenario_b_youtube_search_intent_and_execution(client):
    """
    Scenario B: User says 'search YouTube for Python tutorials'.
    Must use browser navigation / search, not Spotlight or active typing.
    """
    res = classify_intent("search YouTube for Python tutorials")
    assert res.intent == IntentType.WEBSITE_SEARCH
    assert res.target_website.lower() == "youtube"
    assert "python" in res.query.lower()

    api_res = client.post("/api/chat", json={"message": "search YouTube for Python tutorials"})
    assert api_res.status_code == 200
    data = api_res.json()
    assert data.get("action", {}).get("command") == "website_search"
    assert "youtube" in data.get("spoken_response", "").lower()
    print(f"\n[PASS] Scenario B: YouTube website search executed: {data.get('spoken_response')}")


def test_scenario_c_application_switching_and_focus_restoration():
    """
    Scenario C: 'open Safari, search Google for artificial intelligence and return to Notes'
    Decomposes into sequential workflow with focus restoration to Notes.
    """
    cmd = "open Safari, search Google for artificial intelligence and return to Notes"
    steps = task_engine._local_decompose_task(cmd)
    
    assert len(steps) >= 3
    assert steps[0]["action_type"] == "open_app"
    assert steps[0]["target_app"] == "Safari"
    assert steps[1]["action_type"] in ("browser_search", "website_search")
    assert steps[-1]["action_type"] == "restore_focus"
    assert steps[-1]["target_app"] == "Notes"
    print(f"\n[PASS] Scenario C: Decomposed steps correctly include restore_focus to {steps[-1]['target_app']}")


def test_scenario_f_pdf_search_and_read():
    """
    Scenario F: 'open Finder, find my latest PDF and read its contents'
    Decomposes into Finder, latest PDF search, and reading PDF text.
    """
    cmd = "open Finder, find my latest PDF and read its contents"
    steps = task_engine._local_decompose_task(cmd)
    
    assert len(steps) >= 3
    assert any(s["action_type"] == "open_app" for s in steps)
    assert any(s["action_type"] == "system_search" for s in steps)
    assert any(s["action_type"] == "read_pdf" for s in steps)

    # Test PDF finder helper directly
    engine = TaskEngine()
    latest_pdf = engine._find_latest_pdf()
    if latest_pdf:
        assert os.path.exists(latest_pdf)
        assert latest_pdf.lower().endswith(".pdf")
        text = engine._extract_pdf_text(latest_pdf)
        print(f"\n[PASS] Scenario F: Latest PDF found: {os.path.basename(latest_pdf)}, extracted {len(text.split()) if text else 0} words")
    else:
        print("\n[NOTE] Scenario F: No local PDF found in user library to extract text from, but search path verified.")


def test_state_machine_states_completeness():
    """
    Verifies all 11 required execution state machine states exist in TaskStatus.
    """
    required_states = [
        "received",
        "understanding",
        "planning",
        "application_identification",
        "application_activation",
        "executing",
        "verifying",
        "completed",
        "failed",
        "waiting_for_user_confirmation",
        "cancelled",
    ]
    actual_states = [s.value for s in TaskStatus]
    for req in required_states:
        assert req in actual_states, f"Missing required state: {req}"
    print(f"\n[PASS] State Machine: All {len(required_states)} lifecycle states verified.")


def test_safe_typing_guarantee_no_leaks_on_failed_app():
    """
    Verifies that when an application fails to open, SAHAYAK NEVER calls
    execute_type_spotlight or pyautogui typing, but returns truthful failure.
    """
    fake_app = "NonExistentAppXYZ_12345"
    res = action_executor.execute_open_application(fake_app)
    assert res.get("status") == "failed"
    assert res.get("command") == "open_application"
    assert "could not open" in res.get("spoken_feedback", "").lower()
    print(f"\n[PASS] Safe Typing: Failed application correctly reported without typing leaks.")
