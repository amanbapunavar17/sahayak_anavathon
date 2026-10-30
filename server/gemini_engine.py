"""
SAHAYAK — Google Gemini Multi-Model Resilient AI Engine
Tagline: Your Voice. Your Freedom.
Platform: macOS (Apple Silicon M4)

Features:
  - Multi-model automatic failover across official Gemini Flash models
    (gemini-3.8-flash -> gemini-3.5-flash -> gemini-3.5-flash-lite -> gemini-flash-lite-latest)
  - Real conversational AI responses (general knowledge, coding, learning plans, error explanations)
  - Multistep task decomposition & execution planning
  - Multimodal visual reasoning on desktop screenshots
  - Screen description for blind/low-vision users
  - Action planning with Pydantic structured output
  - Sensitive action interception (destructive action confirmation guardrail)
  - Real-time connection diagnostics (Online AI, Reconnecting, Offline)
  - Safe error masking (never exposes secrets or API keys)
"""

import base64
import json
import logging
import os
import re
import time
import typing
from datetime import datetime
from pydantic import BaseModel, Field

try:
    from intent_classifier import classify_intent, IntentType, WEBSITE_CATALOG
except ImportError:
    from server.intent_classifier import classify_intent, IntentType, WEBSITE_CATALOG

logger = logging.getLogger("sahayak-gemini")

# Official Google GenAI SDK import
try:
    from google import genai
    from google.genai import types
    _HAS_GOOGLE_GENAI = True
except ImportError:
    _HAS_GOOGLE_GENAI = False
    logger.warning("google-genai SDK not installed. Falling back to offline mode.")

# Preferred primary model and automatic fallback hierarchy
PRIMARY_MODEL_ID = "gemini-3.8-flash"
GEMINI_MODEL_ID = PRIMARY_MODEL_ID
CANDIDATE_FLASH_MODELS = [
    "gemini-3.8-flash",
    "gemini-3.5-flash",
    "gemini-3.5-flash-lite",
    "gemini-flash-lite-latest",
    "gemini-3.1-flash-lite",
]

# Sensitive keywords requiring user confirmation before execution
SENSITIVE_PATTERNS = [
    r"\bdelete\b",
    r"\bremove\b",
    r"\berase\b",
    r"\btrash\b",
    r"\bformat\b",
    r"\bpurchase\b",
    r"\bbuy\b",
    r"\bcheckout\b",
    r"\bpay\b",
    r"\bsend\s+(email|message|text|mail)\b",
    r"\bempty\s+trash\b",
    r"\buninstall\b",
    r"\bterminate\b",
    r"\bshut\s*down\b",
]


class IntentResult(BaseModel):
    corrected_command: str


class SimpleAction(BaseModel):
    command: typing.Literal["type_text", "open_url", "press_hotkey", "scroll", "escalate"]
    text: typing.Optional[str] = None
    url: typing.Optional[str] = None
    keys: typing.Optional[list[str]] = None
    amount: typing.Optional[int] = None


class AgentAction(BaseModel):
    explanation: str = "Action determined by SAHAYAK"
    command: typing.Literal[
        "click", "type_text", "keyboard_type", "open_url",
        "press_hotkey", "scroll", "wait", "describe", "ask_confirmation",
        "website_search", "browser_search", "system_search", "open_website", "open_application",
        "conversational_answer", "multistep_workflow"
    ]
    x: typing.Optional[int] = Field(default=None, ge=0, le=1000)
    y: typing.Optional[int] = Field(default=None, ge=0, le=1000)
    text: typing.Optional[str] = None
    url: typing.Optional[str] = None
    target_website: typing.Optional[str] = None
    query: typing.Optional[str] = None
    keys: typing.Optional[list[str]] = None
    amount: typing.Optional[int] = None
    is_sensitive: bool = False
    confirmation_prompt: typing.Optional[str] = None
    done: bool = False


class TaskStepPlan(BaseModel):
    step_id: int
    action_type: str
    target_app: typing.Optional[str] = None
    target_website: typing.Optional[str] = None
    query: typing.Optional[str] = None
    url: typing.Optional[str] = None
    text: typing.Optional[str] = None
    description: str
    expected_result: str


class MultiStepPlan(BaseModel):
    task_goal: str
    steps: list[TaskStepPlan]


class GeminiEngine:
    """
    Coordinates all cognitive reasoning, natural language answers,
    and multi-step action planning with resilient multi-model failover.
    """

    def __init__(self):
        self.api_key = os.getenv("GEMINI_API_KEY", "").strip()
        self.client: typing.Optional[genai.Client] = None
        self.primary_model = PRIMARY_MODEL_ID
        self.active_model = PRIMARY_MODEL_ID
        self.candidate_models = list(CANDIDATE_FLASH_MODELS)
        
        # Connection and diagnostic state
        self.connection_state = "offline"  # "online", "reconnecting", "offline"
        self.last_latency_ms: float = 0.0
        self.last_success_time: typing.Optional[float] = None
        self.last_error: typing.Optional[str] = None
        self.total_requests: int = 0
        self.total_success: int = 0
        
        self._init_client()

    def _init_client(self) -> None:
        self.api_key = os.getenv("GEMINI_API_KEY", "").strip()
        if self.api_key and _HAS_GOOGLE_GENAI:
            try:
                self.client = genai.Client(api_key=self.api_key)
                self.connection_state = "online"
                logger.info(f"GeminiEngine initialized. Candidates: {self.candidate_models}")
            except Exception as exc:
                self.last_error = f"Client init error: {exc}"
                logger.error(self.last_error)
                self.client = None
                self.connection_state = "offline"
        else:
            self.client = None
            self.connection_state = "offline"
            if not self.api_key:
                logger.info("GEMINI_API_KEY is not configured. Running in Local Offline Mode.")

    def is_available(self) -> bool:
        """Check if Gemini client is active and configured with an API key."""
        return bool(self.client and self.api_key)

    def get_diagnostics(self) -> dict:
        """Returns non-sensitive health & connectivity metrics."""
        return {
            "status": self.connection_state,
            "configured_model": self.primary_model,
            "active_model": self.active_model,
            "has_api_key": bool(self.api_key),
            "last_latency_ms": round(self.last_latency_ms, 1),
            "last_successful_request": (
                datetime.fromtimestamp(self.last_success_time).isoformat()
                if self.last_success_time else None
            ),
            "last_error": self.last_error,
            "total_requests": self.total_requests,
            "total_success": self.total_success,
            "candidate_models": self.candidate_models,
        }

    # -----------------------------------------------------------------------
    # Resilient Multi-Model Generation Helper
    # -----------------------------------------------------------------------
    def _call_with_failover(
        self,
        contents: typing.Any,
        config: typing.Optional[types.GenerateContentConfig] = None,
    ) -> str:
        """
        Executes content generation. If the current model hits quota (429) or is not found (404),
        seamlessly fails over to alternative candidate Flash models in priority order.
        """
        if not self.is_available():
            raise RuntimeError("Gemini is not configured or offline.")

        self.total_requests += 1
        t0 = time.time()
        self.connection_state = "reconnecting"

        # Determine attempt sequence: start with current active model, then others
        models_to_try = [self.active_model] + [m for m in self.candidate_models if m != self.active_model]
        last_exception = None

        for model_name in models_to_try:
            try:
                resp = self.client.models.generate_content(
                    model=model_name,
                    contents=contents,
                    config=config,
                )
                raw_text = resp.text.strip()
                self.last_latency_ms = (time.time() - t0) * 1000
                self.last_success_time = time.time()
                self.active_model = model_name
                self.connection_state = "online"
                self.last_error = None
                self.total_success += 1
                return raw_text
            except Exception as exc:
                last_exception = exc
                err_str = str(exc)
                # Check for rate-limiting, quota exhaustion, or model not available
                is_quota_or_notfound = (
                    "429" in err_str or "RESOURCE_EXHAUSTED" in err_str or
                    "404" in err_str or "NOT_FOUND" in err_str or
                    "503" in err_str
                )
                if is_quota_or_notfound:
                    logger.warning(f"Gemini model '{model_name}' hit limit/unavailable ({type(exc).__name__}). Trying next candidate...")
                    continue
                else:
                    logger.error(f"Gemini unexpected error on '{model_name}': {exc}")
                    break

        self.connection_state = "offline"
        sanitized_err = re.sub(r"key=[a-zA-Z0-9_\-]+", "key=REDACTED", str(last_exception))
        self.last_error = sanitized_err[:200]
        raise RuntimeError(f"All candidate Gemini models failed: {sanitized_err}")

    # -----------------------------------------------------------------------
    # Sensitive Action Detector Guardrail
    # -----------------------------------------------------------------------
    def detect_sensitive_operation(self, command_text: str) -> tuple[bool, str]:
        """
        Interception policy: Checks if an operation is irreversible or sensitive.
        Returns (is_sensitive, prompt_to_speak_to_user).
        """
        lower = command_text.lower()
        for pat in SENSITIVE_PATTERNS:
            if re.search(pat, lower):
                if "delete" in lower or "trash" in lower or "remove" in lower:
                    prompt = "I understood you want to delete something. Because this is permanent, please confirm: do you want me to proceed with deleting it?"
                elif "purchase" in lower or "buy" in lower or "pay" in lower:
                    prompt = "I detected a financial transaction or checkout request. Do you want me to proceed with this payment?"
                elif "send" in lower:
                    prompt = "I detected a request to send a message or email. Are you sure you want to send it now?"
                else:
                    prompt = f"You requested '{command_text}'. This action cannot be easily undone. Please confirm: should I continue?"
                return True, prompt
        return False, ""

    # -----------------------------------------------------------------------
    # Intent Interpretation & Speech Correction
    # -----------------------------------------------------------------------
    async def interpret_intent(self, raw_transcription: str, screen_context: dict) -> str:
        """
        Reconstruct the user's intended instruction from raw speech transcription,
        fixing typical speech-to-text misrecognitions in macOS context.
        """
        if not self.is_available():
            return raw_transcription.strip()

        app_name = screen_context.get("app_name", "Finder")
        prompt = (
            f"You are the Voice Command Interpreter for SAHAYAK, an accessibility assistant for blind individuals.\n"
            f"Active Application: {app_name}\n"
            f'Raw User Voice Transcription: "{raw_transcription}"\n\n'
            f"Reconstruct the actual intended computer command. Handle common speech recognition mishearings.\n"
            f"For example: 'clothes window' -> 'close window', 'right text' -> 'type text', 'safari open' -> 'open safari'.\n"
            f"If it is a multi-step task (e.g. using 'then', 'and then', 'after that', 'and save to'), keep all steps and sequence intact.\n"
            f"If it is a general question or conversational request (e.g. 'explain artificial intelligence', 'what is RAM'), keep the natural wording.\n"
            f"Return ONLY valid JSON matching this schema: {{\"corrected_command\": \"...\"}}"
        )

        try:
            raw = self._call_with_failover(
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.1,
                ),
            )
            data = json.loads(raw)
            corrected = data.get("corrected_command", "").strip()
            if corrected:
                logger.info(f"Intent corrected: '{raw_transcription}' -> '{corrected}'")
                return corrected
        except Exception as exc:
            logger.warning(f"interpret_intent failed ({exc}), using raw transcription.")

        return raw_transcription.strip()

    # -----------------------------------------------------------------------
    # Real Conversational AI Answers (General Knowledge, Questions, Advice)
    # -----------------------------------------------------------------------
    async def chat_conversational(
        self,
        user_query: str,
        screen_context: typing.Optional[dict] = None,
        ocr_blocks: typing.Optional[list[dict]] = None,
        image_b64: typing.Optional[str] = None,
        history: typing.Optional[list[dict]] = None,
    ) -> str:
        """
        Provides direct, intelligent conversational answers to user questions,
        explanations, coding advice, learning plans, or screen error diagnostics.
        """
        if not self.is_available():
            return (
                f"I understood your question: '{user_query}'. "
                "However, Gemini AI is currently operating in offline mode. "
                "Please configure a GEMINI_API_KEY in settings to enable full natural language responses."
            )

        app_ctx = screen_context or {}
        app_name = app_ctx.get("app_name", "macOS")
        tab_title = app_ctx.get("tab_title", "")
        
        # Determine if query asks about on-screen content or errors
        lower_q = user_query.lower()
        is_screen_query = any(k in lower_q for k in ["screen", "error", "this window", "on display", "what does this mean", "failing"])

        system_instruction = (
            "You are SAHAYAK, an intelligent voice-controlled AI accessibility assistant on macOS for blind and sighted users alike. "
            "Provide an accurate, engaging, vivid, and conversational spoken response to the user's question or instruction. "
            "Keep the tone friendly, confident, and direct. "
            "Directly address the user's topic or subject by name in your answer. "
            "CRITICAL FORMATTING RULE: Do not use markdown asterisks (*), hashtags (#), or bullet symbols (-) "
            "because your response is read directly aloud using native Text-to-Speech. Use natural conversational phrasing."
        )

        prompt_parts = []
        if is_screen_query and (ocr_blocks or tab_title):
            ocr_summary = ", ".join([b.get("text", "") for b in (ocr_blocks or [])[:20] if len(b.get("text", "")) > 2])
            prompt_parts.append(
                f"[CURRENT SCREEN CONTEXT]\n"
                f"Frontmost Application: {app_name}\n"
                f"Window/Tab: {tab_title}\n"
                f"Visible Text/Errors: {ocr_summary}\n"
            )

        # Include recent conversation turns if provided
        if history:
            history_text = "\n".join([f"{h.get('role', 'user').title()}: {h.get('content', '')}" for h in history[-4:]])
            prompt_parts.append(f"[CONVERSATION CONTEXT]\n{history_text}\n")

        prompt_parts.append(f"User Request: {user_query}")
        full_prompt = "\n".join(prompt_parts)

        contents = [full_prompt]
        if is_screen_query and image_b64:
            try:
                image_bytes = base64.b64decode(image_b64)
                contents.append(types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"))
            except Exception as e:
                logger.warning(f"Failed to attach image to conversational chat: {e}")

        try:
            resp_text = self._call_with_failover(
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    temperature=0.4,
                ),
            )
            # Clean any stray markdown formatting for smooth speech synthesis
            clean_text = resp_text.replace("*", "").replace("#", "").replace("`", "").strip()
            return clean_text
        except Exception as exc:
            logger.error(f"chat_conversational failed: {exc}")
            return (
                f"I encountered a temporary connection issue while processing your request: {user_query}. "
                f"Error detail: {str(exc)[:100]}."
            )

    # -----------------------------------------------------------------------
    # Multistep Task Decomposition
    # -----------------------------------------------------------------------
    async def decompose_multistep_task(
        self,
        user_instruction: str,
        screen_context: typing.Optional[dict] = None,
    ) -> list[dict]:
        """
        Decomposes complex multi-step user workflows into a sequenced list of executable actions.
        Examples:
          "Open YouTube, search for Python tutorials, summarize the beginner tutorial, and save to Notes"
          "Open Safari, then open Notes and write down my next three tasks"
        """
        app_ctx = screen_context or {}
        app_name = app_ctx.get("app_name", "Finder")

        if not self.is_available():
            # Rule-based fallback decomposition
            return self._local_decompose_task(user_instruction)

        prompt = (
            f"You are the Multi-Task Planner for SAHAYAK on macOS.\n"
            f"USER INSTRUCTION: \"{user_instruction}\"\n"
            f"Current Front Application: {app_name}\n\n"
            f"Break this user instruction down into an ordered list of concrete, executable steps.\n"
            f"Allowed action_type values:\n"
            f"  - 'open_app': Launch or switch to an app (target_app)\n"
            f"  - 'website_search': Open website and search (target_website, query)\n"
            f"  - 'browser_search': General web search (query)\n"
            f"  - 'system_search': Search local Mac files via Spotlight (query)\n"
            f"  - 'read_page': Read and extract visible text from current browser page\n"
            f"  - 'summarize': Summarize extracted text using Gemini\n"
            f"  - 'create_note': Create a new note in Apple Notes (text, title)\n"
            f"  - 'speak': Announce spoken feedback to the user (text)\n"
            f"  - 'keyboard_type': Type text into active application (text)\n"
            f"  - 'press_hotkey': Press shortcut keys (keys)\n\n"
            f"Return ONLY valid JSON matching this schema:\n"
            f"{{\n"
            f"  \"task_goal\": \"Brief description\",\n"
            f"  \"steps\": [\n"
            f"    {{\n"
            f"      \"step_id\": 1,\n"
            f"      \"action_type\": \"website_search\",\n"
            f"      \"target_website\": \"youtube\",\n"
            f"      \"query\": \"Python tutorials\",\n"
            f"      \"text\": null,\n"
            f"      \"target_app\": null,\n"
            f"      \"description\": \"Search YouTube for Python tutorials\",\n"
            f"      \"expected_result\": \"YouTube search results displayed\"\n"
            f"    }}\n"
            f"  ]\n"
            f"}}"
        )

        try:
            raw_json = self._call_with_failover(
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.1,
                ),
            )
            data = json.loads(raw_json)
            steps = data.get("steps", [])
            if steps:
                logger.info(f"Decomposed '{user_instruction}' into {len(steps)} steps.")
                return steps
        except Exception as exc:
            logger.warning(f"Gemini task decomposition failed ({exc}), using local rule decomposition.")

        return self._local_decompose_task(user_instruction)

    def _local_decompose_task(self, user_instruction: str) -> list[dict]:
        """Local heuristic multi-step splitter when Gemini is unreachable."""
        # Split on sequential conjunctions: "then", "and then", "after that", commas, and sequential 'and'
        raw_parts = re.split(
            r",\s*(?:and\s+)?then\s+|,?\s+then\s+|\s+after\s+that\s+|;\s*|,\s*and\s+|\s+and\s+(?=write|save|open|search|find|summarize|read|tell)",
            user_instruction,
            flags=re.IGNORECASE
        )
        steps = []
        step_id = 1

        for part in raw_parts:
            part = part.strip()
            if not part:
                continue

            lower_p = part.lower()
            if "youtube" in lower_p and any(s in lower_p for s in ["search", "find"]):
                m = re.search(r"search\s+(?:youtube\s+for|for)\s+(.+)", lower_p)
                q = m.group(1) if m else "Python tutorials"
                steps.append({
                    "step_id": step_id,
                    "action_type": "website_search",
                    "target_website": "youtube",
                    "query": q,
                    "description": f"Search YouTube for '{q}'",
                    "expected_result": "Search results displayed on YouTube",
                })
            elif any(w in lower_p for w in ["write down", "save to notes", "write to notes", "note down", "save note"]) or ("notes" in lower_p and any(w in lower_p for w in ["write", "save", "tasks"])):
                m = re.search(r"(?:write\s+down|save\s+to\s+notes|save|write)\s+(.+)", lower_p)
                note_text = m.group(1) if m else "SAHAYAK automated note"
                steps.append({
                    "step_id": step_id,
                    "action_type": "create_note",
                    "target_app": "Notes",
                    "text": note_text,
                    "description": f"Save note: '{note_text}'",
                    "expected_result": "Note created in Apple Notes",
                })
            elif "summarize" in lower_p:
                steps.append({
                    "step_id": step_id,
                    "action_type": "summarize",
                    "description": "Summarize content",
                    "expected_result": "Summary synthesized",
                })
            elif "open" in lower_p:
                m_app = re.search(r"open\s+(?:the\s+)?([a-zA-Z0-9\s]+)", lower_p)
                app = m_app.group(1).strip() if m_app else "Safari"
                steps.append({
                    "step_id": step_id,
                    "action_type": "open_app",
                    "target_app": app.title(),
                    "description": f"Open {app.title()}",
                    "expected_result": f"{app.title()} brought to front",
                })
            else:
                steps.append({
                    "step_id": step_id,
                    "action_type": "speak",
                    "text": f"Completed: {part}",
                    "description": part,
                    "expected_result": "Feedback spoken",
                })
            step_id += 1

        return steps

    # -----------------------------------------------------------------------
    # Screen Description for Visually Impaired Users
    # -----------------------------------------------------------------------
    async def describe_screen(
        self,
        image_b64: str,
        app_context: dict,
        ocr_blocks: list[dict],
        user_query: str = "What is on my screen?",
    ) -> str:
        """
        Provides a natural, vivid, structured spoken description of what is currently
        visible on the screen tailored for blind and low-vision individuals.
        """
        if not self.is_available():
            return self._local_describe_screen(app_context, ocr_blocks, user_query)

        app_name = app_context.get("app_name", "Unknown")
        tab_title = app_context.get("tab_title", "")
        tab_url = app_context.get("tab_url", "")
        ocr_summary = ", ".join([b.get("text", "") for b in ocr_blocks[:15]])

        system_instruction = (
            "You are SAHAYAK, a voice-first computer assistant for blind and low-vision individuals. "
            "You must describe the computer screen naturally, concisely, and informatively aloud. "
            "Prioritize: 1. Which application is currently in front. "
            "2. The main headline or content displayed. "
            "3. Key actionable buttons, links, or inputs available. "
            "4. Any error messages or dialogs. "
            "Keep the response natural, conversational, and direct for speech synthesis (2 to 4 sentences). "
            "Do not use markdown formatting, asterisks, bullet lists, or tables because this will be read aloud."
        )

        prompt_text = (
            f"User asked: '{user_query}'\n"
            f"Front Application: {app_name}\n"
            f"Tab Title / URL: {tab_title} {tab_url}\n"
            f"Detected Text on screen: {ocr_summary}\n\n"
            f"Describe the visible screen content clearly and informatively for someone who cannot see it."
        )

        try:
            contents = [prompt_text]
            if image_b64:
                image_bytes = base64.b64decode(image_b64)
                contents.append(types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"))

            raw_desc = self._call_with_failover(
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    temperature=0.2,
                ),
            )
            desc = raw_desc.replace("*", "").replace("#", "").strip()
            return desc
        except Exception as exc:
            logger.error(f"describe_screen Gemini error: {exc}")
            return self._local_describe_screen(app_context, ocr_blocks, user_query)

    def _local_describe_screen(self, app_context: dict, ocr_blocks: list[dict], user_query: str) -> str:
        """Local fallback when Gemini is unavailable."""
        app = app_context.get("app_name", "Finder")
        title = app_context.get("tab_title", "")
        texts = [b.get("text", "") for b in ocr_blocks[:10] if len(b.get("text", "")) > 3]

        if not texts:
            return f"You are currently in {app}. No readable text was detected on the front screen."

        summary_snippets = "; ".join(texts[:5])
        return (
            f"You are currently in {app}" + (f" on {title}" if title else "") +
            f". Detected text includes: {summary_snippets}. Local offline assistive mode is active."
        )

    # -----------------------------------------------------------------------
    # Action Planning (Single-Action Control)
    # -----------------------------------------------------------------------
    async def plan_action(
        self,
        user_text: str,
        image_b64: str,
        app_context: dict,
        ocr_blocks: list[dict],
        step_number: int = 1,
    ) -> AgentAction:
        """
        Decides the next physical or cognitive action.
        """
        # Step 0: Check sensitive operation confirmation
        is_sensitive, confirm_prompt = self.detect_sensitive_operation(user_text)
        if is_sensitive:
            return AgentAction(
                explanation="Operation involves sensitive or irreversible action.",
                command="ask_confirmation",
                is_sensitive=True,
                confirmation_prompt=confirm_prompt,
                done=False,
            )

        if not self.is_available():
            return self._local_rule_action(user_text, app_context, ocr_blocks)

        app_name = app_context.get("app_name", "Finder")
        prompt = (
            f"You are the Autonomous Accessibility Agent for SAHAYAK on macOS.\n"
            f"TASK: '{user_text}'\n"
            f"Active Application: {app_name}\n"
            f"Step: {step_number}\n\n"
            f"Identify the user's intent and plan the single next action to advance the task.\n"
            f"DISTINCT SEARCH & NAVIGATION COMMANDS (Choose the most specific):\n"
            f"  - website_search: Open a specific website (e.g. YouTube, Google, Wikipedia, GitHub, Amazon) and search within it.\n"
            f"      Required: target_website (e.g. 'youtube'), query (e.g. 'Python tutorials').\n"
            f"      CRITICAL: Never use type_text or Spotlight for website-specific searches!\n"
            f"  - browser_search: General web/internet search across search engines.\n"
            f"      Required: query (e.g. 'best Python courses').\n"
            f"  - system_search: Search for files, documents, or content locally on this Mac using macOS Spotlight.\n"
            f"      Required: query (e.g. 'project.pdf'). Never use a browser for local Mac file search!\n"
            f"  - open_website: Direct navigation to a website URL or domain.\n"
            f"      Required: url (e.g. 'https://www.youtube.com').\n"
            f"  - open_application: Launch a local macOS application (e.g. Calculator, Notes).\n"
            f"      Required: text (e.g. 'Calculator').\n"
            f"  - click: x and y in [0, 1000] normalized space.\n"
            f"  - keyboard_type: text to type into active input.\n"
            f"  - press_hotkey: list of keys like ['command', 'n'] or ['command', 'w'].\n"
            f"  - scroll: amount (e.g. -12 for down, 12 for up).\n"
            f"  - describe: explain screen content in text field.\n"
            f"  - wait: brief pause.\n"
            f"Set done=true if task is finished.\n"
            f"Output JSON matching AgentAction schema."
        )

        try:
            contents = [prompt]
            if image_b64:
                image_bytes = base64.b64decode(image_b64)
                contents.append(types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"))

            raw = self._call_with_failover(
                contents=contents,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.1,
                ),
            )
            data = json.loads(raw)
            if isinstance(data, dict):
                if "action" in data and "command" not in data:
                    data["command"] = data["action"]
                if "explanation" not in data or not data["explanation"]:
                    data["explanation"] = f"Executing {data.get('command', 'action')}"
            return AgentAction(**data)
        except Exception as exc:
            logger.error(f"plan_action failed: {exc}")
            return self._local_rule_action(user_text, app_context, ocr_blocks)

    def _local_rule_action(self, user_text: str, app_context: dict, ocr_blocks: list[dict]) -> AgentAction:
        """Local rule-based fallback when offline or no API key, separating search intents."""
        intent_res = classify_intent(user_text)

        if intent_res.intent == IntentType.DESCRIBE_SCREEN:
            desc = self._local_describe_screen(app_context, ocr_blocks, user_text)
            return AgentAction(
                explanation="Local description of screen content",
                command="describe",
                text=desc,
                done=True,
            )

        if intent_res.intent == IntentType.WEBSITE_SEARCH:
            return AgentAction(
                explanation=intent_res.explanation,
                command="website_search",
                target_website=intent_res.target_website,
                query=intent_res.query,
                url=intent_res.url,
                done=True,
            )

        if intent_res.intent == IntentType.BROWSER_SEARCH:
            return AgentAction(
                explanation=intent_res.explanation,
                command="browser_search",
                query=intent_res.query,
                url=intent_res.url,
                done=True,
            )

        if intent_res.intent == IntentType.SYSTEM_SEARCH:
            return AgentAction(
                explanation=intent_res.explanation,
                command="system_search",
                query=intent_res.query,
                done=True,
            )

        if intent_res.intent == IntentType.OPEN_WEBSITE:
            return AgentAction(
                explanation=intent_res.explanation,
                command="open_website",
                url=intent_res.url,
                done=True,
            )

        if intent_res.intent == IntentType.OPEN_APPLICATION:
            return AgentAction(
                explanation=intent_res.explanation,
                command="open_application",
                text=intent_res.target_app,
                done=True,
            )

        # Scrolling
        if "scroll down" in user_text.lower():
            return AgentAction(explanation="Scrolling down", command="scroll", amount=-12, done=True)
        if "scroll up" in user_text.lower():
            return AgentAction(explanation="Scrolling up", command="scroll", amount=12, done=True)

        # Close / Switch
        if "close" in user_text.lower():
            return AgentAction(explanation="Closing window", command="press_hotkey", keys=["command", "w"], done=True)

        return AgentAction(
            explanation="Unrecognized local command",
            command="describe",
            text=f"I understood '{user_text}'. In local offline mode, say 'search YouTube for music', 'search web for news', 'find file project.pdf on my Mac', 'open browser', 'scroll down', or provide a GEMINI_API_KEY for advanced reasoning.",
            done=True,
        )


# Global Singleton
gemini_engine = GeminiEngine()
