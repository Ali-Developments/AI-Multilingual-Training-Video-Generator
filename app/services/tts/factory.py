"""Factory function for instantiating configured TTS providers."""

from typing import Optional
from app.core.config import settings
from app.services.tts.base import TTSProvider
from app.services.tts.edge_tts_provider import EdgeTTSProvider
from app.services.tts.mock_tts_provider import MockTTSProvider


def get_tts_provider(provider_type: Optional[str] = None) -> TTSProvider:
    """
    Retrieve configured or requested TTS provider instance.
    
    Args:
        provider_type: Explicit provider type override (edge_tts, mock).
    """
    active_type = (provider_type or settings.DEFAULT_TTS_PROVIDER).strip().lower()

    if active_type == "edge_tts":
        return EdgeTTSProvider()
    elif active_type == "mock":
        return MockTTSProvider()
    else:
        raise ValueError(
            f"Unsupported TTS provider: '{active_type}'. "
            "Supported providers: 'edge_tts', 'mock'."
        )
