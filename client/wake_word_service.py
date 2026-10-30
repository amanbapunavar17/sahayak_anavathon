"""
SAHAYAK — Global Wake Word & Voice Interaction Service
Tagline: Your Voice. Your Freedom.
Platform: macOS (Apple Silicon M4)

Listens persistently in the background across all macOS apps for:
  "HELLO SAHAY" (and "HELLO SAHAYAK")

Privacy & Efficiency Architecture:
  - Rolling RAM ring-buffer (zero disk writes, zero permanent recordings)
  - Energy threshold VAD (Voice Activity Detection) to avoid idle CPU burn
  - Instant activation chime (/System/Library/Sounds/Tink.aiff)
  - Seamless handoff to instruction transcription and execution
  - Thread-safe pause, resume, and status controls
"""

import io
import json
import logging
import os
import re
import subprocess
import sys
import threading
import time
import typing
import wave
from pathlib import Path

# Add project root to sys.path
_PROJECT_DIR = Path(__file__).resolve().parent.parent
if str(_PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(_PROJECT_DIR))
_SERVER_DIR = _PROJECT_DIR / "server"
if str(_SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(_SERVER_DIR))

try:
    from stt_engine import stt
except ImportError:
    from server.stt_engine import stt

logger = logging.getLogger("sahayak-wakeword")

WAKE_PATTERNS = [
    r"\bhello\s+sahay\b",
    r"\bhello\s+sahayak\b",
    r"\bhey\s+sahay\b",
    r"\bhey\s+sahayak\b",
    r"\bhi\s+sahay\b",
    r"\bhi\s+sahayak\b",
    r"\bsahay\b",
    r"\bsahayak\b",
]

ACTIVATION_SOUNDS = [
    "/System/Library/Sounds/Tink.aiff",
    "/System/Library/Sounds/Pop.aiff",
    "/System/Library/Sounds/Ping.aiff",
]


def play_chime(sound_path: typing.Optional[str] = None) -> None:
    """Plays an instant activation audio cue via macOS afplay."""
    chosen = sound_path or ACTIVATION_SOUNDS[0]
    for s in [chosen] + ACTIVATION_SOUNDS:
        if os.path.exists(s):
            try:
                subprocess.Popen(["afplay", s], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return
            except Exception:
                pass


def is_wake_word_in_text(text: str) -> bool:
    """Checks if text contains 'HELLO SAHAY' or variants."""
    lower = text.lower().strip()
    return any(re.search(pat, lower) for pat in WAKE_PATTERNS)


def extract_command_after_wake_word(text: str) -> str:
    """Strips the wake word prefix to extract the trailing instruction if spoken in one breath."""
    lower = text.lower().strip()
    for pat in WAKE_PATTERNS:
        m = re.search(pat, lower)
        if m:
            after = text[m.end():].strip().lstrip(",.?! ")
            if after:
                return after
    return ""


class WakeWordService:
    """
    Persistent background audio listener for macOS.
    """

    def __init__(
        self,
        on_wake: typing.Optional[typing.Callable[[], None]] = None,
        on_command: typing.Optional[typing.Callable[[str], None]] = None,
        sample_rate: int = 16000,
        chunk_seconds: float = 2.0,
    ):
        self.on_wake = on_wake
        self.on_command = on_command
        self.sample_rate = sample_rate
        self.chunk_seconds = chunk_seconds
        
        self.is_running = False
        self.is_paused = False
        self.mic_status = "idle"  # "idle", "listening_wakeword", "listening_command", "paused", "error"
        
        self._thread: typing.Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        
        # Call tracking
        self.total_triggers = 0
        self.last_trigger_time: typing.Optional[float] = None

    def start(self) -> None:
        """Starts background wake-word monitoring thread."""
        with self._lock:
            if self.is_running:
                return
            self.is_running = True
            self.is_paused = False
            self.mic_status = "listening_wakeword"
            self._stop_event.clear()
            self._thread = threading.Thread(target=self._monitor_loop, name="SahayakWakeWordService", daemon=True)
            self._thread.start()
            logger.info("WakeWordService started. Monitoring for 'HELLO SAHAY'...")

    def stop(self) -> None:
        """Stops background audio monitoring cleanly."""
        with self._lock:
            if not self.is_running:
                return
            self.is_running = False
            self.mic_status = "idle"
            self._stop_event.set()
        logger.info("WakeWordService stopped.")

    def pause(self) -> None:
        """Mutes / pauses microphone monitoring."""
        with self._lock:
            self.is_paused = True
            self.mic_status = "paused"
            logger.info("Microphone paused / muted.")

    def resume(self) -> None:
        """Resumes microphone monitoring."""
        with self._lock:
            self.is_paused = False
            self.mic_status = "listening_wakeword"
            logger.info("Microphone resumed.")

    def trigger_wake(self, command: str = "") -> None:
        """
        Manually trigger wake activation (e.g. via Option+Space global hotkey
        or automated testing).
        """
        self.total_triggers += 1
        self.last_trigger_time = time.time()
        play_chime()
        if self.on_wake:
            try:
                self.on_wake()
            except Exception as e:
                logger.error(f"on_wake callback error: {e}")

        if command and self.on_command:
            try:
                self.on_command(command)
            except Exception as e:
                logger.error(f"on_command callback error: {e}")

    def get_status(self) -> dict:
        """Returns microphone & wake-word health diagnostics."""
        return {
            "running": self.is_running,
            "paused": self.is_paused,
            "mic_status": self.mic_status,
            "wake_phrase": "HELLO SAHAY",
            "total_triggers": self.total_triggers,
            "last_trigger_time": self.last_trigger_time,
        }

    def _monitor_loop(self) -> None:
        """
        Continuous local audio monitoring loop.
        Uses speech_recognition or sounddevice for local capture.
        """
        try:
            import speech_recognition as sr
            recognizer = sr.Recognizer()
            recognizer.energy_threshold = 300
            recognizer.dynamic_energy_threshold = True
            recognizer.pause_threshold = 0.8
        except Exception as e:
            logger.warning(f"speech_recognition init failed: {e}. Running in standby mode.")
            while not self._stop_event.is_set():
                time.sleep(1)
            return

        while not self._stop_event.is_set():
            if self.is_paused:
                time.sleep(0.5)
                continue

            try:
                with sr.Microphone(sample_rate=self.sample_rate) as source:
                    # Adjust ambient noise periodically
                    recognizer.adjust_for_ambient_noise(source, duration=0.4)
                    self.mic_status = "listening_wakeword"

                    while not self._stop_event.is_set() and not self.is_paused:
                        try:
                            # Listen for short phrase
                            audio = recognizer.listen(source, timeout=3.0, phrase_time_limit=self.chunk_seconds)
                            raw_wav = audio.get_wav_data()

                            # Transcribe locally via faster-whisper or speech_recognition
                            text = stt.transcribe_audio_bytes(raw_wav, sample_rate=self.sample_rate)

                            if text and is_wake_word_in_text(text):
                                logger.info(f"Wake word detected in: '{text}'")
                                self.trigger_wake()

                                # Check if command was spoken in the same breath
                                inline_cmd = extract_command_after_wake_word(text)
                                if inline_cmd:
                                    logger.info(f"Inline command detected: '{inline_cmd}'")
                                    if self.on_command:
                                        self.on_command(inline_cmd)
                                else:
                                    # Listen for subsequent command
                                    self.mic_status = "listening_command"
                                    try:
                                        cmd_audio = recognizer.listen(source, timeout=5.0, phrase_time_limit=8.0)
                                        cmd_wav = cmd_audio.get_wav_data()
                                        cmd_text = stt.transcribe_audio_bytes(cmd_wav, sample_rate=self.sample_rate)
                                        if cmd_text and self.on_command:
                                            logger.info(f"Command transcribed: '{cmd_text}'")
                                            self.on_command(cmd_text)
                                    except sr.WaitTimeoutError:
                                        logger.info("Command listening timed out.")
                                    finally:
                                        self.mic_status = "listening_wakeword"

                        except sr.WaitTimeoutError:
                            continue
                        except Exception as loop_e:
                            logger.debug(f"Audio loop iteration: {loop_e}")
                            time.sleep(0.2)

            except Exception as mic_err:
                logger.warning(f"Microphone access error: {mic_err}. Retrying in 3 seconds...")
                self.mic_status = "error"
                time.sleep(3.0)


# Global Singleton
wake_service = WakeWordService()

