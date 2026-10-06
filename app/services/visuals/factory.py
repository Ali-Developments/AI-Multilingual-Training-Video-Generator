"""Factory for visual asset providers."""

from typing import Optional
from app.core.config import settings
from app.services.visuals.base import VisualAssetProvider
from app.services.visuals.local_provider import LocalVisualProvider
from app.services.visuals.mock_provider import MockVisualProvider


def get_visual_provider(provider_type: Optional[str] = None) -> VisualAssetProvider:
    """
    Retrieve configured or requested visual provider instance.
    """
    active_type = (provider_type or settings.DEFAULT_VISUAL_PROVIDER).strip().lower()

    if active_type == "local":
        return LocalVisualProvider()
    elif active_type == "mock":
        return MockVisualProvider()
    else:
        raise ValueError(
            f"Unsupported Visual provider: '{active_type}'. "
            "Supported providers: 'local', 'mock'."
        )
