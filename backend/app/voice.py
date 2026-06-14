import asyncio
import io
import wave
from typing import Protocol

from piper import PiperVoice

from app.config import get_settings

from faster_whisper import WhisperModel


class STTProvider(Protocol):
    """Common interface for any speech-to-text backend."""

    async def transcribe(self, audio_bytes: bytes) -> str: ...

class TTSProvider(Protocol):
    """Common interface for any text-to-speech backend."""

    async def synthesize(self, text: str) -> bytes: ...

class PiperProvider:
    """Runs a PiperVoice model in-process on CPU."""

    def __init__(self, model_path: str) -> None:
        self._voice = PiperVoice.load(model_path)

    async def synthesize(self, text: str) -> bytes:
        return await asyncio.to_thread(self._synthesize_sync, text)
    
    def _synthesize_sync(self, text: str) -> bytes:
        buffer = io.BytesIO() # Create an in-memory bytes buffer so no disk space used
        chunks = list(self._voice.synthesize(text))
        if not chunks:
            return b""
        
        first = chunks[0]
        with wave.open(buffer, 'wb') as wav_file:
            wav_file.setnchannels(first.sample_channels)
            wav_file.setsampwidth(first.sample_width)
            wav_file.setframerate(first.sample_rate)
            for chunk in chunks:
                wav_file.writeframes(chunk.audio_int16_bytes)
        
        buffer.seek(0)
        return buffer.read()
    
_tts_provider: TTSProvider | None = None

def init_tts() -> TTSProvider:
    """Initialize the TTS provider based on config. Call once at startup."""
    global _tts_provider
    settings = get_settings()
    _tts_provider = PiperProvider(settings.piper_model_path)
    return _tts_provider

def get_tts() -> TTSProvider:
    if _tts_provider is None:
        raise RuntimeError("TTS provider not initialized")
    return _tts_provider


class WhisperProvider:
    """Runs a WhisperModel in-process on CPU."""

    def __init__(self, model_name: str) -> None:
        self._model = WhisperModel(model_name, device="cpu", compute_type="int8")

    async def transcribe(self, audio_bytes: bytes) -> str:
        return await asyncio.to_thread(self._transcribe_sync, audio_bytes)
    
    def _transcribe_sync(self, audio_bytes: bytes) -> str:
        audio_io = io.BytesIO(audio_bytes)
        segments, _info = self._model.transcribe(audio_io)
        return " ".join(segment.text for segment in segments).strip()
    
_stt_provider: STTProvider | None = None

def init_stt() -> STTProvider:
    """Initialize the STT provider based on config. Call once at startup."""
    global _stt_provider
    settings = get_settings()
    _stt_provider = WhisperProvider(settings.whisper_model)
    return _stt_provider

def get_stt() -> STTProvider:
    if _stt_provider is None:
        raise RuntimeError("STT provider not initialized")
    return _stt_provider