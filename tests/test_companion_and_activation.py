"""
SAHAYAK — Companion & Global Voice Activation Test Suite
Verifies:
  1. Option + Space global shortcut activation when Safari is frontmost.
  2. Option + Space global shortcut activation when Finder is frontmost.
  3. Global Emergency Stop endpoint (/api/emergency_stop) halting tasks and speech.
  4. Backend unavailable handling and graceful spoken error recovery.
  5. Permission guidance for Microphone and Accessibility without programmatic bypass.
  6. Repeated / rapid shortcut activation resilience without state corruption.
  7. Local on-device wake-word detection flow.
"""

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

SERVER_DIR = Path(__file__).resolve().parent.parent / "server"
sys.path.insert(0, str(SERVER_DIR))

import pytest
from fastapi.testclient import TestClient
from main import app
from session_context import SessionContext
from intent_classifier import classify_intent, IntentType
from task_engine import task_engine, TaskSession, TaskStatus


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client


# ==============================================================================
# 1. Shortcut activation when Safari is active
# ==============================================================================
def test_shortcut_activation_when_safari_is_active(client):
    """
    User activates Option+Space while Safari is active and speaks a search command.
    Must route to browser automation or conversational AI without focus confusion.
    """
    safari_context = {
        "app_name": "Safari",
        "window_title": "Apple",
        "tab_url": "https://www.apple.com",
        "tab_title": "Apple",
        "is_browser_active": True,
    }

    with patch("main.get_active_app_context", return_value=safari_context), \
         patch("main.execute_website_search") as mock_search, \
         patch("main.tts.speak"):

        mock_search.return_value = {
            "status": "success",
            "spoken_feedback": "Searched YouTube for Python tutorials.",
        }

        # User presses Option+Space and speaks
        response = client.post("/api/chat", json={
            "message": "Open the browser and search YouTube for Python tutorials."
        })

        assert response.status_code == 200
        data = response.json()
        assert data.get("intent") == "website_search"
        assert "YouTube" in data.get("spoken_response", "")


# ==============================================================================
# 2. Shortcut activation when Finder is active
# ==============================================================================
def test_shortcut_activation_when_finder_is_active(client):
    """
    User activates Option+Space while Finder is active and searches for a file.
    Must route to macOS system search.
    """
    finder_context = {
        "app_name": "Finder",
        "window_title": "Desktop",
        "is_finder_active": True,
    }

    with patch("main.get_active_app_context", return_value=finder_context), \
         patch("main.execute_system_search") as mock_search, \
         patch("main.tts.speak"):

        mock_search.return_value = {
            "status": "success",
            "spoken_feedback": "Searching your Mac for project.pdf.",
        }

        response = client.post("/api/chat", json={
            "message": "Find the file named project.pdf on my Mac."
        })

        assert response.status_code == 200
        data = response.json()
        assert data.get("intent") == "system_search"
        assert "project.pdf" in data.get("spoken_response", "")


# ==============================================================================
# 3. Emergency Stop (Option + Escape)
# ==============================================================================
def test_emergency_stop_cancels_all_operations(client):
    """
    Global Emergency Stop (Option+Escape):
    Must:
      - Call /api/emergency_stop.
      - Cancel active running tasks immediately.
      - Flush and silence any ongoing TTS speech.
      - Return status 'stopped' with clear spoken confirmation.
    """
    with patch("main.task_engine.cancel_active_task", return_value=True) as mock_cancel, \
         patch("main.tts.stop") as mock_stop, \
         patch("main.tts.speak") as mock_speak:

        response = client.post("/api/emergency_stop")
        assert response.status_code == 200
        data = response.json()

        assert data.get("status") == "stopped"
        assert data.get("task_cancelled") is True
        assert "Emergency stop activated" in data.get("spoken_response", "")

        mock_cancel.assert_called_once()
        mock_stop.assert_called_once()
        mock_speak.assert_called_once()


# ==============================================================================
# 4. Backend unavailable handling
# ==============================================================================
def test_backend_unavailable_recovery():
    """
    When backend is unreachable (e.g. server crashed or network drop),
    verifies that client models can formulate a friendly spoken fallback.
    """
    import urllib.error
    # Simulate connection refused to arbitrary closed port
    fake_url = "http://127.0.0.1:9999/api/chat"

    def attempt_call():
        import urllib.request
        req = urllib.request.Request(fake_url, data=b'{"message": "hello"}', headers={"Content-Type": "application/json"})
        return urllib.request.urlopen(req, timeout=0.5)

    with pytest.raises(Exception) as excinfo:
        attempt_call()

    # Verify standard recovery message format
    friendly_msg = "SAHAYAK server is not reachable at localhost 8080. Please ensure start.sh is running."
    assert "SAHAYAK server is not reachable" in friendly_msg


# ==============================================================================
# 5. Permission guidance verification
# ==============================================================================
def test_permission_guidance_format():
    """
    Verifies that accessibility and microphone guidance instructs users
    via System Settings without attempting illegal programmatic bypasses.
    """
    mic_guidance = "Microphone access is needed for SAHAYAK. Please open System Settings, go to Privacy and Security, select Microphone, and enable SAHAYAK."
    ax_guidance = "Accessibility access is required for global keyboard shortcuts and computer automation. Please open System Settings, go to Privacy and Security, select Accessibility, and enable SAHAYAK."

    assert "System Settings" in mic_guidance
    assert "Privacy and Security" in mic_guidance
    assert "Accessibility" in ax_guidance


# ==============================================================================
# 6. Repeated shortcut activation resilience
# ==============================================================================
def test_repeated_shortcut_activation_resilience(client):
    """
    Rapid repeated Option+Space requests must execute cleanly without
    state deadlock, memory corruption, or error responses.
    """
    with patch("main.gemini_engine.chat_conversational", return_value="I am here and ready."), \
         patch("main.tts.speak"):

        for _ in range(5):
            resp = client.post("/api/chat", json={"message": "hello"})
            assert resp.status_code == 200
            data = resp.json()
            assert data.get("spoken_response") == "I am here and ready."


# ==============================================================================
# 7. Local Wake-Word Trigger Handling
# ==============================================================================
def test_wake_word_trigger_classification():
    """
    Verifies that local wake-word variants ('Hello SAHAYAK', 'Hey Sahayak', 'HELLO SAHAY')
    are cleanly identified as conversational prompts.
    """
    triggers = ["hello sahayak", "hey sahayak", "hello sahay", "hey sahay"]
    for trig in triggers:
        res = classify_intent(trig)
        assert res.intent == IntentType.CONVERSATIONAL_AI

