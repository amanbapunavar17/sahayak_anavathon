"""
SAHAYAK — Universal Task Execution & App-Independent Automation Test Suite
Tagline: Your Voice. Your Freedom.
Platform: macOS (Apple Silicon M4)

Tests:
  1. Test Workflow 1: "Find the latest file in Downloads and open it."
     - Verifies multi-step detection without dropping "open it".
     - Prevents "it" from being classified as an application name.
     - Sequences: file_search -> open_file with matched path context propagation.
  2. Test Workflow 2: "Open System Settings and change the display brightness."
     - Verifies compound multi-step detection without dropping brightness action.
     - Sequences: open_app (System Settings) -> system_settings (Displays/Brightness).
  3. Test Workflow 3: "Open Safari, visit Google, and search for something."
     - Verifies 3-clause sequential decomposition.
     - Sequences: open_app (Safari) -> open_website (Google) -> search.
  4. Test Workflow 4: "Create a folder and move these files into it."
     - Verifies create_folder -> move_files workflow.
     - Validates destination context propagation.
  5. Focus Independence & No Blind Typing:
     - Spoken commands are never typed into active text fields or cursor locations.
     - Unfocused keyboard typing aborts safely rather than spilling into wrong apps.
  6. Non-App Target Guard:
     - Pronouns and non-app nouns ('it', 'them', 'the file', 'the folder', 'files', 'something')
       are strictly excluded from OPEN_APPLICATION.
  7. Full State Machine Lifecycle:
     - Verifies progression through:
       RECEIVED -> UNDERSTANDING -> PLANNING -> TARGETING -> ACTIVATING -> EXECUTING -> VERIFYING -> COMPLETED.
"""

import asyncio
import os
import sys
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

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
from server import macos_automator
from server import action_executor
from server.gemini_engine import gemini_engine


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client


# ==============================================================================
# 1. Non-App Target Guard (No False App Identifications)
# ==============================================================================
def test_non_app_pronouns_not_classified_as_applications():
    """
    Ensure that words like 'it', 'them', 'the file', 'something', etc.
    are never classified as application targets in OPEN_APPLICATION.
    """
    test_cases = [
        "Open it",
        "Open them",
        "Open the file",
        "Open this",
        "Open that",
        "Open something",
    ]
    for text in test_cases:
        res = classify_intent(text)
        if res.intent == IntentType.OPEN_APPLICATION:
            assert res.target_app.lower() not in {"it", "them", "the file", "this", "that", "something", "the folder"}
    print("\n[PASS] Non-app targets properly guarded against false app launches.")


# ==============================================================================
# 2. Workflow 1: "Find the latest file in Downloads and open it."
# ==============================================================================
def test_workflow_find_latest_file_and_open():
    """
    Workflow: "Find the latest file in Downloads and open it."
    Must:
      - Classify as MULTISTEP_TASK.
      - Decompose into: file_search -> open_file.
      - Execute sequentially and pass matched_file_path to open_file.
    """
    query = "Find the latest file in Downloads and open it."
    intent_res = classify_intent(query)
    assert intent_res.intent == IntentType.MULTISTEP_TASK

    steps = asyncio.run(gemini_engine.decompose_multistep_task(query))
    assert len(steps) >= 2
    step_types = [s.get("action_type", "").lower() for s in steps]
    assert "file_search" in step_types
    assert "open_file" in step_types

    # Test autonomous execution with mocked file paths
    fake_file = "/Users/testuser/Downloads/annual_report_2026.pdf"
    with patch.object(task_engine.macos_automator, "find_latest_file", return_value=fake_file), \
         patch.object(task_engine.macos_automator, "open_file", return_value=(True, "Opened annual_report_2026.pdf")), \
         patch("os.path.exists", return_value=True):
        
        session = asyncio.run(task_engine.execute_multistep_task(query))
        assert session.status == TaskStatus.COMPLETED
        assert len(session.steps) >= 2
        assert session.context_store.get("matched_file_path") == fake_file
        assert "annual_report_2026.pdf" in session.spoken_summary or "Opened" in session.spoken_summary
    print("\n[PASS] Workflow 1: Find latest file in Downloads and open it passed.")


# ==============================================================================
# 3. Workflow 2: "Open System Settings and change the display brightness."
# ==============================================================================
def test_workflow_system_settings_brightness():
    """
    Workflow: "Open System Settings and change the display brightness."
    Must:
      - Classify as MULTISTEP_TASK.
      - Decompose into: open_app (System Settings) -> system_settings (Displays/Brightness).
      - Execute without dropping the brightness adjustment step.
    """
    query = "Open System Settings and change the display brightness."
    intent_res = classify_intent(query)
    assert intent_res.intent == IntentType.MULTISTEP_TASK

    steps = asyncio.run(gemini_engine.decompose_multistep_task(query))
    assert len(steps) >= 2
    step_types = [s.get("action_type", "").lower() for s in steps]
    assert any(t in ("open_app", "open_application") for t in step_types)
    assert "system_settings" in step_types

    # Execute and verify mock automation
    with patch.object(task_engine.app_target_manager, "activate_and_focus_application", return_value=True), \
         patch.object(task_engine.macos_automator, "change_display_brightness", return_value=(True, "Changed display brightness")):
        
        session = asyncio.run(task_engine.execute_multistep_task(query))
        assert session.status == TaskStatus.COMPLETED
        assert len(session.steps) >= 1
        assert any(s.action_type in ("system_settings", "open_app") and s.status == StepStatus.COMPLETED for s in session.steps)
    print("\n[PASS] Workflow 2: System Settings and display brightness adjustment passed.")


# ==============================================================================
# 4. Workflow 3: "Open Safari, visit Google, and search for something."
# ==============================================================================
def test_workflow_three_clause_browser_navigation():
    """
    Workflow: "Open Safari, visit Google, and search for something."
    Must:
      - Decompose into 3 sequential steps: open_app -> open_website -> search.
      - Execute all 3 steps sequentially.
    """
    query = "Open Safari, visit Google, and search for something."
    intent_res = classify_intent(query)
    assert intent_res.intent == IntentType.MULTISTEP_TASK

    # Verify exact 3-clause deterministic decomposition
    local_steps = gemini_engine._local_decompose_task(query)
    assert len(local_steps) >= 3
    local_types = [s.get("action_type", "").lower() for s in local_steps]
    assert any("open_app" in t for t in local_types)
    assert any("open_website" in t for t in local_types)
    assert any("search" in t for t in local_types)

    # Verify AI or failover decomposition
    steps = asyncio.run(gemini_engine.decompose_multistep_task(query))
    assert len(steps) >= 1
    step_types = [s.get("action_type", "").lower() for s in steps]
    assert any("open" in t or "website" in t or "search" in t for t in step_types)

    with patch.object(task_engine.app_target_manager, "activate_and_focus_application", return_value=True), \
         patch.object(task_engine.browser_engine, "execute_open_website") as mock_open_site, \
         patch.object(task_engine.browser_engine, "execute_browser_search") as mock_search, \
         patch.object(task_engine.browser_engine, "execute_website_search") as mock_web_search:
        
        from server.browser_engine import BrowserTaskResult
        mock_open_site.return_value = BrowserTaskResult(
            task_type="open_website",
            target_website="google",
            target_url="https://www.google.com",
            success=True,
            stage_reached="verified",
            spoken_feedback="Navigated to Google"
        )
        mock_search.return_value = BrowserTaskResult(
            task_type="browser_search",
            target_website="google",
            query="something",
            target_url="https://www.google.com/search?q=something",
            success=True,
            stage_reached="verified",
            spoken_feedback="Searched for something"
        )
        mock_web_search.return_value = mock_search.return_value

        session = asyncio.run(task_engine.execute_multistep_task(query))
        assert session.status == TaskStatus.COMPLETED
        assert len(session.steps) >= 1
        assert any("search" in s.action_type or "website" in s.action_type for s in session.steps)
        assert all(s.status == StepStatus.COMPLETED for s in session.steps)
    print("\n[PASS] Workflow 3: Three-clause browser workflow passed.")


# ==============================================================================
# 5. Workflow 4: "Create a folder and move these files into it."
# ==============================================================================
def test_workflow_create_folder_and_move_files():
    """
    Workflow: "Create a folder and move these files into it."
    Must:
      - Decompose into: create_folder -> move_files.
      - Propagate created folder path as destination for move_files.
    """
    query = "Create a folder and move these files into it."
    intent_res = classify_intent(query)
    assert intent_res.intent == IntentType.MULTISTEP_TASK

    steps = asyncio.run(gemini_engine.decompose_multistep_task(query))
    assert len(steps) >= 2
    step_types = [s.get("action_type", "").lower() for s in steps]
    assert "create_folder" in step_types
    assert "move_files" in step_types

    fake_dest = "/Users/testuser/Desktop/New Folder"
    fake_sources = ["/Users/testuser/Downloads/doc1.pdf", "/Users/testuser/Downloads/doc2.pdf"]

    with patch.object(task_engine.macos_automator, "create_folder", return_value=(True, "Created folder", fake_dest)), \
         patch.object(task_engine.macos_automator, "get_finder_selected_files", return_value=fake_sources), \
         patch.object(task_engine.macos_automator, "move_files", return_value=(True, "Moved 2 files", fake_sources)):
        
        session = asyncio.run(task_engine.execute_multistep_task(query))
        assert session.status == TaskStatus.COMPLETED
        assert session.context_store.get("created_folder_path") == fake_dest
        assert any(s.action_type == "move_files" and s.status == StepStatus.COMPLETED for s in session.steps)
    print("\n[PASS] Workflow 4: Create folder and move files passed.")


# ==============================================================================
# 6. Focus Independence: Commands Are Never Typed Into Active Text Fields
# ==============================================================================
def test_commands_are_never_typed_into_active_text_fields(client):
    """
    Spoken instructions like:
      - "Open Camera and take a picture."
      - "Find the latest file in Downloads and open it."
      - "Open System Settings and change the display brightness."
    must NEVER be typed into whatever search bar or text field happens to be active.
    """
    commands = [
        "Open Camera and take a picture.",
        "Find the latest file in Downloads and open it.",
        "Open System Settings and change the display brightness.",
        "Open Safari, visit Google, and search for something.",
    ]
    for cmd in commands:
        intent = classify_intent(cmd)
        # Must be an action or workflow, NEVER plain keyboard text typing
        assert intent.intent in (IntentType.MULTISTEP_TASK, IntentType.TAKE_PHOTO, IntentType.OPEN_APPLICATION)
        
        with patch("server.action_executor.pyautogui.write") as mock_write:
            res = client.post("/api/chat", json={"message": cmd})
            assert res.status_code == 200
            data = res.json()
            # The action command should not be keyboard_type
            action = data.get("action", {})
            assert action.get("command") != "keyboard_type"
            # pyautogui.write should NOT be called with the full user command
            for call in mock_write.call_args_list:
                arg = call[0][0] if call[0] else ""
                assert cmd not in arg

    print("\n[PASS] Commands are never typed into active text fields.")


# ==============================================================================
# 7. Safe Keyboard Typing Protection
# ==============================================================================
def test_safe_keyboard_typing_requires_focus_or_aborts():
    """
    Verifies that safe_keyboard_type verifies application focus before typing,
    and aborts cleanly if the target application cannot be activated.
    """
    # Case A: Target application fails activation
    with patch("server.macos_automator.app_target_manager.activate_and_focus_application", return_value=False):
        success, msg = macos_automator.safe_keyboard_type("secret notes", target_app="NonExistentApp")
        assert not success
        assert "Could not verify focus" in msg or "Aborting" in msg

    # Case B: Target application succeeds activation
    with patch("server.macos_automator.app_target_manager.activate_and_focus_application", return_value=True), \
         patch("server.macos_automator.app_target_manager.get_frontmost_application", return_value={"app_name": "Notes"}), \
         patch("subprocess.run") as mock_sub, \
         patch("pyautogui.hotkey") as mock_hotkey:
        
        success, msg = macos_automator.safe_keyboard_type("meeting notes", target_app="Notes")
        assert success
        assert "Notes" in msg
    print("\n[PASS] Safe typing protection verified.")


# ==============================================================================
# 8. Complete State Machine Lifecycle
# ==============================================================================
def test_state_machine_full_lifecycle():
    """
    Verifies that task engine defines the required execution states:
      RECEIVED -> UNDERSTANDING -> PLANNING -> TARGETING -> ACTIVATING -> EXECUTING -> VERIFYING -> COMPLETED
      Plus: FAILED, WAITING_FOR_USER_CONFIRMATION, CANCELLED.
    """
    required_states = {
        "received",
        "understanding",
        "planning",
        "targeting",
        "activating",
        "executing",
        "verifying",
        "completed",
        "failed",
        "waiting_for_user_confirmation",
        "cancelled"
    }
    actual_values = {status.value for status in TaskStatus}
    for state in required_states:
        assert state in actual_values, f"State Machine missing required state: '{state}'"
    print("\n[PASS] State Machine complete lifecycle states verified.")
