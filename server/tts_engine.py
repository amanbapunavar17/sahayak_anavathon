"""
SAHAYAK — Text-To-Speech (TTS) Engine
Uses macOS native 'say' utility and NSSpeechSynthesizer.
100% Free, Offline, Low-latency spoken feedback for blind and low-vision users.
"""

import logging
import os
import queue
import subprocess
import threading
import typing

logger = logging.getLogger("sahayak-tts")


class TTSEngine:
    """
    Thread-safe, non-blocking Speech Synthesis engine.
    Queues spoken messages to avoid overlapping audio and allows
    instant cancellation when a user interrupts or cancels.
    """

    def __init__(self, default_voice: str = "Samantha", default_rate: int = 180):
        self.default_voice = os.getenv("SAHAYAK_TTS_VOICE", default_voice)
        self.default_rate = int(os.getenv("SAHAYAK_TTS_RATE", default_rate))
        self._speech_queue: queue.Queue = queue.Queue()
        self._current_process: typing.Optional[subprocess.Popen] = None
        self._lock = threading.Lock()
        self._running = True
        self._worker_thread = threading.Thread(
            target=self._speech_worker, name="SahayakTTSWorker", daemon=True
        )
        self._worker_thread.start()
        logger.info(
            f"TTS Engine initialized with voice={self.default_voice}, rate={self.default_rate}"
        )

    def speak(
        self,
        text: str,
        voice: typing.Optional[str] = None,
        rate: typing.Optional[int] = None,
        interrupt: bool = False,
    ) -> None:
        """
        Queue text to be spoken aloud.
        If interrupt is True, stops any currently playing audio and clears queue.
        """
        if not text or not text.strip():
            return

        clean_text = text.strip()
        v = voice or self.default_voice
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
    ) -> None:
        """Speak immediately and block until finished (useful for startup/shutdown cues)."""
        if not text or not text.strip():
            return
        v = voice or self.default_voice
        r = rate or self.default_rate
        try:
            subprocess.run(
                ["say", "-v", v, "-r", str(r), text],
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

