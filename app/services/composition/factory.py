"""Factory for video composition providers."""

from typing import Optional
from app.core.config import settings
from app.services.composition.base import CompositionProvider
from app.services.composition.ffmpeg_provider import FFmpegCompositionProvider
from app.services.composition.mock_provider import MockCompositionProvider


def get_composition_provider(provider_type: Optional[str] = None) -> CompositionProvider:
    """
    Retrieve configured or requested video composition provider.
    """
    active_type = (provider_type or settings.DEFAULT_COMPOSITION_PROVIDER).strip().lower()

    if active_type == "ffmpeg":
        return FFmpegCompositionProvider()
    elif active_type == "mock":
        return MockCompositionProvider()
    else:
        raise ValueError(
            f"Unsupported Composition provider: '{active_type}'. "
            "Supported providers: 'ffmpeg', 'mock'."
        )
