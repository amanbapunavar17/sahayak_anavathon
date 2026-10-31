"""
SAHAYAK — Session & Language Context Manager
Maintains global session state including current language preferences.
Supported languages:
  - 'en-US' (English, default) -> Samantha
  - 'kn' / 'kn-IN' (Kannada) -> Soumya
  - 'hi' / 'hi-IN' (Hindi) -> Lekha
"""

import logging
import typing

logger = logging.getLogger("sahayak-session")


class SessionContext:
    _language: str = "en-US"

    @classmethod
    def get_language(cls) -> str:
        """Returns the current active BCP-47 language code."""
        return cls._language

    @classmethod
    def set_language(cls, lang: str) -> None:
        """Sets the active session language."""
        if not lang:
            return
        clean_lang = lang.strip()
        cls._language = clean_lang
        logger.info(f"SessionContext: language updated to '{cls._language}'")

    @classmethod
    def is_kannada(cls, lang: typing.Optional[str] = None) -> bool:
        check = (lang or cls._language).strip().lower()
        return check in ("kn", "kn-in", "kn_in", "kannada")

    @classmethod
    def get_language_prompt_instruction(cls, lang: typing.Optional[str] = None) -> str:
        """
        Returns the multilingual system instruction to prepend to Gemini prompts
        when operating in non-English modes.
        """
        target = (lang or cls._language).strip().lower()
        if cls.is_kannada(target):
            return "You are a multilingual assistant. Respond only in Kannada unless the user asks for a different language."
        elif target in ("hi", "hi-in", "hi_in", "hindi"):
            return "You are a multilingual assistant. Respond only in Hindi unless the user asks for a different language."
        return ""

