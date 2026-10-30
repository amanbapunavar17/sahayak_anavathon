"""
SAHAYAK — Global Wake Word & Floating Assistant Test Suite
Tests:
  1. Wake word phrase detection ("HELLO SAHAY", "HELLO SAHAYAK", "hey sahay").
  2. False activation suppression on normal speech.
  3. Inline command extraction after wake word.
  4. WakeWordService pause, resume, and status diagnostics.
  5. Floating companion popup endpoint (/popup).
  6. Active application and browser context sensing.
"""

import sys
from pathlib import Path

# Add project root and server to sys.path
_PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_DIR))
_SERVER_DIR = _PROJECT_DIR / "server"
sys.path.insert(0, str(_SERVER_DIR))

import pytest
from fastapi.testclient import TestClient
from server.main import app
from server.screen_engine import get_active_app_context
from client.wake_word_service import (
    is_wake_word_in_text,
    extract_command_after_wake_word,
    WakeWordService,
)


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client


def test_wake_word_phrase_detection():
    """Verify detection of 'HELLO SAHAY' and expected natural variants."""
    positive_phrases = [
        "HELLO SAHAY",
        "Hello Sahay",
        "hello sahayak",
        "HEY SAHAY",
        "hey sahayak, what is on my screen?",
        "hi sahay, open browser",
        "Hello Sahayak, explain AI",
    ]
    for p in positive_phrases:
        assert is_wake_word_in_text(p) is True, f"Failed to detect wake word in: '{p}'"
    print("\n[PASS] All 7 wake word variants detected cleanly.")


def test_wake_word_negative_suppression():
    """Verify everyday speech does not falsely activate the wake word."""
    negative_phrases = [
        "Good morning everyone",
        "Can you help me with this presentation?",
        "Let's check the weather in San Francisco",
        "The project deadline is tomorrow",
        "How do you do",
    ]
    for p in negative_phrases:
        assert is_wake_word_in_text(p) is False, f"False positive on: '{p}'"
    print("\n[PASS] False positive suppression verified on 5 normal speech phrases.")


def test_inline_command_extraction():
    """Verify command trailing the wake word is extracted accurately."""
    phrase = "Hello Sahay, open YouTube and search for Python tutorials"
    extracted = extract_command_after_wake_word(phrase)
    assert "open youtube" in extracted.lower()
    assert "python" in extracted.lower()
    print(f"\n[PASS] Inline command extracted: '{extracted}'")


def test_wake_word_service_lifecycle():
    """Verify WakeWordService start, pause, resume, and trigger controls."""
    service = WakeWordService()
    # Initial
    assert service.is_running is False
    assert service.is_paused is False

    # Pause and resume
    service.pause()
    assert service.is_paused is True
    assert service.get_status()["paused"] is True

    service.resume()
    assert service.is_paused is False

    # Trigger wake callback
    triggered = []
    service.on_wake = lambda: triggered.append(True)
    service.trigger_wake()
    assert len(triggered) == 1
    assert service.total_triggers == 1
    print("\n[PASS] WakeWordService lifecycle and pause/resume verified.")


def test_popup_companion_endpoint(client):
    """Verify /popup serves the accessible floating assistant HTML companion."""
    res = client.get("/popup")
    assert res.status_code == 200
    assert "SAHAYAK" in res.text
    assert "Floating Assistant" in res.text or "HELLO SAHAY" in res.text
    print("\n[PASS] /popup endpoint verified.")


def test_active_app_and_browser_context():
    """Verify get_active_app_context returns rich window and browser properties."""
    ctx = get_active_app_context()
    assert "app_name" in ctx
    assert "is_browser_active" in ctx
    assert "is_document_active" in ctx
    assert "is_finder_active" in ctx
    print(f"\n[PASS] Active context sensed: App={ctx.get('app_name')}, BrowserActive={ctx.get('is_browser_active')}")

