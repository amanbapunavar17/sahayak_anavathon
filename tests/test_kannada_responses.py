"""
SAHAYAK — Multilingual Support Test Suite (Kannada)
Verifies:
  1. Intent classification recognizes language-switch requests (e.g. 'switch to Kannada', 'talk in Kannada').
  2. SessionContext and TTSEngine track the active language and map 'kn' to the macOS Kannada voice identifier ('Soumya').
  3. tts.speak receives the Kannada voice identifier ('Soumya').
  4. AgentAction schema includes the optional 'language' field for downstream modules.
  5. Gemini system prompt injects:
     "You are a multilingual assistant. Respond only in Kannada unless the user asks for a different language."
     and returns Kannada text.
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
from tts_engine import tts, resolve_voice, VOICE_MAP
from gemini_engine import gemini_engine, AgentAction


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def reset_language():
    """Ensure each test starts with a clean language state."""
    SessionContext.set_language("en-US")
    tts.set_language("en-US")
    yield
    SessionContext.set_language("en-US")
    tts.set_language("en-US")


def test_language_switch_intent_classification():
    """Verify that language switch requests are cleanly recognized."""
    r1 = classify_intent("Switch to Kannada")
    assert r1.intent == IntentType.LANGUAGE_SWITCH
    assert r1.language == "kn"

    r2 = classify_intent("Please talk in Kannada")
    assert r2.intent == IntentType.LANGUAGE_SWITCH
    assert r2.language == "kn"

    r3 = classify_intent("switch to English")
    assert r3.intent == IntentType.LANGUAGE_SWITCH
    assert r3.language == "en-US"


def test_tts_kannada_voice_mapping():
    """Verify that Kannada language code resolves to the macOS Kannada voice ('Soumya')."""
    voice = resolve_voice(language="kn")
    assert voice == "Soumya"
    assert VOICE_MAP.get("kn") == "Soumya"
    assert VOICE_MAP.get("kannada") == "Soumya"

    tts.set_language("kn")
    assert tts.get_voice_for_language() == "Soumya"


def test_tts_speak_receives_kannada_voice():
    """Verify that tts.speak queues messages using the Kannada voice identifier."""
    with patch.object(tts, "_speech_queue") as mock_queue:
        tts.speak("ನಮಸ್ಕಾರ", language="kn")
        mock_queue.put.assert_called_once()
        args, _ = mock_queue.put.call_args
        clean_text, voice, rate = args[0]
        assert clean_text == "ನಮಸ್ಕಾರ"
        assert voice == "Soumya"


def test_agent_action_has_optional_language_field():
    """Verify AgentAction schema supports the optional 'language' field."""
    action = AgentAction(
        command="conversational_answer",
        text="ನಮಸ್ಕಾರ",
        language="kn",
    )
    assert action.language == "kn"
    assert action.command == "conversational_answer"

    # Default should be None
    default_action = AgentAction(command="describe")
    assert default_action.language is None


def test_language_switch_via_chat_endpoint(client):
    """
    Simulate user requesting 'switch to Kannada' via /api/chat.
    Verify:
      - Endpoint returns 200 with intent 'language_switch'.
      - SessionContext language is updated to 'kn'.
      - Spoken feedback is issued with Kannada voice.
    """
    with patch.object(tts, "speak") as mock_speak:
        response = client.post("/api/chat", json={"message": "Switch to Kannada"})
        assert response.status_code == 200
        data = response.json()

        assert data.get("intent") == "language_switch"
        assert SessionContext.get_language() == "kn"
        assert "ಕನ್ನಡ" in data.get("spoken_response", "")

        mock_speak.assert_called_once()
        _, kwargs = mock_speak.call_args
        assert kwargs.get("language") == "kn"


import asyncio


def test_gemini_prompt_injection_and_kannada_response():
    """
    Verify that when Kannada language is active:
      - Gemini prompt includes the system instruction:
        'You are a multilingual assistant. Respond only in Kannada unless the user asks for a different language.'
      - Mocked Gemini returns Kannada text.
    """
    SessionContext.set_language("kn")
    kannada_reply = "ನಮಸ್ಕಾರ! ನಾನು ನಿಮಗೆ ಹೇಗೆ ಸಹಾಯ ಮಾಡಬಹುದು?"

    captured_config = {}

    def mock_call(contents, config=None):
        if config and hasattr(config, "system_instruction"):
            captured_config["system_instruction"] = config.system_instruction
        return kannada_reply

    with patch.object(gemini_engine, "is_available", return_value=True), \
         patch.object(gemini_engine, "_call_with_failover", side_effect=mock_call):

        result = asyncio.run(gemini_engine.chat_conversational("ಹಲೋ"))

        assert result == kannada_reply
        sys_instr = captured_config.get("system_instruction", "")
        expected_fragment = "You are a multilingual assistant. Respond only in Kannada unless the user asks for a different language."
        assert expected_fragment in sys_instr


def test_kannada_punctuation_cleaned_for_tts_speech():
    """
    CRITICAL: Verify that Kannada text with question marks ('?', '??')
    has those punctuation marks stripped before being spoken aloud, so
    the macOS 'say' command with Soumya never speaks 'question mark question mark'.
    """
    from tts_engine import sanitize_speech_text

    raw_text = "ಖಂಡಿತ! ನಾನು ನಿಮಗೆ ಹೇಗೆ ಸಹಾಯ ಮಾಡಲಿ? ನಿಮ್ಮ ಆದೇಶವನ್ನು ತಿಳಿಸಿ??"
    cleaned = sanitize_speech_text(raw_text, voice="Soumya")

    assert "?" not in cleaned
    assert "!" not in cleaned
    assert "??" not in cleaned
    assert "ಖಂಡಿತ" in cleaned
    assert "ಸಹಾಯ ಮಾಡಲಿ" in cleaned
    assert "ತಿಳಿಸಿ" in cleaned

    # Also test mixed markdown and punctuation
    raw_md = "**ಹಲೋ**! ಇದು `ಪರೀಕ್ಷೆ`?? ಹೇಗೆ ಸಹಾಯ ಮಾಡಲಿ?"
    cleaned_md = sanitize_speech_text(raw_md, voice="Soumya")
    assert "**" not in cleaned_md
    assert "`" not in cleaned_md
    assert "?" not in cleaned_md
    assert "ಹಲೋ" in cleaned_md
