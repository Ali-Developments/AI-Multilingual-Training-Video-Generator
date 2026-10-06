"""Factory function for instantiating configured Avatar providers."""

from typing import Optional
from app.core.config import settings
from app.services.avatar.base import AvatarProvider
from app.services.avatar.mock_avatar_provider import MockAvatarProvider
from app.services.avatar.heygen_provider import HeyGenProvider


def get_avatar_provider(provider_type: Optional[str] = None) -> AvatarProvider:
    """
    Retrieve configured or requested Avatar provider instance.
    
    Args:
        provider_type: Explicit provider override (heygen, mock).
    """
    active_type = (provider_type or settings.DEFAULT_AVATAR_PROVIDER).strip().lower()

    if active_type == "mock":
        return MockAvatarProvider()
    elif active_type == "heygen":
        return HeyGenProvider()
    else:
        raise ValueError(
            f"Unsupported Avatar provider: '{active_type}'. "
            "Supported providers: 'mock', 'heygen'."
        )
