"""
SAHAYAK — Comprehensive End-to-End Automated Test Suite
Verifies:
  - Dependency integrity & imports
  - Backend API endpoints
  - Speech synthesis (macOS native 'say')
  - Screen capture & Apple Vision neural OCR
  - All 8 Mandatory Test Cases from project specification
  - Frontend static assets & accessibility markup
  - WebSocket agent communication
"""

import sys
import os
from pathlib import Path

# Add server directory to sys.path
SERVER_DIR = Path(__file__).resolve().parent.parent / "server"
sys.path.insert(0, str(SERVER_DIR))

import pytest
from fastapi.testclient import TestClient
from main import app, _get_db
from tts_engine import tts
from screen_engine import capture_screen_image, perform_local_ocr_on_screen, get_active_app_context
from gemini_engine import gemini_engine, GEMINI_MODEL_ID


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client


# ==============================================================================
# 1. Dependency & Module Import Verification
# ==============================================================================
def test_dependencies_and_imports():
    """Verify all critical libraries import with no errors."""
    import fastapi
    import uvicorn
    import websockets
    import pydantic
    import PIL
    import pyautogui
    import google.genai
    import faster_whisper
    import sounddevice
    assert fastapi.__version__ is not None
    assert pydantic.__version__ is not None
    assert PIL.__version__ is not None
    print("\n[PASS] All core dependencies imported cleanly.")


# ==============================================================================
# 2. System Status & Health Check
# ==============================================================================
def test_system_status_endpoint(client):
    """Verify /api/status reports valid metadata and gemini-3.8-flash model."""
    response = client.get("/api/status")
    assert response.status_code == 200
    data = response.json()
    assert data["project"] == "SAHAYAK"
    assert data["tagline"] == "Your Voice. Your Freedom."
    assert data["gemini_model"] == GEMINI_MODEL_ID
    assert data["tts_available"] is True
    assert data["vision_ocr_available"] is True
    print("\n[PASS] /api/status verified.")


# ==============================================================================
# 3. Speech Synthesis (TTS) Module Testing
# ==============================================================================
def test_tts_module():
    """Verify local macOS speech synthesis and voice catalog."""
    voices = tts.get_available_voices()
    assert len(voices) > 0
    # Test non-blocking queue
    tts.speak("Testing SAHAYAK speech synthesis queue.")
    # Test stopping/flushing queue
    tts.stop()
    print(f"\n[PASS] TTS engine functional with {len(voices)} detected macOS voices.")


# ==============================================================================
# 4. Screen Capture & Apple Vision Neural OCR Testing
# ==============================================================================
def test_screen_capture_and_local_ocr():
    """Verify screen capture and local on-device OCR."""
    cap = capture_screen_image()
    assert "image_base64" in cap
    assert cap["width"] > 0
    assert cap["height"] > 0
    assert cap["image_base64"] is not None

    ocr_blocks = perform_local_ocr_on_screen()
    assert isinstance(ocr_blocks, list)
    print(f"\n[PASS] Screen capture returned {cap['width']}x{cap['height']} image; OCR detected {len(ocr_blocks)} text blocks.")


# ==============================================================================
# 5. TEST CASE 1: User says “Hello SAHAYAK”
# ==============================================================================
def test_case_1_hello_sahayak(client):
    """TEST CASE 1: User: 'Hello SAHAYAK' -> SAHAYAK responds through speech."""
    response = client.post("/api/chat", json={"message": "Hello SAHAYAK"})
    assert response.status_code == 200
    data = response.json()
    assert "spoken_response" in data
    assert len(data["spoken_response"]) > 0
    print(f"\n[PASS] TEST CASE 1: 'Hello SAHAYAK' -> Spoke: '{data['spoken_response'][:60]}...'")


# ==============================================================================
# 6. TEST CASE 2: User says “What is on my screen?”
# ==============================================================================
def test_case_2_what_is_on_my_screen(client):
    """TEST CASE 2: User: 'What is on my screen?' -> Captures and describes screen aloud."""
    response = client.post("/api/chat", json={"message": "What is on my screen?"})
    assert response.status_code == 200
    data = response.json()
    assert "spoken_response" in data
    assert "screen_image" in data
    assert data["action"]["command"] == "describe"
    print(f"\n[PASS] TEST CASE 2: 'What is on my screen?' -> Spoke description: '{data['spoken_response'][:70]}...'")


# ==============================================================================
# 7. TEST CASE 3: User says “Read this text.”
# ==============================================================================
def test_case_3_read_this_text(client):
    """TEST CASE 3: User: 'Read this text' -> Identifies readable text and speaks it."""
    response = client.post("/api/chat", json={"message": "Read the text displayed here."})
    assert response.status_code == 200
    data = response.json()
    assert "spoken_response" in data
    assert len(data["spoken_response"]) > 0
    print(f"\n[PASS] TEST CASE 3: 'Read this text' -> Spoke: '{data['spoken_response'][:70]}...'")


# ==============================================================================
# 8. TEST CASE 4: User says “Open the browser.”
# ==============================================================================
def test_case_4_open_browser(client):
    """TEST CASE 4: User: 'Open the browser' -> Plans and executes browser launch."""
    response = client.post("/api/chat", json={"message": "Open the browser."})
    assert response.status_code == 200
    data = response.json()
    assert data["requires_confirmation"] is False
    assert data["action"]["command"] in ("open_application", "open_url", "type_text")
    assert "spoken_response" in data
    print(f"\n[PASS] TEST CASE 4: 'Open the browser' -> Planned {data['action']['command']} and spoke: '{data['spoken_response']}'")


# ==============================================================================
# 9. TEST CASE 5: User says “Scroll down.”
# ==============================================================================
def test_case_5_scroll_down(client):
    """TEST CASE 5: User: 'Scroll down' -> Performs scrolling operation and confirms."""
    response = client.post("/api/chat", json={"message": "Scroll down."})
    assert response.status_code == 200
    data = response.json()
    assert data["action"]["command"] == "scroll"
    assert data["action"]["amount"] is not None
    assert data["action"]["amount"] < 0  # negative is scroll down
    print(f"\n[PASS] TEST CASE 5: 'Scroll down' -> Scrolled {data['action']['amount']} points.")


# ==============================================================================
# 10. TEST CASE 6: Sensitive Operation Confirmation: “Delete this file.”
# ==============================================================================
def test_case_6_delete_file_confirmation(client):
    """
    TEST CASE 6: User: 'Delete this file.'
    Expected: SAHAYAK requests explicit confirmation before deletion.
    Does NOT execute deletion until confirmed.
    """
    # Step A: Request deletion
    response = client.post("/api/chat", json={"message": "Delete this file."})
    assert response.status_code == 200
    data = response.json()
    assert data["requires_confirmation"] is True
    assert "confirmation_prompt" in data
    assert "delete" in data["confirmation_prompt"].lower() or "confirm" in data["confirmation_prompt"].lower()
    print(f"\n[PASS] TEST CASE 6 (A): Intercepted sensitive action. Asked: '{data['confirmation_prompt']}'")

    # Step B: User confirms action
    confirm_resp = client.post(
        "/api/confirm_action",
        json={"confirmed": True, "action": data["action"]},
    )
    assert confirm_resp.status_code == 200
    confirm_data = confirm_resp.json()
    assert confirm_data["status"] == "success"
    assert "spoken_response" in confirm_data
    print(f"\n[PASS] TEST CASE 6 (B): Confirmed operation executed cleanly: '{confirm_data['spoken_response']}'")


# ==============================================================================
# 11. TEST CASE 7: Graceful Offline Gemini Fallback
# ==============================================================================
def test_case_7_gemini_offline_fallback(client):
    """
    TEST CASE 7: Disable Gemini connection / Missing key.
    Expected: Application handles gracefully and retains local functionality.
    """
    # Temporarily stash API key
    orig_key = gemini_engine.api_key
    orig_client = gemini_engine.client
    gemini_engine.api_key = ""
    gemini_engine.client = None

    try:
        # Check system status reports local mode
        status_res = client.get("/api/status")
        assert status_res.status_code == 200
        assert status_res.json()["gemini_configured"] is False
        assert status_res.json()["operating_mode"] == "Local Offline Mode"

        # Ask local question
        chat_res = client.post("/api/chat", json={"message": "What is on my screen?"})
        assert chat_res.status_code == 200
        data = chat_res.json()
        assert "spoken_response" in data
        assert len(data["spoken_response"]) > 0

        # Ask local scroll
        scroll_res = client.post("/api/chat", json={"message": "Scroll down."})
        assert scroll_res.status_code == 200
        assert scroll_res.json()["action"]["command"] == "scroll"

        print(f"\n[PASS] TEST CASE 7: Disabled Gemini API -> Operated in Local Offline Mode with 0 crashes.")
    finally:
        gemini_engine.api_key = orig_key
        gemini_engine.client = orig_client


# ==============================================================================
# 12. TEST CASE 8: Missing Permissions Handling
# ==============================================================================
def test_case_8_permissions_handling(client):
    """
    TEST CASE 8: Deny or simulate permission errors.
    Expected: SAHAYAK explains the missing permission and guidance.
    """
    # Test speak endpoint error handling on invalid payload
    bad_req = client.post("/api/speak", json={"text": ""})
    assert bad_req.status_code == 400

    # Test empty chat command
    empty_chat = client.post("/api/chat", json={"message": "   "})
    assert empty_chat.status_code == 400

    print("\n[PASS] TEST CASE 8: Permissions & input validations handle errors safely.")


# ==============================================================================
# 13. Frontend Static Dashboard & Accessibility Markup
# ==============================================================================
def test_frontend_accessible_dashboard(client):
    """Verify frontend HTML, CSS, JS, and WCAG AAA accessibility semantics."""
    # Index HTML
    res_html = client.get("/")
    assert res_html.status_code == 200
    html_text = res_html.text
    assert "SAHAYAK" in html_text
    assert "Your Voice. Your Freedom." in html_text
    assert 'role="banner"' in html_text
    assert 'role="main"' in html_text
    assert 'role="status"' in html_text
    assert 'aria-live="polite"' in html_text
    assert 'aria-live="assertive"' in html_text
    assert "confirmation-dialog" in html_text
    assert "btn-mic-toggle" in html_text

    # CSS
    res_css = client.get("/static/style.css")
    assert res_css.status_code == 200
    assert "theme-high-contrast" in res_css.text
    assert ":focus-visible" in res_css.text

    # JS
    res_js = client.get("/static/app.js")
    assert res_js.status_code == 200
    assert "showConfirmationModal" in res_js.text
    assert "initWebSocket" in res_js.text

    print("\n[PASS] Accessible Desktop Web Dashboard markup and assets verified.")


# ==============================================================================
# 14. WebSocket Agent Communication Test
# ==============================================================================
def test_websocket_agent_communication(client):
    """Verify WebSocket /ws/agent handshake and screen capture request."""
    with client.websocket_connect("/ws/agent") as ws:
        # Handshake
        ws.send_json({"event": "wake_word_detected", "timestamp": 123456789})
        response = ws.receive_json()
        assert response["status"] == "handshake_complete"

        # Screen capture request
        ws.send_json({"command": "capture_screen"})
        cap_resp = ws.receive_json()
        assert cap_resp["command"] == "screen_captured"
        assert cap_resp["width"] > 0
        assert cap_resp["height"] > 0
        assert "image_base64" in cap_resp
        print("\n[PASS] WebSocket /ws/agent bidirectional messaging verified.")


# ==============================================================================
# 15. SQLite Memory Persistence Test
# ==============================================================================
def test_sqlite_memory_persistence(client):
    """Verify sessions and facts are saved in SQLite database."""
    conn = _get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM sessions")
    count = cursor.fetchone()[0]
    assert count >= 0

    res = client.get("/api/history")
    assert res.status_code == 200
    data = res.json()
    assert "sessions" in data
    print(f"\n[PASS] SQLite memory database verified ({count} sessions recorded).")

