
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
import re
import sqlite3
import sys
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

_SERVER_DIR = Path(__file__).resolve().parent
if str(_SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(_SERVER_DIR))

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
    execute_take_photo,
    execute_open_file,
    execute_find_latest_file,
    execute_create_folder,
    execute_move_files,
    execute_system_settings,
    execute_click_element,
    execute_mouse_move,
    execute_double_click,
    execute_right_click,
)
from mouse_controller import mouse_controller
from intent_classifier import classify_intent, IntentType
from session_context import SessionContext
from gemini_engine import (
    gemini_engine,
    AgentAction,
    GEMINI_MODEL_ID,
)
from task_engine import task_engine
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


def get_recent_history(limit: int = 4) -> list[dict]:
    """Formats recent conversational turns for contextual Gemini reasoning."""
    sessions = fetch_recent_sessions(limit)
    history = []
    for s in reversed(sessions):
        if s.get("task"):
            history.append({"role": "user", "content": s["task"]})
        if s.get("summary"):
            history.append({"role": "assistant", "content": s["summary"]})
    return history


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
    language: typing.Optional[str] = None


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


@app.get("/popup")
async def get_popup():
    """Serves the compact accessible floating popup."""
    popup_file = STATIC_DIR / "popup.html"
    if popup_file.exists():
        return FileResponse(str(popup_file))
    return FileResponse(str(STATIC_DIR / "index.html"))


@app.get("/api/status")
async def get_system_status():
    """Returns real-time status of AI engines, local permissions, screen context, and tasks."""
    app_ctx = get_active_app_context()
    screen_size = get_logical_screen_size()
    diagnostics = gemini_engine.get_diagnostics()
    return {
        "project": "SAHAYAK",
        "tagline": "Your Voice. Your Freedom.",
        "gemini_configured": gemini_engine.is_available(),
        "gemini_model": GEMINI_MODEL_ID,
        "active_model": diagnostics.get("active_model", GEMINI_MODEL_ID),
        "connection_state": diagnostics.get("status", "offline"),
        "operating_mode": f"Gemini ({diagnostics.get('active_model')}) + Local Fallback" if gemini_engine.is_available() else "Local Offline Mode",
        "tts_available": True,
        "tts_engine": "macOS Native (say)",
        "stt_engine": "Local Whisper (faster-whisper) + Web Speech",
        "vision_ocr_available": True,
        "mouse_controller_available": True,
        "active_app": app_ctx.get("app_name", "Finder"),
        "window_title": app_ctx.get("window_title", ""),
        "tab_title": app_ctx.get("tab_title", ""),
        "is_browser_active": app_ctx.get("is_browser_active", False),
        "screen_resolution": f"{screen_size[0]}x{screen_size[1]}",
        "diagnostics": diagnostics,
        "active_task": task_engine.get_status_payload(),
    }


@app.get("/api/diagnostics")
async def get_diagnostics():
    """Returns real-time non-sensitive AI connectivity metrics."""
    return gemini_engine.get_diagnostics()


@app.get("/api/tasks/active")
async def get_active_task_status():
    """Returns live multitasking progress."""
    return task_engine.get_status_payload()


@app.post("/api/tasks/cancel")
async def post_cancel_active_task():
    """Cancels running multi-step task."""
    cancelled = task_engine.cancel_active_task()
    return {"status": "cancelled" if cancelled else "no_active_task"}


@app.post("/api/emergency_stop")
async def post_emergency_stop():
    """
    Global Emergency Stop:
    1. Cancels any running multi-step tasks immediately.
    2. Flushes and silences all Text-to-Speech audio immediately.
    3. Resets active automation state.
    4. Announces emergency stop to user.
    """
    task_cancelled = task_engine.cancel_active_task()
    tts.stop()
    msg = "Emergency stop activated. All operations halted."
    tts.speak(msg, interrupt=True)
    store_session("EMERGENCY_STOP", "halted", msg)
    return {
        "status": "stopped",
        "task_cancelled": task_cancelled,
        "spoken_response": msg,
    }


@app.post("/api/speak")
async def post_speak(req: SpeakRequest):
    """Speaks text aloud using local macOS speech synthesis."""
    if not req.text:
        raise HTTPException(status_code=400, detail="Text is required")
    tts.speak(req.text, voice=req.voice, rate=req.rate, interrupt=req.interrupt, language=req.language)
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
    try:
        return await _process_chat_message(raw_message)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Error handling post_chat for '{raw_message}': {exc}", exc_info=True)
        current_lang = SessionContext.get_language()
        if SessionContext.is_kannada(current_lang):
            fallback_speech = "ಕ್ಷಮಿಸಿ, ಈ ವಿನಂತಿಯನ್ನು ಪ್ರಕ್ರಿಯೆಗೊಳಿಸುವಾಗ ಸಣ್ಣ ಸಮಸ್ಯೆ ಎದುರಾಯಿತು. ದಯವಿಟ್ಟು ಮತ್ತೊಮ್ಮೆ ಪ್ರಯತ್ನಿಸಿ."
        else:
            fallback_speech = "I am listening and ready for your next command."
        tts.speak(fallback_speech, language=current_lang)
        store_session(raw_message, "recovered_error", str(exc)[:80])
        return {
            "requires_confirmation": False,
            "spoken_response": fallback_speech,
            "action": {"command": "conversational_answer", "text": fallback_speech, "language": current_lang},
            "error_detail": str(exc),
            "diagnostics": gemini_engine.get_diagnostics(),
        }


async def _process_chat_message(raw_message: str) -> dict:
    # Auto-detect script language so Kannada speech/text immediately sets Kannada context
    if re.search(r"[\u0c80-\u0cff]", raw_message):
        SessionContext.set_language("kn")
        tts.set_language("kn")
    elif re.search(r"[\u0900-\u097f]", raw_message):
        SessionContext.set_language("hi")
        tts.set_language("hi")

    app_ctx = get_active_app_context()

    # Step 1: Intent Pre-classification & Speech Mishearing Recovery
    raw_intent_check = classify_intent(raw_message)
    if raw_intent_check.intent in (
        IntentType.MULTISTEP_TASK,
        IntentType.TAKE_PHOTO,
        IntentType.CONVERSATIONAL_AI,
        IntentType.WEBSITE_SEARCH,
        IntentType.BROWSER_SEARCH,
        IntentType.SYSTEM_SEARCH,
        IntentType.OPEN_WEBSITE,
        IntentType.DESCRIBE_SCREEN,
        IntentType.CLICK_ELEMENT,
        IntentType.MOUSE_CONTROL,
        IntentType.LANGUAGE_SWITCH,
    ):
        interpreted = raw_message
    else:
        interpreted = await gemini_engine.interpret_intent(raw_message, app_ctx)

    # Step 2: Lazy screen context accessors to avoid ~880ms overhead on every single command
    _cached_cap = None
    _cached_ocr = None

    def _get_cap():
        nonlocal _cached_cap
        if _cached_cap is None:
            _cached_cap = capture_screen_image()
        return _cached_cap

    def _get_ocr():
        nonlocal _cached_ocr
        if _cached_ocr is None:
            _cached_ocr = perform_local_ocr_on_screen()
        return _cached_ocr

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
    current_lang = SessionContext.get_language()
    if any(q in lower_cmd for q in ["what is on my screen", "describe", "read this", "what's on my screen", "explain this window"]):
        cap = _get_cap()
        ocr_blocks = _get_ocr()
        desc = await gemini_engine.describe_screen(
            image_b64=cap.get("image_base64", ""),
            app_context=app_ctx,
            ocr_blocks=ocr_blocks,
            user_query=interpreted,
            language=current_lang,
        )
        tts.speak(desc, language=current_lang)
        store_session(interpreted, "complete", desc[:100])
        return {
            "requires_confirmation": False,
            "spoken_response": desc,
            "action": {"command": "describe", "text": desc, "language": current_lang},
            "screen_image": cap.get("image_base64"),
        }

    # Step 4a: Check Intent Classification (Conversational AI vs Multistep Task vs Actions)
    intent_res = classify_intent(interpreted)

    # Language Switch Handling (e.g. "Switch to Kannada", "Talk in Kannada")
    if intent_res.intent == IntentType.LANGUAGE_SWITCH:
        target_lang = intent_res.language or "kn"
        SessionContext.set_language(target_lang)
        tts.set_language(target_lang)
        if SessionContext.is_kannada(target_lang):
            ack_msg = "ಖಂಡಿತ, ಇನ್ನು ಮುಂದೆ ನಾನು ಕನ್ನಡದಲ್ಲಿ ಮಾತನಾಡುತ್ತೇನೆ."
        else:
            ack_msg = f"Language changed to {target_lang}."
        tts.speak(ack_msg, language=target_lang)
        store_session(interpreted, "complete", ack_msg)
        return {
            "requires_confirmation": False,
            "spoken_response": ack_msg,
            "action": {"command": "language_switch", "language": target_lang},
            "intent": "language_switch",
            "diagnostics": gemini_engine.get_diagnostics(),
        }

    # Conversational AI (Q&A, explanations, learning plans, coding advice, error diagnostics)
    if intent_res.intent == IntentType.CONVERSATIONAL_AI:
        recent_history = get_recent_history(limit=4)
        active_lang = SessionContext.get_language()
        needs_vision = any(w in lower_cmd for w in ["screen", "window", "what does this say", "look at", "read this", "error on", "image"])
        cap_b64 = _get_cap().get("image_base64", "") if needs_vision else ""
        blocks = _get_ocr() if needs_vision else []
        ai_response = await gemini_engine.chat_conversational(
            user_query=interpreted,
            screen_context=app_ctx,
            ocr_blocks=blocks,
            image_b64=cap_b64,
            history=recent_history,
            language=active_lang,
        )
        tts.speak(ai_response, language=active_lang)
        store_session(interpreted, "complete", ai_response[:100])
        return {
            "requires_confirmation": False,
            "spoken_response": ai_response,
            "action": {"command": "conversational_answer", "text": ai_response, "language": active_lang},
            "screen_image": cap_b64 if cap_b64 else None,
            "intent": "conversational_ai",
            "diagnostics": gemini_engine.get_diagnostics(),
        }

    # Multistep Task Workflows
    if intent_res.intent == IntentType.MULTISTEP_TASK:
        task_session = await task_engine.execute_multistep_task(interpreted)
        store_session(interpreted, task_session.status.value, task_session.spoken_summary[:100])
        return {
            "requires_confirmation": False,
            "spoken_response": task_session.spoken_summary,
            "action": {"command": "multistep_workflow", "task_id": task_session.task_id},
            "task_session": task_session.model_dump(),
            "screen_image": None,
            "intent": "multistep_task",
            "diagnostics": gemini_engine.get_diagnostics(),
        }

    # Step 5: Construct or plan action
    if intent_res.intent == IntentType.WEBSITE_SEARCH:
        action = AgentAction(
            command="website_search",
            explanation=intent_res.explanation,
            target_website=intent_res.target_website,
            query=intent_res.query,
            url=intent_res.url,
            done=True,
        )
    elif intent_res.intent == IntentType.BROWSER_SEARCH:
        action = AgentAction(
            command="browser_search",
            explanation=intent_res.explanation,
            query=intent_res.query,
            url=intent_res.url,
            done=True,
        )
    elif intent_res.intent == IntentType.SYSTEM_SEARCH:
        action = AgentAction(
            command="system_search",
            explanation=intent_res.explanation,
            query=intent_res.query,
            done=True,
        )
    elif intent_res.intent == IntentType.OPEN_WEBSITE:
        action = AgentAction(
            command="open_website",
            explanation=intent_res.explanation,
            url=intent_res.url,
            target_website=intent_res.target_website,
            done=True,
        )
    elif intent_res.intent == IntentType.OPEN_APPLICATION:
        action = AgentAction(
            command="open_application",
            explanation=intent_res.explanation,
            text=intent_res.target_app,
            done=True,
        )
    elif intent_res.intent == IntentType.TAKE_PHOTO:
        action = AgentAction(
            command="take_photo",
            explanation=intent_res.explanation or "Opening camera and capturing photo",
            text=intent_res.target_app or "Photo Booth",
            done=True,
        )
    elif intent_res.intent == IntentType.CLICK_ELEMENT:
        action = AgentAction(
            command="click_element",
            explanation=intent_res.explanation or f"Clicking {intent_res.target_element or 'element'}",
            target_element=intent_res.target_element,
            click_type=intent_res.click_type,
            button=intent_res.button,
            x=intent_res.x,
            y=intent_res.y,
            done=True,
        )
    elif intent_res.intent == IntentType.MOUSE_CONTROL:
        action = AgentAction(
            command="mouse_control",
            explanation=intent_res.explanation or f"Moving mouse cursor to {intent_res.target_element or 'target'}",
            target_element=intent_res.target_element,
            x=intent_res.x,
            y=intent_res.y,
            done=True,
        )
    else:
        action: AgentAction = await gemini_engine.plan_action(
            user_text=interpreted,
            image_b64=_get_cap().get("image_base64", ""),
            app_context=app_ctx,
            ocr_blocks=_get_ocr(),
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

    elif cmd == "take_photo":
        restore_prev = getattr(intent_res, "restore_previous", False)
        exec_result = execute_take_photo(restore_previous=restore_prev)
        spoken_feedback = exec_result.get("spoken_feedback", "Photo captured successfully.")

    elif cmd == "file_search":
        dir_target = getattr(action, "target_folder", None) or "Downloads"
        exec_result = execute_find_latest_file(directory=dir_target)
        spoken_feedback = exec_result.get("spoken_feedback", f"Found file in {dir_target}.")

    elif cmd == "open_file":
        target_path = getattr(action, "path", None) or action.text or ""
        exec_result = execute_open_file(target_path)
        spoken_feedback = exec_result.get("spoken_feedback", f"Opening file {target_path}.")

    elif cmd == "create_folder":
        folder_n = getattr(action, "folder_name", None) or action.text or "New Folder"
        parent = getattr(action, "target_folder", None) or "Desktop"
        exec_result = execute_create_folder(folder_n, parent_dir=parent)
        spoken_feedback = exec_result.get("spoken_feedback", f"Created folder {folder_n}.")

    elif cmd == "move_files":
        target_f = getattr(action, "target_folder", None) or action.text or "Desktop"
        paths = getattr(action, "source_paths", None) or []
        exec_result = execute_move_files(paths, target_f)
        spoken_feedback = exec_result.get("spoken_feedback", f"Moved files to {target_f}.")

    elif cmd == "system_settings":
        pane = action.text or getattr(action, "setting_type", None) or "Displays"
        delta = getattr(action, "delta", None) or 0
        exec_result = execute_system_settings(pane_query=pane, setting_type=getattr(action, "setting_type", None), delta=delta)
        spoken_feedback = exec_result.get("spoken_feedback", f"Adjusted {pane} settings.")

    elif cmd == "conversational_answer":
        spoken_feedback = action.text or action.explanation or "Here is what I found."
        exec_result = {"status": "success", "command": "conversational_answer", "text": spoken_feedback}
    elif cmd == "open_url" and action.url:
        exec_result = execute_open_url(action.url)
        spoken_feedback = f"Opening {action.url}."
    elif cmd == "type_text" and action.text:
        exec_result = execute_type_spotlight(action.text)
        spoken_feedback = f"Opening {action.text}."
    elif cmd == "keyboard_type" and action.text:
        lower_raw = interpreted.lower()
        explicit_type = any(w in lower_raw for w in ["type", "enter text", "write down", "write text", "input text", "dictate"]) or bool(action.target_element)
        if not explicit_type and not getattr(action, "target_app", None):
            # Guard against typing user questions/instructions into active browser
            active_lang = SessionContext.get_language()
            ai_response = await gemini_engine.chat_conversational(
                user_query=interpreted,
                screen_context=app_ctx,
                ocr_blocks=ocr_blocks,
                image_b64=cap.get("image_base64", ""),
                language=active_lang,
            )
            spoken_feedback = ai_response
            exec_result = {"status": "success", "command": "conversational_answer", "text": ai_response}
        else:
            target_a = getattr(action, "target_app", None)
            exec_result = execute_keyboard_type(action.text, target_app=target_a)
            spoken_feedback = exec_result.get("spoken_feedback", f"Typed {action.text}.")
    elif cmd == "press_hotkey" and action.keys:
        exec_result = execute_hotkey(action.keys)
        spoken_feedback = f"Pressed {' plus '.join(action.keys)}."
    elif cmd == "scroll" and action.amount is not None:
        exec_result = execute_scroll(action.amount)
        spoken_feedback = "Scrolled."
    elif cmd in ("click_element", "click_button"):
        t_elem = getattr(action, "target_element", None) or action.text
        c_type = getattr(action, "click_type", "single") or "single"
        btn = getattr(action, "button", "left") or "left"
        exec_result = execute_click_element(
            target_element=t_elem,
            click_type=c_type,
            button=btn,
            x=action.x,
            y=action.y,
            ocr_blocks=ocr_blocks,
        )
        spoken_feedback = exec_result.get("spoken_feedback", f"Clicked {t_elem or 'element'}.")

    elif cmd in ("mouse_control", "move_mouse"):
        target = getattr(action, "target_element", None) or action.text
        exec_result = execute_mouse_move(
            target=target,
            x=action.x,
            y=action.y,
        )
        spoken_feedback = exec_result.get("spoken_feedback", f"Moved mouse to {target or 'target'}.")

    elif cmd == "double_click":
        t_elem = getattr(action, "target_element", None) or action.text
        exec_result = execute_double_click(
            x=action.x,
            y=action.y,
            target_element=t_elem,
            ocr_blocks=ocr_blocks,
        )
        spoken_feedback = exec_result.get("spoken_feedback", f"Double clicked {t_elem or 'element'}.")

    elif cmd == "right_click":
        t_elem = getattr(action, "target_element", None) or action.text
        exec_result = execute_right_click(
            x=action.x,
            y=action.y,
            target_element=t_elem,
            ocr_blocks=ocr_blocks,
        )
        spoken_feedback = exec_result.get("spoken_feedback", f"Right clicked {t_elem or 'element'}.")

    elif cmd == "click":
        if getattr(action, "target_element", None):
            exec_result = execute_click_element(
                target_element=action.target_element,
                click_type=getattr(action, "click_type", "single") or "single",
                button=getattr(action, "button", "left") or "left",
                x=action.x,
                y=action.y,
                ocr_blocks=ocr_blocks,
            )
            spoken_feedback = exec_result.get("spoken_feedback", f"Clicked {action.target_element}.")
        elif action.x is not None and action.y is not None:
            exec_result = execute_click(action.x, action.y)
            spoken_feedback = f"Clicked at coordinate {action.x}, {action.y}."
        else:
            exec_result = execute_click_element(click_type="single")
            spoken_feedback = "Clicked at current position."

    elif cmd == "describe" and action.text:
        spoken_feedback = action.text

    # Speak result aloud
    action_lang = getattr(action, "language", None) or SessionContext.get_language()
    tts.speak(spoken_feedback, language=action_lang)
    store_session(interpreted, "complete", spoken_feedback)

    return {
        "requires_confirmation": False,
        "spoken_response": spoken_feedback,
        "action": action.model_dump(),
        "execution_result": exec_result,
        "screen_image": _cached_cap.get("image_base64") if _cached_cap else None,
        "intent": intent_res.intent.value,
        "diagnostics": gemini_engine.get_diagnostics(),
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
                            elif action.command in ("click_element", "click_button"):
                                res = execute_click_element(
                                    target_element=getattr(action, "target_element", None) or action.text,
                                    click_type=getattr(action, "click_type", "single") or "single",
                                    button=getattr(action, "button", "left") or "left",
                                    x=action.x,
                                    y=action.y,
                                    ocr_blocks=ocr_blocks,
                                )
                                feedback = res.get("spoken_feedback", feedback)
                            elif action.command in ("mouse_control", "move_mouse"):
                                res = execute_mouse_move(
                                    target=getattr(action, "target_element", None) or action.text,
                                    x=action.x,
                                    y=action.y,
                                )
                                feedback = res.get("spoken_feedback", feedback)
                            elif action.command == "double_click":
                                res = execute_double_click(
                                    x=action.x,
                                    y=action.y,
                                    target_element=getattr(action, "target_element", None) or action.text,
                                    ocr_blocks=ocr_blocks,
                                )
                                feedback = res.get("spoken_feedback", feedback)
                            elif action.command == "right_click":
                                res = execute_right_click(
                                    x=action.x,
                                    y=action.y,
                                    target_element=getattr(action, "target_element", None) or action.text,
                                    ocr_blocks=ocr_blocks,
                                )
                                feedback = res.get("spoken_feedback", feedback)
                            elif action.command == "click":
                                if getattr(action, "target_element", None):
                                    res = execute_click_element(
                                        target_element=action.target_element,
                                        click_type=getattr(action, "click_type", "single") or "single",
                                        button=getattr(action, "button", "left") or "left",
                                        x=action.x,
                                        y=action.y,
                                        ocr_blocks=ocr_blocks,
                                    )
                                    feedback = res.get("spoken_feedback", feedback)
                                elif action.x and action.y:
                                    res = execute_click(action.x, action.y)
                                    feedback = res.get("spoken_feedback", feedback)
                                else:
                                    res = execute_click_element(click_type="single")
                                    feedback = res.get("spoken_feedback", feedback)

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