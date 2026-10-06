"""Factory for subtitle providers."""

from typing import Optional
from app.services.subtitles.base import SubtitleProvider
from app.services.subtitles.deterministic_provider import DeterministicSubtitleProvider


def get_subtitle_provider(provider_type: Optional[str] = None) -> SubtitleProvider:
    """
    Retrieve configured or requested subtitle provider instance.
    """
    active_type = (provider_type or "deterministic").strip().lower()

    if active_type == "deterministic":
        return DeterministicSubtitleProvider()
    else:
        raise ValueError(
            f"Unsupported Subtitle provider: '{active_type}'. "
            "Supported providers: 'deterministic'."
        )
