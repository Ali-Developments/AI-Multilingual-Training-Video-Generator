"""TTS (Text-to-Speech) and audio duration measurement package."""

from app.services.tts.audio_probe import get_audio_duration
from app.services.tts.base import TTSProvider
from app.services.tts.mock_tts_provider import MockTTSProvider, generate_synthetic_wav_file
from app.services.tts.edge_tts_provider import EdgeTTSProvider
from app.services.tts.factory import get_tts_provider
from app.services.tts.service import TTSService

__all__ = [
    "get_audio_duration",
    "TTSProvider",
    "MockTTSProvider",
    "generate_synthetic_wav_file",
    "EdgeTTSProvider",
    "get_tts_provider",
    "TTSService",
]
