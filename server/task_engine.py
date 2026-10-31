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
    import app_target_manager
    import macos_automator
    from mouse_controller import mouse_controller
except ImportError:
    from server.gemini_engine import gemini_engine
    from server.browser_engine import browser_engine
    from server.screen_engine import get_active_app_context, perform_local_ocr_on_screen
    from server.action_executor import execute_open_application, execute_open_website
    from server.tts_engine import tts
    from server import app_target_manager
    from server import macos_automator
    from server.mouse_controller import mouse_controller

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
    RECEIVED = "received"
    UNDERSTANDING = "understanding"
    PLANNING = "planning"
    TARGETING = "targeting"
    APPLICATION_IDENTIFICATION = "application_identification"  # Backward compatibility alias
    ACTIVATING = "activating"
    APPLICATION_ACTIVATION = "application_activation"          # Backward compatibility alias
    EXECUTING = "executing"
    VERIFYING = "verifying"
    COMPLETED = "completed"
    FAILED = "failed"
    WAITING_FOR_USER_CONFIRMATION = "waiting_for_user_confirmation"
    CANCELLED = "cancelled"


class TaskStep(BaseModel):
    step_id: int
    action_type: str
    target_app: typing.Optional[str] = None
    target_bundle_id: typing.Optional[str] = None
    target_window: typing.Optional[str] = None
    target_ui_element: typing.Optional[str] = None
    click_type: typing.Optional[str] = "single"
    button: typing.Optional[str] = "left"
    x: typing.Optional[int] = None
    y: typing.Optional[int] = None
    target_website: typing.Optional[str] = None
    target_folder: typing.Optional[str] = None
    folder_name: typing.Optional[str] = None
    setting_type: typing.Optional[str] = None
    operation: typing.Optional[str] = None
    delta: typing.Optional[int] = None
    query: typing.Optional[str] = None
    url: typing.Optional[str] = None
    text: typing.Optional[str] = None
    description: str
    expected_result: str
    requires_text_input: bool = False
    requires_camera_permission: bool = False
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
        self.macos_automator = macos_automator
        self.app_target_manager = app_target_manager
        self.browser_engine = browser_engine
        self.mouse_controller = mouse_controller

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
        session = TaskSession(task_id=task_id, instruction=user_instruction, status=TaskStatus.RECEIVED)
        self.active_session = session

        # Save initial foreground context to support restoring user focus
        front_app = app_target_manager.get_frontmost_application()
        initial_app_name = front_app.get("app_name") or "Finder"
        session.context_store["initial_active_app"] = initial_app_name
        session.context_store["initial_window_title"] = front_app.get("window_title", "")

        session.status = TaskStatus.UNDERSTANDING
        logger.info(f"[Task {task_id}] Planning multi-step instruction: '{user_instruction}'")
        app_ctx = get_active_app_context()

        # Step 1: Decompose instruction via Gemini (or local rule fallback)
        session.status = TaskStatus.PLANNING
        raw_steps = await gemini_engine.decompose_multistep_task(user_instruction, app_ctx)
        if not raw_steps:
            session.status = TaskStatus.FAILED
            session.error_detail = "Failed to decompose instruction into actionable steps."
            session.spoken_summary = "I could not create a plan for that request."
            return session

        # Convert raw dictionaries to TaskStep models
        for i, s_data in enumerate(raw_steps, start=1):
            target_app_raw = s_data.get("target_app")
            target_bundle = None
            if target_app_raw:
                t_info = app_target_manager.resolve_target_application(target_app_raw)
                target_bundle = t_info.get("bundle_id")
            session.steps.append(TaskStep(
                step_id=i,
                action_type=s_data.get("action_type", "speak"),
                target_app=target_app_raw,
                target_bundle_id=target_bundle,
                target_website=s_data.get("target_website"),
                target_ui_element=s_data.get("target_ui_element") or s_data.get("target_element"),
                click_type=s_data.get("click_type", "single"),
                button=s_data.get("button", "left"),
                x=s_data.get("x"),
                y=s_data.get("y"),
                target_folder=s_data.get("target_folder"),
                folder_name=s_data.get("folder_name"),
                setting_type=s_data.get("setting_type"),
                operation=s_data.get("operation"),
                delta=s_data.get("delta"),
                query=s_data.get("query"),
                url=s_data.get("url"),
                text=s_data.get("text"),
                description=s_data.get("description", f"Step {i}"),
                expected_result=s_data.get("expected_result", "Completed"),
                requires_text_input=s_data.get("requires_text_input", False),
                requires_camera_permission=(s_data.get("action_type") == "take_photo"),
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

            # State transition: TARGETING and ACTIVATING
            session.status = TaskStatus.TARGETING
            if step.target_app:
                session.status = TaskStatus.ACTIVATING
                self.app_target_manager.activate_and_focus_application(step.target_app, timeout=2.5)

            session.status = TaskStatus.EXECUTING
            # Execute single step
            success, step_msg, step_data = await self._execute_single_step(step, session.context_store)

            session.status = TaskStatus.VERIFYING
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
            t_info = self.app_target_manager.resolve_target_application(app_name)
            target_name = t_info.get("name", app_name)
            activated = self.app_target_manager.activate_and_focus_application(target_name, timeout=3.0)
            context["active_app"] = target_name
            context["active_bundle_id"] = t_info.get("bundle_id")
            return activated, f"Opened {target_name}", {"app_name": target_name, "verified": activated}

        # 2. Camera Photo Capture
        elif atype == "take_photo":
            res = self.app_target_manager.execute_camera_capture(restore_previous=False)
            if res.get("success"):
                context["captured_photo_path"] = res.get("photo_path")
                context["captured_photo_filename"] = res.get("photo_filename")
                context["captured_photo_size"] = res.get("file_size")
                return True, f"Captured photo: {res.get('photo_filename')}", res
            else:
                return False, f"Failed to take picture: {res.get('error', 'unknown')}", res

        # 3. Restore Application Focus
        elif atype == "restore_focus":
            target = step.target_app or context.get("initial_active_app") or "Notes"
            success = self.app_target_manager.restore_application_focus(target)
            return True, f"Restored focus to {target}", {"restored_app": target, "verified": success}

        # 4. Open Website / Direct Navigation
        elif atype in ("open_website", "visit_website"):
            target_url = step.url or (f"https://www.{step.target_website}.com" if step.target_website else "https://google.com")
            res = self.browser_engine.execute_open_website(target_url)
            context["current_url"] = res.target_url
            context["last_searched_site"] = step.target_website
            return res.success, f"Navigated to {step.target_website or target_url}", res.model_dump()

        # 5. Website-Specific Search
        elif atype == "website_search":
            site = step.target_website or "youtube"
            query = step.query or "Python tutorials"
            res = self.browser_engine.execute_website_search(site, query)
            context["last_searched_site"] = site
            context["last_search_query"] = query
            context["current_url"] = res.target_url
            return res.success, f"Searched {site.title()} for '{query}'", res.model_dump()

        # 6. General Browser Search
        elif atype == "browser_search":
            query = step.query or "latest news"
            res = self.browser_engine.execute_browser_search(query)
            context["last_search_query"] = query
            context["current_url"] = res.target_url
            return res.success, f"Searched web for '{query}'", res.model_dump()

        # 7. File Search (Directory scanning or latest file)
        elif atype == "file_search":
            dir_target = step.target_folder or "Downloads"
            found_path = self.macos_automator.find_latest_file(directory=dir_target)
            if found_path:
                context["matched_file_path"] = found_path
                fname = os.path.basename(found_path)
                return True, f"Located latest file in {dir_target}: {fname}", {"file_path": found_path, "filename": fname}
            return False, f"Could not find any files in {dir_target}", {}

        # 8. Open Local File
        elif atype == "open_file":
            target_f = context.get("matched_file_path") or step.query
            if not target_f:
                target_f = self.macos_automator.find_latest_file("Downloads")
            if target_f and os.path.exists(target_f):
                success, msg = self.macos_automator.open_file(target_f)
                return success, msg, {"file_path": target_f}
            return False, "No file specified or found on your Mac to open", {}

        # 9. Create Folder
        elif atype == "create_folder":
            fn = step.folder_name or "New Folder"
            p_dir = step.target_folder or "Desktop"
            success, msg, path_created = self.macos_automator.create_folder(fn, parent_dir=p_dir)
            if success:
                context["created_folder_path"] = path_created
                return True, msg, {"folder_path": path_created}
            return False, msg, {}

        # 10. Move Files
        elif atype == "move_files":
            dest = context.get("created_folder_path") or str(Path.home() / "Desktop" / "New Folder")
            sources = []
            if context.get("matched_file_path"):
                sources.append(context["matched_file_path"])
            finder_sel = self.macos_automator.get_finder_selected_files()
            if finder_sel:
                sources.extend([s for s in finder_sel if s not in sources])
            if not sources:
                latest_dl = self.macos_automator.find_latest_file("Downloads")
                if latest_dl:
                    sources.append(latest_dl)
            if not sources:
                return False, "No files found to move into folder", {}
            success, msg, moved = self.macos_automator.move_files(sources, dest)
            return success, msg, {"moved_files": moved, "destination": dest}

        # 11. System Settings & Display Brightness / Sound Volume
        elif atype == "system_settings":
            stype = (step.setting_type or "").lower()
            if "display" in stype or "brightness" in stype or "brightness" in step.description.lower():
                delta_val = step.delta if step.delta is not None else 3
                success, msg = self.macos_automator.change_display_brightness(delta=delta_val)
                return success, msg, {"setting": "displays", "action": "brightness"}
            elif "sound" in stype or "volume" in stype or "volume" in step.description.lower():
                success, msg = self.macos_automator.change_sound_volume(delta=step.delta or 5)
                return success, msg, {"setting": "sound", "action": "volume"}
            else:
                success, msg = self.macos_automator.open_system_settings_pane(stype or "general")
                return success, msg, {"setting": stype}

        # 12. System File Search (Spotlight / mdfind)
        elif atype == "system_search":
            query = step.query or "project.pdf"
            if ".pdf" in query.lower() or "latest" in query.lower():
                file_path = self._find_latest_pdf()
            else:
                file_path = self._find_local_file(query)
            if file_path:
                context["matched_file_path"] = file_path
                return True, f"Found file at {os.path.basename(file_path)}", {"file_path": file_path}
            else:
                return False, f"Could not find any local file matching '{query}' on your Mac", {}

        # 13. Read Page Content (Active Browser)
        elif atype == "read_page":
            page_text = self._extract_browser_page_text()
            if page_text:
                context["extracted_text"] = page_text
                return True, f"Extracted {len(page_text.split())} words from visible page", {"text_length": len(page_text)}
            else:
                return False, "Could not extract readable text from current browser page", {}

        # 14. Read PDF Document
        elif atype == "read_pdf":
            file_path = context.get("matched_file_path")
            if not file_path and step.query:
                if ".pdf" in step.query.lower() or "latest" in step.query.lower():
                    file_path = self._find_latest_pdf()
                else:
                    file_path = self._find_local_file(step.query)
            if not file_path:
                file_path = self._find_latest_pdf()
            if not file_path:
                return False, "No PDF file specified or found to read", {}

            doc_text = self._extract_pdf_text(file_path)
            if doc_text:
                context["extracted_text"] = doc_text
                return True, f"Read {len(doc_text.split())} words from {os.path.basename(file_path)}", {"text_length": len(doc_text), "file_path": file_path}
            else:
                return False, f"Failed to extract readable text from {os.path.basename(file_path)}", {}

        # 15. Summarize Content via Gemini
        elif atype == "summarize":
            source_text = context.get("extracted_text") or step.text or ""
            if not source_text:
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

        # 16. Create Note in Apple Notes
        elif atype == "create_note":
            note_content = step.text or ""
            if context.get("captured_photo_path"):
                photo_p = context["captured_photo_path"]
                photo_f = context.get("captured_photo_filename", "Photo")
                if not note_content or any(k in note_content.lower() for k in ["photo", "picture", "save", "path", "where"]):
                    note_content = f"SAHAYAK Captured Photo:\nFile: {photo_f}\nPath: {photo_p}\nSaved at: {datetime_str()}"
            if not note_content:
                note_content = context.get("summary") or context.get("extracted_text") or "Note generated by SAHAYAK."

            note_title = f"SAHAYAK Note ({datetime_str()})"
            success, note_id = self._create_apple_note(note_title, note_content)
            if success:
                return True, f"Created note in Apple Notes: {note_title}", {"note_title": note_title, "note_id": note_id}
            else:
                return False, "Failed to create note in Apple Notes", {}

        # 17. Speak Spoken Feedback
        elif atype == "speak":
            msg = step.text
            if not msg:
                if context.get("extracted_text"):
                    snippet = " ".join(context["extracted_text"].split()[:25])
                    msg = f"Document content: {snippet}..."
                else:
                    msg = context.get("summary") or "Step completed."
            tts.speak(msg)
            return True, msg, {"spoken": msg}

        # 18. Explicit Keyboard Typing (Safe, verified focus)
        elif atype == "keyboard_type":
            txt = step.text or ""
            if not txt:
                return False, "No text provided to type", {}
            target = step.target_app or context.get("active_app")
            success, msg = self.macos_automator.safe_keyboard_type(txt, target_app=target)
            return success, msg, {"typed_text": txt, "target_app": target}

        # 19. Mouse Cursor Click on UI Element / Button
        elif atype in ("click_element", "click_button", "click"):
            target_el = step.target_ui_element or step.text
            c_type = step.click_type or "single"
            btn = step.button or "left"
            res = self.mouse_controller.click_element(
                target_element=target_el,
                click_type=c_type,
                button=btn,
                x=step.x,
                y=step.y,
            )
            is_success = res.get("status") == "success"
            msg = res.get("spoken_feedback", f"Clicked {target_el or 'element'}")
            return is_success, msg, res

        # 20. Mouse Double Click
        elif atype == "double_click":
            target_el = step.target_ui_element or step.text
            res = self.mouse_controller.click_element(
                target_element=target_el,
                click_type="double",
                button="left",
                x=step.x,
                y=step.y,
            )
            is_success = res.get("status") == "success"
            msg = res.get("spoken_feedback", f"Double clicked {target_el or 'element'}")
            return is_success, msg, res

        # 21. Mouse Right Click
        elif atype == "right_click":
            target_el = step.target_ui_element or step.text
            res = self.mouse_controller.click_element(
                target_element=target_el,
                click_type="right",
                button="right",
                x=step.x,
                y=step.y,
            )
            is_success = res.get("status") == "success"
            msg = res.get("spoken_feedback", f"Right clicked {target_el or 'element'}")
            return is_success, msg, res

        # 22. Move Mouse Cursor
        elif atype in ("move_mouse", "mouse_control"):
            target_el = step.target_ui_element or step.text
            res = self.mouse_controller.move_mouse(target=target_el, x=step.x, y=step.y)
            is_success = res.get("status") == "success"
            msg = res.get("spoken_feedback", f"Moved cursor to {target_el or 'target'}")
            return is_success, msg, res

        # 23. Default / Unrecognized
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

    def _find_latest_pdf(self) -> typing.Optional[str]:
        """Finds the most recently modified PDF file on the Mac using Spotlight / mdfind."""
        try:
            home = str(Path.home())
            cmd = ["mdfind", "-onlyin", home, "kMDItemContentType == 'com.adobe.pdf'"]
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=4)
            paths = [p for p in r.stdout.strip().splitlines() if p.strip() and os.path.exists(p)]
            if not paths:
                r2 = subprocess.run(["mdfind", "kMDItemContentType == 'com.adobe.pdf'"], capture_output=True, text=True, timeout=4)
                paths = [p for p in r2.stdout.strip().splitlines() if p.strip() and os.path.exists(p)]
            if paths:
                paths.sort(key=lambda p: os.path.getmtime(p), reverse=True)
                return paths[0]
        except Exception as e:
            logger.warning(f"Error finding latest PDF: {e}")
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