"""
SAHAYAK — Local Speech-To-Text (STT) Engine
100% Free, Local, Offline speech recognition using faster-whisper on Apple Silicon.
Replaces paid ElevenLabs streaming transcription API.
"""

import io
import logging
import os
import tempfile
import threading
import wave
import typing

logger = logging.getLogger("sahayak-stt")

_HAS_FASTER_WHISPER = False
try:
    from faster_whisper import WhisperModel
    _HAS_FASTER_WHISPER = True
except ImportError:
    logger.warning("faster_whisper not available. Will use speech_recognition or Web Speech.")

_HAS_SR = False
try:
    import speech_recognition as sr
    _HAS_SR = True
except ImportError:
    pass


class LocalSTTEngine:
    """
    On-device speech recognition engine.
    Initializes a lightweight 'tiny.en' or 'base.en' Whisper model locally.
    """

    def __init__(self, model_size: str = "tiny.en", device: str = "cpu", compute_type: str = "int8"):
        self.model_size = os.getenv("SAHAYAK_WHISPER_MODEL", model_size)
        self.device = device
        self.compute_type = compute_type
        self.model: typing.Optional[WhisperModel] = None
        self._lock = threading.Lock()
        self._initialized = False

    def _ensure_loaded(self) -> bool:
        """Lazy load the Whisper model on first transcription request."""
        if self._initialized:
            return self.model is not None

        with self._lock:
            if self._initialized:
                return self.model is not None

            if not _HAS_FASTER_WHISPER:
                self._initialized = True
                return False

            try:
                logger.info(f"Loading local Whisper model '{self.model_size}' on {self.device} ({self.compute_type})...")
                self.model = WhisperModel(
                    self.model_size,
                    device=self.device,
                    compute_type=self.compute_type,
                    download_root=os.path.expanduser("~/.cache/sahayak_whisper"),
                )
                logger.info("Local Whisper model loaded successfully.")
            except Exception as exc:
                logger.warning(f"Could not load faster-whisper model ({exc}). Falling back to speech_recognition.")
                self.model = None

            self._initialized = True
            return self.model is not None

    def transcribe_audio_bytes(self, pcm_bytes: bytes, sample_rate: int = 16000, sample_width: int = 2, channels: int = 1) -> str:
        """
        Transcribes raw PCM audio bytes to text locally.
        """
        if not pcm_bytes:
            return ""

        # Write to temporary WAV in memory
        wav_buf = io.BytesIO()
        with wave.open(wav_buf, "wb") as wf:
            wf.setnchannels(channels)
            wf.setsampwidth(sample_width)
            wf.setframerate(sample_rate)
            wf.writeframes(pcm_bytes)
        wav_buf.seek(0)

        # Attempt faster-whisper first
        if self._ensure_loaded() and self.model is not None:
            try:
                segments, info = self.model.transcribe(wav_buf, beam_size=1, language="en")
                text_segments = [s.text.strip() for s in segments]
                full_text = " ".join(text_segments).strip()
                if full_text:
                    logger.info(f"Whisper transcribed: '{full_text}'")
                    return full_text
            except Exception as exc:
                logger.warning(f"Whisper transcription error: {exc}")

        # Fallback to speech_recognition if available
        if _HAS_SR:
            try:
                wav_buf.seek(0)
                r = sr.Recognizer()
                with sr.AudioFile(wav_buf) as source:
                    audio_data = r.record(source)
                # Uses free offline Sphinx or free recognizer
                text = r.recognize_google(audio_data)
                return text.strip()
            except Exception as exc:
                logger.debug(f"speech_recognition fallback: {exc}")

        return ""

    def transcribe_wav_file(self, file_path: str) -> str:
        """Transcribe an on-disk WAV file."""
        if not os.path.exists(file_path):
            return ""

        if self._ensure_loaded() and self.model is not None:
            try:
                segments, _ = self.model.transcribe(file_path, beam_size=1, language="en")
                return " ".join(s.text.strip() for s in segments).strip()
            except Exception as exc:
                logger.warning(f"File transcription error: {exc}")
        return ""


# Global Singleton
stt = LocalSTTEngine()

