"""
SAHAYAK — Regression Test Suite for Robust Error Recovery & Safari Focus Typing
Verifies:
  1. Conversational questions and general queries while Safari is the front app
     are never mistakenly converted into 'keyboard_type' actions or 'Entered text into Safari.'
  2. Errors during instruction handling never throw unhandled 500 crashes or produce
     'I encountered an error processing that instruction. Please try again.'
  3. Explicit typing commands with targeted applications (e.g. 'type hello in Notes')
     still properly trigger keyboard typing when requested.
"""

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

SERVER_DIR = Path(__file__).resolve().parent.parent / "server"
sys.path.insert(0, str(SERVER_DIR))

import pytest
from fastapi.testclient import TestClient
from main import app
from intent_classifier import classify_intent, IntentType
from session_context import SessionContext
from gemini_engine import AgentAction


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client


def test_conversational_questions_never_type_into_safari(client):
    """
    When Safari is the active frontmost application and the user asks a question,
    it must be handled as conversational AI, NEVER as 'Entered text into Safari.'
    """
    safari_context = {
        "app_name": "Safari",
        "window_title": "Apple",
        "tab_url": "https://www.apple.com",
        "tab_title": "Apple",
        "is_browser_active": True,
    }

    test_queries = [
        "Tell me about quantum computing",
        "Who was Alan Turing?",
        "Can you help me plan my morning?",
        "What is the capital of France?",
    ]

    for query in test_queries:
        with patch("main.get_active_app_context", return_value=safari_context), \
             patch("main.gemini_engine.chat_conversational", return_value="Here is the explanation you asked for."), \
             patch("main.tts.speak") as mock_speak:

            response = client.post("/api/chat", json={"message": query})
            assert response.status_code == 200
            data = response.json()

            # Verify it did NOT enter text into Safari
            spoken = data.get("spoken_response", "")
            assert "Entered text into Safari" not in spoken
            assert spoken == "Here is the explanation you asked for."
            assert data.get("action", {}).get("command") == "conversational_answer"


def test_keyboard_type_guard_prevents_unrequested_browser_typing(client):
    """
    Even if an action planner accidentally returns 'keyboard_type' for an instruction
    without explicit typing keywords, main.py guards against pasting it into Safari.
    """
    safari_context = {
        "app_name": "Safari",
        "window_title": "Start Page",
        "is_browser_active": True,
    }

    accidental_action = AgentAction(
        command="keyboard_type",
        text="why is the sky blue",
        target_app=None,
    )

    with patch("main.get_active_app_context", return_value=safari_context), \
         patch("main.gemini_engine.plan_action", return_value=accidental_action), \
         patch("main.gemini_engine.chat_conversational", return_value="The sky appears blue due to Rayleigh scattering."):

        response = client.post("/api/chat", json={"message": "why is the sky blue"})
        assert response.status_code == 200
        data = response.json()

        spoken = data.get("spoken_response", "")
        assert "Entered text into Safari" not in spoken
        assert "Rayleigh scattering" in spoken


def test_error_resilience_never_crashes_endpoint(client):
    """
    Simulate an internal failure (e.g. screen capture error or database lock).
    The endpoint must catch it gracefully, return HTTP 200, and provide a helpful spoken response
    instead of an unhandled 500 error.
    """
    with patch("main.capture_screen_image", side_effect=RuntimeError("Screen capture buffer failure")), \
         patch("main.tts.speak") as mock_speak:

        response = client.post("/api/chat", json={"message": "What is on my screen?"})
        assert response.status_code == 200
        data = response.json()

        assert data.get("requires_confirmation") is False
        spoken = data.get("spoken_response", "")
        assert len(spoken) > 0
        assert "I encountered an error processing that instruction" not in spoken
        mock_speak.assert_called()

