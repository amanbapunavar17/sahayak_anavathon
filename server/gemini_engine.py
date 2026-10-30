"""
SAHAYAK — Google Gemini 3.8 Flash AI Engine
Replaces legacy paid APIs (Amazon Nova Lite, Nova Pro, OpenRouter) with
the official Google Gemini API (model: gemini-3.8-flash) on the available Free Tier.

Features:
  - Intent interpretation & speech correction
  - Multimodal visual reasoning on screenshots
  - Screen description for blind/low-vision users
  - Action planning with Pydantic structured output
  - Sensitive action interception (destructive action confirmation guardrail)
  - Resilient error handling (graceful fallback if key missing or quota exhausted)
"""

import json
import logging
import os
import re
import typing
from pydantic import BaseModel, Field

from intent_classifier import classify_intent, IntentType, WEBSITE_CATALOG

logger = logging.getLogger("sahayak-gemini")

# Official Google GenAI SDK import
try:
    from google import genai
    from google.genai import types
    _HAS_GOOGLE_GENAI = True
except ImportError:
    _HAS_GOOGLE_GENAI = False
    logger.warning("google-genai SDK not installed. Falling back to offline mode.")

# Preferred & verified model identifier
GEMINI_MODEL_ID = "gemini-3.8-flash"

# Sensitive keywords that require user confirmation before execution
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
    explanation: str
    command: typing.Literal[
        "click", "type_text", "keyboard_type", "open_url",
        "press_hotkey", "scroll", "wait", "describe", "ask_confirmation",
        "website_search", "browser_search", "system_search", "open_website", "open_application"
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


class CriticVerdict(BaseModel):
    approved: bool
    reason: str
    corrected_x: typing.Optional[int] = None
    corrected_y: typing.Optional[int] = None


class GeminiEngine:
    """
    Coordinates all cognitive reasoning through Gemini 3.8 Flash.
    """

    def __init__(self):
        self.api_key = os.getenv("GEMINI_API_KEY", "").strip()
        self.client: typing.Optional[genai.Client] = None
        self.model_id = GEMINI_MODEL_ID
        self._init_client()

    def _init_client(self) -> None:
        self.api_key = os.getenv("GEMINI_API_KEY", "").strip()
        if self.api_key and _HAS_GOOGLE_GENAI:
            try:
                self.client = genai.Client(api_key=self.api_key)
                logger.info(f"GeminiEngine initialized successfully with model {self.model_id}")
            except Exception as exc:
                logger.error(f"Failed to initialize Gemini client: {exc}")
                self.client = None
        else:
            self.client = None
            if not self.api_key:
                logger.info("GEMINI_API_KEY is not set. Operating in Local Offline Mode.")

    def is_available(self) -> bool:
        """Check if Gemini client is active and configured with an API key."""
        return bool(self.client and self.api_key)

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
                # Formulate natural confirmation prompt
                if "delete" in lower or "trash" in lower or "remove" in lower:
                    prompt = f"I understood you want to delete something. Because this is permanent, please confirm: do you want me to proceed with deleting it?"
                elif "purchase" in lower or "buy" in lower or "pay" in lower:
                    prompt = f"I detected a financial transaction or checkout request. Do you want me to proceed with this payment?"
                elif "send" in lower:
                    prompt = f"I detected a request to send a message or email. Are you sure you want to send it now?"
                else:
                    prompt = f"You requested '{command_text}'. This action cannot be easily undone. Please confirm: should I continue?"
                return True, prompt
        return False, ""

    # -----------------------------------------------------------------------
    # Intent Interpretation
    # -----------------------------------------------------------------------
    async def interpret_intent(self, raw_transcription: str, screen_context: dict) -> str:
        """
        Reconstruct the user's intended instruction from raw speech transcription,
        fixing typical speech-to-text misrecognitions in the context of macOS.
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
            f"Return ONLY valid JSON matching this schema: {{\"corrected_command\": \"...\"}}"
        )

        try:
            resp = self.client.models.generate_content(
                model=self.model_id,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.1,
                ),
            )
            raw = resp.text.strip()
            data = json.loads(raw)
            corrected = data.get("corrected_command", "").strip()
            if corrected:
                logger.info(f"Intent corrected: '{raw_transcription}' -> '{corrected}'")
                return corrected
        except Exception as exc:
            logger.warning(f"interpret_intent failed ({exc}), using raw transcription.")

        return raw_transcription.strip()

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
            # Local fallback description using OCR
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
            # Prepare image part for Gemini
            image_bytes = None
            if image_b64:
                import base64
                image_bytes = base64.b64decode(image_b64)

            contents = [prompt_text]
            if image_bytes:
                contents.append(
                    types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg")
                )

            resp = self.client.models.generate_content(
                model=self.model_id,
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    temperature=0.2,
                ),
            )
            desc = resp.text.strip()
            # Clean out any leftover markdown asterisks for spoken clarity
            desc = desc.replace("*", "").replace("#", "").strip()
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
    # Action Planning (Simple vs Visual Loop)
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
            # Return rule-based action
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
            f"  - scroll: amount (e.g. -10 for down, 10 for up).\n"
            f"  - describe: explain screen content in text field.\n"
            f"  - wait: brief pause.\n"
            f"Set done=true if task is finished.\n"
            f"Output JSON matching AgentAction schema."
        )

        try:
            image_bytes = None
            if image_b64:
                import base64
                image_bytes = base64.b64decode(image_b64)

            contents = [prompt]
            if image_bytes:
                contents.append(
                    types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg")
                )

            resp = self.client.models.generate_content(
                model=self.model_id,
                contents=contents,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.1,
                ),
            )
            raw = resp.text.strip()
            data = json.loads(raw)
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

