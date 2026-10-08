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
    elif active_type == "sadtalker":
        from app.services.avatar.sadtalker_provider import SadTalkerProvider
        return SadTalkerProvider()
    elif active_type == "heygen":
        if not getattr(settings, "ENABLE_LIVE_HEYGEN", False):
            raise PermissionError(
                "Live HeyGen avatar generation is blocked by safety configuration (ENABLE_LIVE_HEYGEN=False). "
                "Both DEFAULT_AVATAR_PROVIDER and ENABLE_LIVE_HEYGEN must explicitly allow live generation."
            )
        if not settings.HEYGEN_API_KEY:
            raise ValueError("HEYGEN_API_KEY is not configured for live HeyGen avatar generation.")
        return HeyGenProvider()
    else:
        raise ValueError(
            f"Unsupported Avatar provider: '{active_type}'. "
            "Supported providers: 'mock', 'sadtalker', 'heygen'."
        )
