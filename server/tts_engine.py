"""
SAHAYAK — Text-To-Speech (TTS) Engine
Uses macOS native 'say' utility and NSSpeechSynthesizer.
100% Free, Offline, Low-latency spoken feedback for blind and low-vision users.
"""

import logging
import re
import os
import queue
import subprocess
import threading
import typing

logger = logging.getLogger("sahayak-tts")

VOICE_MAP: dict[str, str] = {
    "en": "Samantha",
    "en-us": "Samantha",
    "en_us": "Samantha",
    "english": "Samantha",
    "kn": "Soumya",
    "kn-in": "Soumya",
    "kn_in": "Soumya",
    "kannada": "Soumya",
    "hi": "Lekha",
    "hi-in": "Lekha",
    "hi_in": "Lekha",
    "hindi": "Lekha",
}


def sanitize_speech_text(text: str, voice: str = "Samantha") -> str:
    """
    Cleans raw AI response text before speech synthesis so that:
    1. Markdown formatting is stripped (bold, italics, code, headings, URLs).
    2. Punctuation that macOS speech voices pronounce literally as words
       (e.g. Soumya/Lekha pronouncing '?' as 'question mark' or '??' as 'question mark question mark')
       is cleanly removed or replaced with natural speech pauses.
    3. Trailing and internal question marks/exclamation marks are converted to natural pauses.
    """
    if not text:
        return ""
    t = text.strip()
    # Strip markdown syntax
    t = re.sub(r"\*\*([^*]+)\*\*", r"\1", t)
    t = re.sub(r"\*([^*]+)\*", r"\1", t)
    t = re.sub(r"`([^`]+)`", r"\1", t)
    t = re.sub(r"#{1,6}\s*", "", t)
    t = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", t)

    is_indic = voice in ("Soumya", "Lekha") or any("\u0c80" <= ch <= "\u0cff" for ch in t) or any("\u0900" <= ch <= "\u097f" for ch in t)

    if is_indic:
        # macOS Indic voices (Soumya for Kannada, Lekha for Hindi) pronounce
        # '?' literally as the English words "question mark" and '??' as "question mark question mark".
        # We replace all question marks and exclamation marks with a soft comma pause or period.
        t = re.sub(r"[?!⁇¿]+", ", ", t)
        t = re.sub(r"[#*_~`^<>|\\/]", " ", t)
        t = re.sub(r'["\']', "", t)
    else:
        # For English voices, remove trailing/repeated question marks and symbols
        t = re.sub(r"[?!⁇¿]+$", "", t)
        t = re.sub(r"[?!⁇¿]{2,}", ".", t)
        t = re.sub(r"[#*_~`^<>|\\]", " ", t)

    # Collapse repeated pauses/commas and whitespace
    t = re.sub(r",\s*,+", ",", t)
    t = re.sub(r"\.\s*\.+", ".", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def resolve_voice(
    voice: typing.Optional[str] = None,
    language: typing.Optional[str] = None,
    default_voice: str = "Samantha",
) -> str:
    """Resolves the best macOS speech synthesis voice name."""
    if voice:
        return voice
    if language:
        return VOICE_MAP.get(language.strip().lower(), default_voice)
    return default_voice


class TTSEngine:
    """
    Thread-safe, non-blocking Speech Synthesis engine.
    Queues spoken messages to avoid overlapping audio and allows
    instant cancellation when a user interrupts or cancels.
    """

    def __init__(self, default_voice: str = "Samantha", default_rate: int = 200):
        self.default_voice = os.getenv("SAHAYAK_TTS_VOICE", default_voice)
        self.default_rate = int(os.getenv("SAHAYAK_TTS_RATE", default_rate))
        self.current_language: str = os.getenv("SAHAYAK_LANGUAGE", "en-US")
        self._speech_queue: queue.Queue = queue.Queue()
        self._current_process: typing.Optional[subprocess.Popen] = None
        self._lock = threading.Lock()
        self._running = True
        self._worker_thread = threading.Thread(
            target=self._speech_worker, name="SahayakTTSWorker", daemon=True
        )
        self._worker_thread.start()
        logger.info(
            f"TTS Engine initialized with voice={self.default_voice}, rate={self.default_rate}, language={self.current_language}"
        )

    def set_language(self, language: str) -> None:
        """Sets the active spoken language for the TTS engine."""
        self.current_language = language
        logger.info(f"TTS Engine active language set to: {language} (voice: {self.get_voice_for_language(language)})")

    def get_voice_for_language(self, language: typing.Optional[str] = None) -> str:
        lang = language or self.current_language
        return resolve_voice(language=lang, default_voice=self.default_voice)

    def speak(
        self,
        text: str,
        voice: typing.Optional[str] = None,
        rate: typing.Optional[int] = None,
        interrupt: bool = False,
        language: typing.Optional[str] = None,
    ) -> None:
        """
        Queue text to be spoken aloud.
        If interrupt is True, stops any currently playing audio and clears queue.
        Supports language-specific voice routing (e.g., 'kn' -> 'Soumya').
        """
        if not text or not text.strip():
            return

        v = resolve_voice(
            voice=voice,
            language=language or self.current_language,
            default_voice=self.default_voice,
        )
        # Clean text specifically for speech so voices never speak "question mark"
        clean_text = sanitize_speech_text(text, voice=v)
        if not clean_text:
            return

        r = rate or self.default_rate

        if interrupt:
            self.stop()

        self._speech_queue.put((clean_text, v, r))
        logger.info(f"TTS Queued: '{clean_text[:60]}...' [voice={v}]")

    def speak_sync(
        self,
        text: str,
        voice: typing.Optional[str] = None,
        rate: typing.Optional[int] = None,
        language: typing.Optional[str] = None,
    ) -> None:
        """Speak immediately and block until finished (useful for startup/shutdown cues)."""
        if not text or not text.strip():
            return
        v = resolve_voice(
            voice=voice,
            language=language or self.current_language,
            default_voice=self.default_voice,
        )
        clean_text = sanitize_speech_text(text, voice=v)
        if not clean_text:
            return
        r = rate or self.default_rate
        try:
            subprocess.run(
                ["say", "-v", v, "-r", str(r), clean_text],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception as exc:
            logger.warning(f"speak_sync error: {exc}")

    def stop(self) -> None:
        """Interrupt and silence any ongoing speech and flush queue."""
        with self._lock:
            # Drain queue
            try:
                while True:
                    self._speech_queue.get_nowait()
                    self._speech_queue.task_done()
            except queue.Empty:
                pass

            # Terminate active process
            if self._current_process and self._current_process.poll() is None:
                try:
                    self._current_process.terminate()
                except Exception as exc:
                    logger.debug(f"Process terminate exception: {exc}")
                self._current_process = None
        logger.info("TTS silenced and queue flushed.")

    def _speech_worker(self) -> None:
        """Background worker thread draining the speech queue."""
        while self._running:
            try:
                item = self._speech_queue.get(timeout=0.5)
            except queue.Empty:
                continue

            text, voice, rate = item
            try:
                with self._lock:
                    self._current_process = subprocess.Popen(
                        ["say", "-v", voice, "-r", str(rate), text],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                self._current_process.wait()
            except Exception as exc:
                logger.error(f"TTS playback error: {exc}")
            finally:
                with self._lock:
                    self._current_process = None
                self._speech_queue.task_done()

    def get_available_voices(self) -> list[dict]:
        """Query available macOS native voices."""
        voices = []
        try:
            res = subprocess.run(["say", "-v", "?"], capture_output=True, text=True, timeout=3)
            for line in res.stdout.strip().splitlines():
                parts = line.split("#")
                left = parts[0].strip()
                tokens = left.split()
                if len(tokens) >= 2:
                    name = " ".join(tokens[:-1])
                    locale = tokens[-1]
                    example = parts[1].strip() if len(parts) > 1 else ""
                    voices.append({"name": name, "locale": locale, "example": example})
        except Exception as exc:
            logger.warning(f"Could not list voices: {exc}")
            voices = [{"name": "Samantha", "locale": "en_US", "example": "Hello!"}]
        return voices


# Global Singleton Instance
tts = TTSEngine()

