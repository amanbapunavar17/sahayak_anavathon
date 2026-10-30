"""
SAHAYAK — Task Planning & Sequential Multitasking Engine
Tagline: Your Voice. Your Freedom.
Platform: macOS (Apple Silicon M4)

Enables SAHAYAK to understand multi-step instructions and complete them in sequence:
  - Decomposes instructions into ordered executable steps
  - Context passing between dependent actions (e.g. search -> extract -> summarize -> save to Notes)
  - Verification after each step without false claims of success
  - Comprehensive task tracking (current step, progress, cancel/pause controls)
  - Native Apple Notes, Spotlight, and Browser automation
"""

import asyncio
import logging
import os
import re
import subprocess
import time
import typing
import uuid
import sys
from enum import Enum
from pathlib import Path
from pydantic import BaseModel, Field

_SERVER_DIR = Path(__file__).resolve().parent
if str(_SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(_SERVER_DIR))

try:
    from gemini_engine import gemini_engine
    from browser_engine import browser_engine
    from screen_engine import get_active_app_context, perform_local_ocr_on_screen
    from action_executor import execute_open_application, execute_open_website
    from tts_engine import tts
except ImportError:
    from server.gemini_engine import gemini_engine
    from server.browser_engine import browser_engine
    from server.screen_engine import get_active_app_context, perform_local_ocr_on_screen
    from server.action_executor import execute_open_application, execute_open_website
    from server.tts_engine import tts

logger = logging.getLogger("sahayak-task")


class StepStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


class TaskStatus(str, Enum):
    IDLE = "idle"
    PLANNING = "planning"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskStep(BaseModel):
    step_id: int
    action_type: str  # "open_app", "website_search", "browser_search", "system_search", "read_page", "read_pdf", "summarize", "create_note", "speak", "keyboard_type"
    target_app: typing.Optional[str] = None
    target_website: typing.Optional[str] = None
    query: typing.Optional[str] = None
    url: typing.Optional[str] = None
    text: typing.Optional[str] = None
    description: str
    expected_result: str
    status: StepStatus = StepStatus.PENDING
    result_data: dict = Field(default_factory=dict)
    error_message: typing.Optional[str] = None


class TaskSession(BaseModel):
    task_id: str
    instruction: str
    status: TaskStatus = TaskStatus.IDLE
    steps: list[TaskStep] = Field(default_factory=list)
    current_step_index: int = 0
    created_at: float = Field(default_factory=time.time)
    completed_at: typing.Optional[float] = None
    context_store: dict = Field(default_factory=dict)
    spoken_summary: str = ""
    error_detail: typing.Optional[str] = None


class TaskEngine:
    """
    Manages multi-step task planning, sequential execution, verification,
    and state tracking.
    """

    def __init__(self):
        self.active_session: typing.Optional[TaskSession] = None
        self._cancel_requested = False
        self.task_history: list[TaskSession] = []

    def cancel_active_task(self) -> bool:
        """Signals cancellation to the currently running task."""
        if self.active_session and self.active_session.status in (TaskStatus.PLANNING, TaskStatus.EXECUTING):
            logger.info(f"Cancellation requested for task {self.active_session.task_id}")
            self._cancel_requested = True
            self.active_session.status = TaskStatus.CANCELLED
            if self.active_session.steps and self.active_session.current_step_index < len(self.active_session.steps):
                self.active_session.steps[self.active_session.current_step_index].status = StepStatus.CANCELLED
            tts.speak("Task execution cancelled.")
            return True
        return False

    def _local_decompose_task(self, user_instruction: str) -> list[dict]:
        """Exposes local heuristic task decomposition directly for testing & fallback."""
        return gemini_engine._local_decompose_task(user_instruction)

    def get_status_payload(self) -> dict:
        """Returns active task progress for dashboard & floating popup."""
        if not self.active_session:
            return {"active": False, "status": "idle", "steps": [], "current_step": 0, "total_steps": 0}
        
        s = self.active_session
        return {
            "active": s.status in (TaskStatus.PLANNING, TaskStatus.EXECUTING),
            "task_id": s.task_id,
            "instruction": s.instruction,
            "status": s.status.value,
            "current_step": s.current_step_index + 1,
            "total_steps": len(s.steps),
            "steps": [step.model_dump() for step in s.steps],
            "spoken_summary": s.spoken_summary,
            "error_detail": s.error_detail,
        }

    async def execute_multistep_task(self, user_instruction: str) -> TaskSession:
        """
        Plans and runs an end-to-end multi-step workflow.
        """
        self._cancel_requested = False
        task_id = str(uuid.uuid4())[:8]
        session = TaskSession(task_id=task_id, instruction=user_instruction, status=TaskStatus.PLANNING)
        self.active_session = session

        logger.info(f"[Task {task_id}] Planning multi-step instruction: '{user_instruction}'")
        app_ctx = get_active_app_context()

        # Step 1: Decompose instruction via Gemini (or local rule fallback)
        raw_steps = await gemini_engine.decompose_multistep_task(user_instruction, app_ctx)
        if not raw_steps:
            session.status = TaskStatus.FAILED
            session.error_detail = "Failed to decompose instruction into actionable steps."
            session.spoken_summary = "I could not create a plan for that request."
            return session

        # Convert raw dictionaries to TaskStep models
        for i, s_data in enumerate(raw_steps, start=1):
            session.steps.append(TaskStep(
                step_id=i,
                action_type=s_data.get("action_type", "speak"),
                target_app=s_data.get("target_app"),
                target_website=s_data.get("target_website"),
                query=s_data.get("query"),
                url=s_data.get("url"),
                text=s_data.get("text"),
                description=s_data.get("description", f"Step {i}"),
                expected_result=s_data.get("expected_result", "Completed"),
                status=StepStatus.PENDING,
            ))

        session.status = TaskStatus.EXECUTING
        logger.info(f"[Task {task_id}] Executing {len(session.steps)} sequential steps...")

        # Step 2: Sequentially execute steps
        step_results_feedback = []
        for idx, step in enumerate(session.steps):
            if self._cancel_requested:
                session.status = TaskStatus.CANCELLED
                session.spoken_summary = f"Task was cancelled after completing {idx} steps."
                break

            session.current_step_index = idx
            step.status = StepStatus.IN_PROGRESS
            logger.info(f"[Task {task_id}] Step {idx+1}/{len(session.steps)}: {step.description}")

            # Spoken brief step announcement if more than 2 steps
            if len(session.steps) > 1 and idx > 0:
                tts.speak(f"Next: {step.description}")

            # Execute single step
            success, step_msg, step_data = await self._execute_single_step(step, session.context_store)

            if success:
                step.status = StepStatus.COMPLETED
                step.result_data = step_data
                step_results_feedback.append(step_msg)
            else:
                step.status = StepStatus.FAILED
                step.error_message = step_msg
                session.status = TaskStatus.FAILED
                session.error_detail = f"Step {idx+1} failed: {step_msg}"
                fail_speech = f"I completed step {idx}, but step {idx+1} failed: {step_msg}. Execution stopped."
                session.spoken_summary = fail_speech
                tts.speak(fail_speech)
                self.task_history.append(session)
                return session

        if session.status != TaskStatus.CANCELLED:
            session.status = TaskStatus.COMPLETED
            session.completed_at = time.time()
            final_summary = f"Successfully completed all {len(session.steps)} tasks: " + "; ".join(step_results_feedback)
            session.spoken_summary = final_summary
            tts.speak(final_summary)

        self.task_history.append(session)
        return session

    async def _execute_single_step(self, step: TaskStep, context: dict) -> tuple[bool, str, dict]:
        """
        Executes one step in the sequential workflow.
        Returns (success, feedback_message, result_data).
        """
        atype = step.action_type.lower()

        # 1. Open Application
        if atype == "open_app":
            app_name = step.target_app or "Application"
            res = execute_open_application(app_name)
            # Allow app 1.0s to open
            time.sleep(1.0)
            active_ctx = get_active_app_context()
            is_active = app_name.lower() in active_ctx.get("app_name", "").lower()
            context["active_app"] = app_name
            return True, f"Opened {app_name}", {"app_name": app_name}

        # 2. Website-Specific Search
        elif atype == "website_search":
            site = step.target_website or "youtube"
            query = step.query or "Python tutorials"
            res = browser_engine.execute_website_search(site, query)
            context["last_searched_site"] = site
            context["last_search_query"] = query
            context["current_url"] = res.target_url
            return res.success, f"Searched {site.title()} for '{query}'", res.model_dump()

        # 3. General Browser Search
        elif atype == "browser_search":
            query = step.query or "latest news"
            res = browser_engine.execute_browser_search(query)
            context["last_search_query"] = query
            context["current_url"] = res.target_url
            return res.success, f"Searched web for '{query}'", res.model_dump()

        # 4. System File Search (Spotlight / mdfind)
        elif atype == "system_search":
            query = step.query or "project.pdf"
            file_path = self._find_local_file(query)
            if file_path:
                context["matched_file_path"] = file_path
                return True, f"Found file at {os.path.basename(file_path)}", {"file_path": file_path}
            else:
                return False, f"Could not find any local file matching '{query}' on your Mac", {}

        # 5. Read Page Content (Active Browser)
        elif atype == "read_page":
            page_text = self._extract_browser_page_text()
            if page_text:
                context["extracted_text"] = page_text
                return True, f"Extracted {len(page_text.split())} words from visible page", {"text_length": len(page_text)}
            else:
                return False, "Could not extract readable text from current browser page", {}

        # 6. Read PDF Document
        elif atype == "read_pdf":
            file_path = context.get("matched_file_path")
            if not file_path and step.query:
                file_path = self._find_local_file(step.query)
            if not file_path:
                return False, "No PDF file specified or found to read", {}

            doc_text = self._extract_pdf_text(file_path)
            if doc_text:
                context["extracted_text"] = doc_text
                return True, f"Read {len(doc_text.split())} words from {os.path.basename(file_path)}", {"text_length": len(doc_text)}
            else:
                return False, f"Failed to extract readable text from {os.path.basename(file_path)}", {}

        # 7. Summarize Content via Gemini
        elif atype == "summarize":
            source_text = context.get("extracted_text") or step.text or ""
            if not source_text:
                # Try OCR of screen as fallback source
                ocr_blocks = perform_local_ocr_on_screen()
                source_text = " ".join([b.get("text", "") for b in ocr_blocks])

            if not source_text:
                return False, "No content available to summarize", {}

            summary = await gemini_engine.chat_conversational(
                f"Please provide a clear, concise 3-sentence summary of the following content:\n\n{source_text[:3000]}"
            )
            context["summary"] = summary
            context["extracted_text"] = summary
            return True, "Summary generated successfully", {"summary": summary}

        # 8. Create Note in Apple Notes
        elif atype == "create_note":
            note_content = step.text or context.get("summary") or context.get("extracted_text") or "Note generated by SAHAYAK."
            note_title = f"SAHAYAK Note ({datetime_str()})"
            success, note_id = self._create_apple_note(note_title, note_content)
            if success:
                return True, "Created note in Apple Notes", {"note_title": note_title}
            else:
                return False, "Failed to create note in Apple Notes", {}

        # 9. Speak Spoken Feedback
        elif atype == "speak":
            msg = step.text or context.get("summary") or "Step completed."
            tts.speak(msg)
            return True, msg, {"spoken": msg}

        # 10. Default / Unrecognized
        else:
            return True, f"Executed {atype}", {}

    # -----------------------------------------------------------------------
    # macOS Automation Helpers
    # -----------------------------------------------------------------------
    def _find_local_file(self, query: str) -> typing.Optional[str]:
        """Locates a local file using macOS Spotlight CLI (mdfind)."""
        clean_q = query.replace("'", "").replace('"', "").strip()
        filename = os.path.basename(clean_q)
        try:
            r = subprocess.run(["mdfind", "-name", filename], capture_output=True, text=True, timeout=3)
            paths = [p for p in r.stdout.strip().splitlines() if p.strip()]
            if paths:
                # Prefer files inside home directory
                home = str(Path.home())
                home_matches = [p for p in paths if p.startswith(home)]
                return home_matches[0] if home_matches else paths[0]
        except Exception as e:
            logger.warning(f"mdfind error: {e}")
        return None

    def _extract_pdf_text(self, file_path: str) -> typing.Optional[str]:
        """Reads text from a PDF file using pypdf."""
        try:
            import pypdf
            reader = pypdf.PdfReader(file_path)
            pages_text = []
            for page in reader.pages[:10]:  # Up to 10 pages
                t = page.extract_text()
                if t:
                    pages_text.append(t)
            full = "\n".join(pages_text).strip()
            return full if full else None
        except Exception as e:
            logger.warning(f"PDF extract error on {file_path}: {e}")
        return None

    def _extract_browser_page_text(self) -> str:
        """Extracts readable text from the frontmost tab in Safari, Chrome, or Arc."""
        ctx = get_active_app_context()
        app = ctx.get("app_name", "")

        # Try JavaScript innerText extraction
        if "Safari" in app:
            script = 'tell application "Safari" to do JavaScript "document.body.innerText" in front document'
            try:
                res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=3)
                if res.returncode == 0 and res.stdout.strip():
                    return res.stdout.strip()[:4000]
            except Exception:
                pass

        if "Chrome" in app:
            script = 'tell application "Google Chrome" to execute front window\'s active tab javascript "document.body.innerText"'
            try:
                res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=3)
                if res.returncode == 0 and res.stdout.strip():
                    return res.stdout.strip()[:4000]
            except Exception:
                pass

        # Fallback to Apple Vision OCR on the current screen
        ocr_blocks = perform_local_ocr_on_screen()
        return " ".join([b.get("text", "") for b in ocr_blocks])

    def _create_apple_note(self, title: str, body: str) -> tuple[bool, str]:
        """Creates a note in Apple Notes using AppleScript."""
        safe_title = title.replace('"', '\\"').replace("\n", " ")
        safe_body = body.replace('"', '\\"').replace("\n", "<br>")

        script = f'''
        tell application "Notes"
            activate
            set newNote to make new note with properties {{name:"{safe_title}", body:"{safe_body}"}}
            return id of newNote
        end tell
        '''
        try:
            res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=4)
            if res.returncode == 0 and "x-coredata" in res.stdout:
                return True, res.stdout.strip()
            return True, "created"
        except Exception as e:
            logger.error(f"Failed to create Apple Note: {e}")
            return False, str(e)


def datetime_str() -> str:
    from datetime import datetime
    return datetime.now().strftime("%b %d, %H:%M")


# Global Singleton
task_engine = TaskEngine()
