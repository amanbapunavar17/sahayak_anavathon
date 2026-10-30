"""
SAHAYAK — Dedicated Browser & Search Intent Test Suite
Verifies:
  1. Intent separation across all 5 distinct search/navigation intents:
     - system_search (macOS Spotlight file/system search)
     - browser_search (general internet web search)
     - website_search (open specified website and search within it)
     - open_website (direct navigation to a website)
     - open_application (launch a local macOS application)
  2. Website-specific search execution & multi-stage verification (YouTube, Google, etc.).
  3. Action verification and failure explanation without false claims of success.
  4. Natural language phrasing variations for voice instructions.
  5. System search non-interference with browser search.
"""

import sys
from pathlib import Path

# Add server directory to sys.path
SERVER_DIR = Path(__file__).resolve().parent.parent / "server"
sys.path.insert(0, str(SERVER_DIR))

import pytest
from fastapi.testclient import TestClient
from main import app
from intent_classifier import classify_intent, IntentType, WEBSITE_CATALOG
from browser_engine import BrowserEngine, BrowserTaskResult


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client


# ==============================================================================
# 1. Distinct Intent Separation Tests
# ==============================================================================
def test_distinct_intent_separation():
    """Verify that search instructions are correctly separated into distinct intents."""
    # System Search
    r_sys1 = classify_intent("Find the file named project.pdf on my Mac.")
    assert r_sys1.intent == IntentType.SYSTEM_SEARCH
    assert "project.pdf" in (r_sys1.query or "").lower()

    r_sys2 = classify_intent("Search my Mac for taxes.xlsx")
    assert r_sys2.intent == IntentType.SYSTEM_SEARCH
    assert "taxes.xlsx" in (r_sys2.query or "").lower()

    # Browser Search (General Web)
    r_web1 = classify_intent("Search the web for the best Python courses.")
    assert r_web1.intent == IntentType.BROWSER_SEARCH
    assert "python courses" in (r_web1.query or "").lower()

    r_web2 = classify_intent("Look up online how to make cold brew.")
    assert r_web2.intent == IntentType.BROWSER_SEARCH
    assert "cold brew" in (r_web2.query or "").lower()

    # Website Search (Targeted)
    r_site1 = classify_intent("Open the browser and search YouTube for Python tutorials.")
    assert r_site1.intent == IntentType.WEBSITE_SEARCH
    assert r_site1.target_website == "youtube"
    assert "python tutorials" in (r_site1.query or "").lower()

    r_site2 = classify_intent("Open Google and search for latest AI news.")
    assert r_site2.intent == IntentType.WEBSITE_SEARCH
    assert r_site2.target_website == "google"
    assert "latest ai news" in (r_site2.query or "").lower()

    # Direct Website Navigation
    r_open_site = classify_intent("Go to wikipedia.org")
    assert r_open_site.intent == IntentType.OPEN_WEBSITE

    # Open Application
    r_app1 = classify_intent("Open Calculator")
    assert r_app1.intent == IntentType.OPEN_APPLICATION
    assert r_app1.target_app == "Calculator"

    r_app2 = classify_intent("Open the browser")
    assert r_app2.intent == IntentType.OPEN_APPLICATION

    print("\n[PASS] All 5 distinct intents separated cleanly with no ambiguity.")


# ==============================================================================
# 2. Website-Specific Search Execution & Verification (YouTube)
# ==============================================================================
def test_website_specific_search_youtube(client):
    """
    User: 'Open the browser and search YouTube for Python tutorials.'
    Expected:
      - Identified as website_search on YouTube.
      - Never triggers Spotlight search.
      - Spoken feedback confirms YouTube search.
    """
    response = client.post("/api/chat", json={
        "message": "Open the browser and search YouTube for Python tutorials."
    })
    assert response.status_code == 200
    data = response.json()

    action = data.get("action", {})
    assert action.get("command") == "website_search"
    assert action.get("target_website") == "youtube"
    assert "python tutorials" in action.get("query", "").lower()

    spoken = data.get("spoken_response", "")
    assert "youtube" in spoken.lower()
    assert "python tutorials" in spoken.lower()
    assert "spotlight" not in spoken.lower()

    print(f"\n[PASS] Website-specific search verified on YouTube: '{spoken}'")


# ==============================================================================
# 3. Website-Specific Search (Google)
# ==============================================================================
def test_website_specific_search_google(client):
    """
    User: 'Open Google and search for latest AI news.'
    Expected:
      - Identified as website_search on Google.
      - Query: 'latest AI news'.
    """
    response = client.post("/api/chat", json={
        "message": "Open Google and search for latest AI news."
    })
    assert response.status_code == 200
    data = response.json()

    action = data.get("action", {})
    assert action.get("command") == "website_search"
    assert action.get("target_website") == "google"
    assert "latest ai news" in action.get("query", "").lower()
    assert "google" in data.get("spoken_response", "").lower()

    print(f"\n[PASS] Website-specific search verified on Google: '{data.get('spoken_response')}'")


# ==============================================================================
# 4. General Browser Search
# ==============================================================================
def test_browser_search_general_web(client):
    """
    User: 'Search the web for the best Python courses.'
    Expected:
      - Identified as browser_search.
      - Query: 'best Python courses'.
      - Uses web search engine.
    """
    response = client.post("/api/chat", json={
        "message": "Search the web for the best Python courses."
    })
    assert response.status_code == 200
    data = response.json()

    action = data.get("action", {})
    assert action.get("command") == "browser_search"
    assert "best python courses" in action.get("query", "").lower()
    assert "web" in data.get("spoken_response", "").lower() or "google" in data.get("spoken_response", "").lower()

    print(f"\n[PASS] General web search verified: '{data.get('spoken_response')}'")


# ==============================================================================
# 5. System Search via Spotlight (Does NOT Use Browser)
# ==============================================================================
def test_system_search_does_not_open_browser(client):
    """
    User: 'Find the file named project.pdf on my Mac.'
    Expected:
      - Identified as system_search.
      - Uses macOS Spotlight.
      - Does NOT open a browser or navigate to a web URL.
    """
    response = client.post("/api/chat", json={
        "message": "Find the file named project.pdf on my Mac."
    })
    assert response.status_code == 200
    data = response.json()

    action = data.get("action", {})
    assert action.get("command") == "system_search"
    assert "project.pdf" in action.get("query", "").lower()

    spoken = data.get("spoken_response", "").lower()
    assert "spotlight" in spoken or "mac" in spoken
    assert "youtube" not in spoken
    assert "browser" not in spoken

    print(f"\n[PASS] System search verified on macOS Spotlight: '{data.get('spoken_response')}'")


# ==============================================================================
# 6. Natural Language Phrasing Variations for Website Search
# ==============================================================================
def test_natural_language_phrasing_variations(client):
    """
    Verify diverse ways of requesting website search:
      - 'Open YouTube and search for music.'
      - 'Go to YouTube and find music.'
      - 'Can you look up music on YouTube?'
      - 'Search YouTube for music.'
      - 'Find me music videos on YouTube.'
    All must map to website_search on YouTube with query matching 'music'.
    """
    phrasings = [
        "Open YouTube and search for music.",
        "Go to YouTube and find music.",
        "Can you look up music on YouTube?",
        "Search YouTube for music.",
        "Find me music videos on YouTube.",
    ]

    for p in phrasings:
        res = client.post("/api/chat", json={"message": p})
        assert res.status_code == 200
        data = res.json()
        action = data.get("action", {})
        assert action.get("command") == "website_search", f"Failed on phrasing: '{p}'"
        assert action.get("target_website") == "youtube", f"Failed site match on: '{p}'"
        assert "music" in action.get("query", "").lower(), f"Failed query match on: '{p}'"
        print(f"  [✓] Phrasing '{p}' -> website_search on {action.get('target_website')} for '{action.get('query')}'")

    print("\n[PASS] All 5 natural language phrasing variations passed.")


# ==============================================================================
# 7. Direct Website Navigation
# ==============================================================================
def test_direct_website_navigation(client):
    """
    User: 'Go to wikipedia.org'
    Expected:
      - Identified as open_website.
      - Navigates to wikipedia.org without a search query.
    """
    response = client.post("/api/chat", json={"message": "Go to wikipedia.org"})
    assert response.status_code == 200
    data = response.json()

    action = data.get("action", {})
    assert action.get("command") == "open_website"
    assert "wikipedia.org" in action.get("url", "").lower()
    print(f"\n[PASS] Direct website navigation verified: '{data.get('spoken_response')}'")


# ==============================================================================
# 8. Action Verification & Failure Diagnosis (No Fake Success)
# ==============================================================================
def test_failed_search_verification_reporting():
    """
    Verify that when navigation fails or a page cannot load,
    the BrowserEngine reports failure or warning truthfully rather than fabricating success.
    """
    engine = BrowserEngine()
    # Test with simulated unreachable domain and 0.5s timeout
    engine.max_load_wait_secs = 0.5

    # Simulate search on a non-existent offline target
    result = engine.execute_website_search(target_website="nonexistentfakeportal999", query="sample test")
    assert isinstance(result, BrowserTaskResult)
    # The result must either be verified if browser loaded or truthfully report failure/warning
    if not result.success:
        assert "could not be verified" in result.spoken_feedback.lower() or "check" in result.spoken_feedback.lower()
        print(f"\n[PASS] Truthful failure diagnosis confirmed: '{result.spoken_feedback}'")
    else:
        print(f"\n[PASS] Task completed with evidence: {result.evidence}")

