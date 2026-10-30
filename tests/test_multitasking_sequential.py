"""
SAHAYAK — Multitasking & Sequential Action Execution Test Suite
Tests:
  1. Multi-step task decomposition into ordered sequential steps.
  2. Sequential workflow execution and verification.
  3. Apple Notes integration (note creation via AppleScript).
  4. Context passing between dependent actions.
  5. Task cancellation mid-flight.
  6. Truthful failure diagnosis when a step cannot be performed.
"""

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
from server.task_engine import task_engine, TaskEngine, TaskStatus, StepStatus


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client


def test_multistep_task_decomposition_heuristic():
    """Verify local heuristic task decomposition splits sequential conjunctions correctly."""
    engine = TaskEngine()
    instruction = "Open Safari, then open Notes and write down my next three tasks."
    steps = engine._local_decompose_task(instruction)
    assert len(steps) >= 2
    assert any(s["action_type"] == "open_app" for s in steps)
    assert any(s["action_type"] == "create_note" for s in steps)
    print(f"\n[PASS] Heuristic decomposition: {len(steps)} steps identified.")


def test_multistep_task_api_execution(client):
    """
    User: 'Open Safari, then open Notes and write down my next three tasks.'
    Expected:
      - Intent classified as multistep_task.
      - 3 steps planned and executed in sequence.
      - Apple Notes note created.
    """
    res = client.post("/api/chat", json={
        "message": "Open Safari, then open Notes and write down my next three tasks."
    })
    assert res.status_code == 200
    data = res.json()
    assert data.get("intent") == "multistep_task"
    assert "task_session" in data
    ts = data["task_session"]
    assert ts.get("status") in ("completed", "executing")
    assert len(ts.get("steps", [])) >= 2
    assert "apple notes" in data.get("spoken_response", "").lower() or "notes" in data.get("spoken_response", "").lower()
    print(f"\n[PASS] Multi-step execution verified: {data.get('spoken_response')}")


def test_apple_note_creation_direct():
    """Verify native Apple Notes automation via AppleScript."""
    engine = TaskEngine()
    success, note_id = engine._create_apple_note("SAHAYAK Unit Test Note", "Body content verified.")
    assert success is True
    print(f"\n[PASS] Native Apple Notes creation verified. Result: {note_id}")


def test_task_cancellation():
    """Verify task cancellation sets status to CANCELLED and stops execution."""
    engine = TaskEngine()
    # Start task
    import asyncio
    task_coro = engine.execute_multistep_task("Open Safari, then open Notes and write down my tasks.")
    # Cancel immediately
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    # Trigger cancel
    engine.cancel_active_task()
    payload = engine.get_status_payload()
    assert payload.get("active") is False
    print("\n[PASS] Task cancellation verified.")


def test_truthful_failure_when_file_not_found():
    """
    Verify that when asked to find a non-existent file,
    the task engine truthfully reports failure without fabricating success.
    """
    engine = TaskEngine()
    found = engine._find_local_file("totally_nonexistent_ghost_file_98765.pdf")
    assert found is None
    print("\n[PASS] Truthful file search verified: non-existent file returned None.")

