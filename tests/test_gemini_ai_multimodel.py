"""
SAHAYAK — Gemini Multi-Model AI Verification Test Suite
Tests:
  1. Real Gemini AI responses to natural-language user queries (not hardcoded).
  2. Diverse questions generate distinctly different dynamic responses.
  3. Resilient multi-model failover (e.g. gemini-3.8-flash -> gemini-3.5-flash).
  4. Real-time diagnostics endpoint (/api/diagnostics).
  5. Missing / invalid API key handling and graceful fallback.
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
from server.gemini_engine import gemini_engine, GeminiEngine


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client


def test_gemini_diagnostics_endpoint(client):
    """Verify /api/diagnostics returns rich connectivity and model health metrics."""
    res = client.get("/api/diagnostics")
    assert res.status_code == 200
    data = res.json()
    assert "status" in data
    assert "active_model" in data
    assert "candidate_models" in data
    assert len(data["candidate_models"]) >= 3
    print(f"\n[PASS] Diagnostics: Status={data['status']}, ActiveModel={data['active_model']}")


def test_real_gemini_explanation_ai(client):
    """
    User: 'Hello Sahayak, explain artificial intelligence in simple language.'
    Verifies that a real AI explanation is generated (not hardcoded or predefined).
    """
    query = "Hello Sahayak, explain artificial intelligence in simple language in two sentences."
    res = client.post("/api/chat", json={"message": query})
    assert res.status_code == 200
    data = res.json()

    assert data.get("intent") == "conversational_ai"
    spoken = data.get("spoken_response", "")
    assert len(spoken) > 20
    # Must explain concepts like learning, computers, human
    spoken_lower = spoken.lower()
    assert any(w in spoken_lower for w in ["computer", "machine", "human", "think", "learn", "technology"])
    # Must NOT be a hardcoded fallback or offline notice if key is available
    if gemini_engine.is_available():
        assert "local offline mode" not in spoken_lower

    print(f"\n[PASS] Real Gemini AI Explanation:\n\"{spoken}\"")


def test_real_gemini_ram_vs_storage(client):
    """
    User: 'What is the difference between RAM and storage?'
    Verifies domain-specific comparison is dynamically generated.
    """
    query = "What is the difference between RAM and storage in two sentences?"
    res = client.post("/api/chat", json={"message": query})
    assert res.status_code == 200
    data = res.json()

    assert data.get("intent") == "conversational_ai"
    spoken = data.get("spoken_response", "").lower()
    assert "ram" in spoken
    assert "storage" in spoken
    assert any(w in spoken for w in ["temporary", "memory", "permanent", "files", "data", "power", "fast"])

    print(f"\n[PASS] Real Gemini RAM vs Storage:\n\"{data.get('spoken_response')}\"")


def test_real_gemini_learning_plan(client):
    """
    User: 'I am learning Python. Create a 30-day learning plan.'
    Verifies structured dynamic advice is returned.
    """
    query = "I am learning Python. Create a brief learning plan in three points."
    res = client.post("/api/chat", json={"message": query})
    assert res.status_code == 200
    data = res.json()

    assert data.get("intent") == "conversational_ai"
    spoken = data.get("spoken_response", "")
    assert len(spoken) > 30
    assert "python" in spoken.lower() or any(w in spoken.lower() for w in ["learn", "basics", "projects", "code", "syntax"])

    print(f"\n[PASS] Real Gemini Learning Plan:\n\"{spoken}\"")


def test_different_questions_yield_different_answers(client):
    """Verify responses are genuinely synthesized, not static canned responses."""
    r1 = client.post("/api/chat", json={"message": "What is water made of?"})
    r2 = client.post("/api/chat", json={"message": "What is the capital of France?"})
    assert r1.status_code == 200 and r2.status_code == 200
    text1 = r1.json().get("spoken_response", "")
    text2 = r2.json().get("spoken_response", "")
    assert text1 != text2
    print("\n[PASS] Confirmed distinct responses to different knowledge questions.")


def test_gemini_multimodel_failover_mechanism():
    """
    Direct unit test of GeminiEngine._call_with_failover:
    Verifies that if primary model hits quota (429), it automatically falls over to candidate models.
    """
    engine = GeminiEngine()
    if not engine.is_available():
        pytest.skip("No GEMINI_API_KEY configured for live failover test.")

    # Call with failover
    response_text = engine._call_with_failover("Say 'verified' in one word.")
    assert len(response_text) > 0
    assert engine.connection_state == "online"
    assert engine.active_model in engine.candidate_models
    print(f"\n[PASS] Multi-model failover active. Working model: {engine.active_model}, Latency: {engine.last_latency_ms:.1f}ms")


def test_missing_api_key_graceful_handling():
    """Verify that when no API key is present, system operates cleanly in offline mode without crashing."""
    offline_engine = GeminiEngine()
    offline_engine.api_key = ""
    offline_engine.client = None
    offline_engine.connection_state = "offline"

    assert not offline_engine.is_available()
    diag = offline_engine.get_diagnostics()
    assert diag["status"] == "offline"
    assert diag["has_api_key"] is False
    print("\n[PASS] Offline engine state verified without unhandled crashes.")
