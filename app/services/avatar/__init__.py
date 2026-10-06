"""Avatar video generation package."""

from app.services.avatar.base import AvatarProvider, is_avatar_eligible
from app.services.avatar.mock_avatar_provider import MockAvatarProvider, generate_synthetic_mp4_file
from app.services.avatar.heygen_provider import (
    HeyGenProvider,
    HeyGenAPIError,
    HeyGenAuthError,
    HeyGenRateLimitError,
)
from app.services.avatar.factory import get_avatar_provider
from app.services.avatar.service import AvatarService

__all__ = [
    "AvatarProvider",
    "is_avatar_eligible",
    "MockAvatarProvider",
    "generate_synthetic_mp4_file",
    "HeyGenProvider",
    "HeyGenAPIError",
    "HeyGenAuthError",
    "HeyGenRateLimitError",
    "get_avatar_provider",
    "AvatarService",
]
