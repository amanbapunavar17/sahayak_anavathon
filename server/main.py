"""
SAHAYAK — OS Accessibility Agent Server
Tagline: Your Voice. Your Freedom.

Voice-first AI-powered computer accessibility assistant designed
primarily for blind and low-vision individuals.

Features:
  - Accessible Desktop Web Dashboard (WCAG 2.1 AAA, ARIA Live, High Contrast)
  - REST & WebSocket APIs for voice and computer control
  - Google Gemini 3.8 Flash multimodal reasoning
  - Free local Speech-to-Text (faster-whisper)
  - Free local Text-to-Speech (macOS native 'say' / NSSpeechSynthesizer)
  - Free local on-device OCR (Apple Silicon Vision Neural Engine)
  - Sensitive operation confirmation guardrail
  - SQLite persistent memory (~/.sahayak/memory.db)
"""

import asyncio
import base64
import json
import logging
import os
import sqlite3
import threading
import typing
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

# Load project environment variables
load_dotenv()

# Import SAHAYAK core engines
from tts_engine import tts
from screen_engine import (
    capture_screen_image,
    perform_local_ocr_on_screen,
    get_active_app_context,
    annotate_screenshot_ruler,
    get_logical_screen_size,
)
from action_executor import (
    execute_click,
    execute_scroll,
    execute_type_spotlight,
    execute_keyboard_type,
    execute_hotkey,
    execute_open_url,
    execute_sensitive_action,
    execute_system_search,
    execute_browser_search,
    execute_website_search,
    execute_open_website,
    execute_open_application,
)
from intent_classifier import classify_intent, IntentType
from gemini_engine import (
    gemini_engine,
    AgentAction,
    GEMINI_MODEL_ID,
)
from stt_engine import stt

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("sahayak-server")

app = FastAPI(
    title="SAHAYAK Accessibility Assistant",
    description="Voice-first computer accessibility assistant for blind and low-vision users",
    version="3.0.0",
)

# Enable CORS for local web interactions
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount Static Files (Accessible Dashboard)
STATIC_DIR = Path(__file__).parent / "static"
if not STATIC_DIR.exists():
    STATIC_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# ---------------------------------------------------------------------------
# Persistent Memory — SQLite at data/memory.db (inside project directory)
# ---------------------------------------------------------------------------
_PROJECT_DIR = Path(__file__).resolve().parent
_MEMORY_DB_PATH = Path(os.getenv("SAHAYAK_DB_PATH", str(_PROJECT_DIR / "data" / "memory.db")))
_db_lock = threading.Lock()
_memory_db: typing.Optional[sqlite3.Connection] = None


def _get_db() -> sqlite3.Connection:
    global _memory_db
    if _memory_db is None:
        _MEMORY_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(_MEMORY_DB_PATH), check_same_thread=False)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at TEXT    NOT NULL,
                task       TEXT,
                outcome    TEXT,
                summary    TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS facts (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT    NOT NULL,
                category   TEXT    NOT NULL,
                content    TEXT    NOT NULL UNIQUE
            )
        """)
        conn.commit()
        _memory_db = conn
    return _memory_db


def store_session(task: str, outcome: str, summary: str) -> None:
    with _db_lock:
        _get_db().execute(
            "INSERT INTO sessions (started_at, task, outcome, summary) VALUES (?, ?, ?, ?)",
            (datetime.utcnow().isoformat(), task, outcome, summary),
        )
        _get_db().commit()


def fetch_recent_sessions(limit: int = 5) -> list[dict]:
    with _db_lock:
        rows = _get_db().execute(
            "SELECT task, outcome, summary, started_at FROM sessions ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [{"task": r[0], "outcome": r[1], "summary": r[2], "started_at": r[3]} for r in rows]


# ---------------------------------------------------------------------------
# Request & Response Schemas
# ---------------------------------------------------------------------------
class ChatRequest(BaseModel):
    message: str


class SpeakRequest(BaseModel):
    text: str
    voice: typing.Optional[str] = None
    rate: typing.Optional[int] = None
    interrupt: bool = False


class ConfirmationRequest(BaseModel):
    confirmed: bool
    action: dict


# ---------------------------------------------------------------------------
# HTTP REST Endpoints
# ---------------------------------------------------------------------------
@app.get("/")
async def get_index():
    """Serves the accessible dashboard index page."""
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        return FileResponse(str(index_file))
    return {"message": "SAHAYAK Backend Running", "status": "ok"}


@app.get("/api/status")
async def get_system_status():
    """Returns real-time status of AI engines, local permissions, and screen context."""
    app_ctx = get_active_app_context()
    screen_size = get_logical_screen_size()
    return {
        "project": "SAHAYAK",
        "tagline": "Your Voice. Your Freedom.",
        "gemini_configured": gemini_engine.is_available(),
        "gemini_model": GEMINI_MODEL_ID,
        "operating_mode": "Gemini 3.8 Flash + Local Fallback" if gemini_engine.is_available() else "Local Offline Mode",
        "tts_available": True,
        "tts_engine": "macOS Native (say)",
        "stt_engine": "Local Whisper (faster-whisper) + Web Speech",
        "vision_ocr_available": True,
        "active_app": app_ctx.get("app_name", "Finder"),
        "tab_title": app_ctx.get("tab_title", ""),
        "screen_resolution": f"{screen_size[0]}x{screen_size[1]}",
    }


@app.post("/api/speak")
async def post_speak(req: SpeakRequest):
    """Speaks text aloud using local macOS speech synthesis."""
    if not req.text:
        raise HTTPException(status_code=400, detail="Text is required")
    tts.speak(req.text, voice=req.voice, rate=req.rate, interrupt=req.interrupt)
    return {"status": "speaking", "text": req.text}


@app.post("/api/capture")
async def post_capture():
    """Captures the screen and provides OCR and visual description."""
    cap = capture_screen_image()
    ocr_blocks = perform_local_ocr_on_screen()
    app_ctx = get_active_app_context()

    description = await gemini_engine.describe_screen(
        image_b64=cap.get("image_base64", ""),
        app_context=app_ctx,
        ocr_blocks=ocr_blocks,
        user_query="Describe what is on my screen.",
    )

    return {
        "status": "success",
        "image_base64": cap.get("image_base64"),
        "width": cap.get("width"),
        "height": cap.get("height"),
        "app_name": app_ctx.get("app_name"),
        "tab_title": app_ctx.get("tab_title"),
        "ocr_count": len(ocr_blocks),
        "description": description,
    }


@app.post("/api/chat")
async def post_chat(req: ChatRequest):
    """
    Primary processing route for commands.
    Interprets intent, checks sensitive confirmation, plans action, executes safe action,
    and returns spoken feedback.
    """
    raw_message = req.message.strip()
    if not raw_message:
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    logger.info(f"Incoming user instruction: '{raw_message}'")
    app_ctx = get_active_app_context()

    # Step 1: Interpret intent
    interpreted = await gemini_engine.interpret_intent(raw_message, app_ctx)

    # Step 2: Capture screen context for vision-guided reasoning
    cap = capture_screen_image()
    ocr_blocks = perform_local_ocr_on_screen()

    # Step 3: Check for sensitive operation (Guardrail)
    is_sensitive, confirm_prompt = gemini_engine.detect_sensitive_operation(interpreted)
    if is_sensitive:
        return {
            "requires_confirmation": True,
            "confirmation_prompt": confirm_prompt,
            "action": {
                "command": "delete_file" if "delete" in interpreted.lower() else "sensitive_action",
                "original_request": interpreted,
            },
            "spoken_response": confirm_prompt,
        }

    # Step 4: Check if request is simply asking to describe or read screen
    lower_cmd = interpreted.lower()
    if any(q in lower_cmd for q in ["what is on my screen", "describe", "read this", "what's on my screen", "explain this window"]):
        desc = await gemini_engine.describe_screen(
            image_b64=cap.get("image_base64", ""),
            app_context=app_ctx,
            ocr_blocks=ocr_blocks,
            user_query=interpreted,
        )
        tts.speak(desc)
        store_session(interpreted, "complete", desc[:100])
        return {
            "requires_confirmation": False,
            "spoken_response": desc,
            "action": {"command": "describe", "text": desc},
            "screen_image": cap.get("image_base64"),
        }

    # Step 5: Plan action via Gemini 3.8 Flash (or Local Rule Engine)
    action: AgentAction = await gemini_engine.plan_action(
        user_text=interpreted,
        image_b64=cap.get("image_base64", ""),
        app_context=app_ctx,
        ocr_blocks=ocr_blocks,
        step_number=1,
    )

    if action.is_sensitive:
        prompt = action.confirmation_prompt or f"Please confirm before executing: {action.explanation}"
        return {
            "requires_confirmation": True,
            "confirmation_prompt": prompt,
            "action": action.model_dump(),
            "spoken_response": prompt,
        }

    # Step 6: Execute the planned safe action
    cmd = action.command
    exec_result = {}
    spoken_feedback = action.explanation or "Action completed."

    if cmd == "website_search":
        target_site = action.target_website or "google"
        search_query = action.query or action.text or ""
        exec_result = execute_website_search(target_site, search_query)
        spoken_feedback = exec_result.get("spoken_feedback", f"Searched {target_site} for {search_query}.")

    elif cmd == "browser_search":
        search_query = action.query or action.text or ""
        exec_result = execute_browser_search(search_query)
        spoken_feedback = exec_result.get("spoken_feedback", f"Searched the web for {search_query}.")

    elif cmd == "system_search":
        search_query = action.query or action.text or ""
        exec_result = execute_system_search(search_query)
        spoken_feedback = exec_result.get("spoken_feedback", f"Searching your Mac for {search_query}.")

    elif cmd == "open_website":
        target = action.url or action.target_website or "https://google.com"
        exec_result = execute_open_website(target)
        spoken_feedback = exec_result.get("spoken_feedback", f"Opening {target}.")

    elif cmd == "open_application":
        app_name = action.text or "Application"
        exec_result = execute_open_application(app_name)
        spoken_feedback = exec_result.get("spoken_feedback", f"Opening {app_name}.")

    elif cmd == "open_url" and action.url:
        exec_result = execute_open_url(action.url)
        spoken_feedback = f"Opening {action.url}."
    elif cmd == "type_text" and action.text:
        exec_result = execute_type_spotlight(action.text)
        spoken_feedback = f"Opening {action.text}."
    elif cmd == "keyboard_type" and action.text:
        exec_result = execute_keyboard_type(action.text)
        spoken_feedback = f"Typed {action.text}."
    elif cmd == "press_hotkey" and action.keys:
        exec_result = execute_hotkey(action.keys)
        spoken_feedback = f"Pressed {' plus '.join(action.keys)}."
    elif cmd == "scroll" and action.amount is not None:
        exec_result = execute_scroll(action.amount)
        spoken_feedback = "Scrolled."
    elif cmd == "click" and action.x is not None and action.y is not None:
        exec_result = execute_click(action.x, action.y)
        spoken_feedback = f"Clicked at coordinate {action.x}, {action.y}."
    elif cmd == "describe" and action.text:
        spoken_feedback = action.text

    # Speak result aloud
    tts.speak(spoken_feedback)
    store_session(interpreted, "complete", spoken_feedback)

    return {
        "requires_confirmation": False,
        "spoken_response": spoken_feedback,
        "action": action.model_dump(),
        "execution_result": exec_result,
        "screen_image": cap.get("image_base64"),
    }


@app.post("/api/confirm_action")
async def post_confirm_action(req: ConfirmationRequest):
    """
    Executes a sensitive action after explicit user confirmation.
    """
    if not req.confirmed:
        tts.speak("Operation cancelled.")
        return {"status": "cancelled", "spoken_response": "Operation cancelled."}

    logger.info(f"User confirmed sensitive action: {req.action}")
    res = execute_sensitive_action(req.action)
    msg = res.get("message", "Confirmed operation was executed successfully.")
    tts.speak(msg)
    store_session(f"Confirmed Action: {req.action.get('command')}", "confirmed_complete", msg)
    return {"status": "success", "spoken_response": msg, "details": msg}


@app.get("/api/history")
async def get_history():
    """Returns recent interaction history from SQLite memory."""
    sessions = fetch_recent_sessions(limit=10)
    return {"sessions": sessions}


# ---------------------------------------------------------------------------
# WebSocket Agent Endpoint: ws://localhost:8080/ws/agent
# ---------------------------------------------------------------------------
@app.websocket("/ws/agent")
async def agent_websocket(websocket: WebSocket):
    await websocket.accept()
    logger.info("New WebSocket client connected to SAHAYAK agent.")

    audio_buffer = bytearray()
    state = {
        "handshake_done": False,
        "is_processing": False,
    }

    try:
        while True:
            msg = await websocket.receive()

            # Binary audio chunks (PCM)
            if msg.get("bytes"):
                audio_chunk = msg["bytes"]
                audio_buffer.extend(audio_chunk)

                # If buffer exceeds ~2 seconds of 16kHz 16-bit mono audio (64,000 bytes)
                if len(audio_buffer) >= 64000 and not state["is_processing"]:
                    state["is_processing"] = True
                    raw_pcm = bytes(audio_buffer)
                    audio_buffer.clear()

                    # Transcribe locally using Whisper
                    transcript = await asyncio.to_thread(stt.transcribe_audio_bytes, raw_pcm)
                    if transcript:
                        logger.info(f"WS Audio Transcribed: '{transcript}'")
                        # Process user instruction
                        app_ctx = get_active_app_context()
                        cap = capture_screen_image()
                        ocr_blocks = perform_local_ocr_on_screen()

                        # Check sensitive
                        is_sens, prompt = gemini_engine.detect_sensitive_operation(transcript)
                        if is_sens:
                            await websocket.send_json({
                                "command": "confirm_required",
                                "description": prompt,
                                "action": {"command": "sensitive_action", "task": transcript},
                            })
                            tts.speak(prompt)
                        else:
                            action = await gemini_engine.plan_action(
                                user_text=transcript,
                                image_b64=cap.get("image_base64", ""),
                                app_context=app_ctx,
                                ocr_blocks=ocr_blocks,
                            )
                            # Execute action
                            feedback = action.explanation or "Action completed."
                            if action.command == "website_search":
                                res = execute_website_search(action.target_website or "google", action.query or action.text or "")
                                feedback = res.get("spoken_feedback", feedback)
                            elif action.command == "browser_search":
                                res = execute_browser_search(action.query or action.text or "")
                                feedback = res.get("spoken_feedback", feedback)
                            elif action.command == "system_search":
                                res = execute_system_search(action.query or action.text or "")
                                feedback = res.get("spoken_feedback", feedback)
                            elif action.command == "open_website":
                                res = execute_open_website(action.url or action.target_website or "https://google.com")
                                feedback = res.get("spoken_feedback", feedback)
                            elif action.command == "open_application":
                                res = execute_open_application(action.text or "Application")
                                feedback = res.get("spoken_feedback", feedback)
                            elif action.command == "open_url" and action.url:
                                execute_open_url(action.url)
                            elif action.command == "type_text" and action.text:
                                execute_type_spotlight(action.text)
                            elif action.command == "scroll" and action.amount:
                                execute_scroll(action.amount)
                            elif action.command == "click" and action.x and action.y:
                                execute_click(action.x, action.y)

                            feedback = action.explanation or "Action completed."
                            tts.speak(feedback)
                            await websocket.send_json({
                                "command": "speak",
                                "text": feedback,
                            })

                    state["is_processing"] = False

            # JSON control messages
            elif msg.get("text"):
                try:
                    payload = json.loads(msg["text"])
                    event = payload.get("event")
                    command = payload.get("command")

                    if event == "wake_word_detected":
                        state["handshake_done"] = True
                        tts.speak("I am listening.", interrupt=True)
                        await websocket.send_json({
                            "status": "handshake_complete",
                            "message": "SAHAYAK is listening",
                        })

                    elif command == "capture_screen":
                        cap = capture_screen_image()
                        app_ctx = get_active_app_context()
                        await websocket.send_json({
                            "command": "screen_captured",
                            "image_base64": cap.get("image_base64"),
                            "width": cap.get("width"),
                            "height": cap.get("height"),
                            "app_context": app_ctx,
                        })

                except json.JSONDecodeError:
                    pass

    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected.")
    except Exception as exc:
        logger.error(f"WebSocket session error: {exc}")
    finally:
        logger.info("WebSocket session terminated.")


# ---------------------------------------------------------------------------
# Application Entry Point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", 8080))
    logger.info(f"Starting SAHAYAK Server on http://{host}:{port}")
    uvicorn.run(app, host=host, port=port)
