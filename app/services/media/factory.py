"""Factory function for instantiating SceneMediaProvider instances."""

from typing import Optional
from app.core.config import settings
from app.services.media.base import SceneMediaProvider
from app.services.media.motion_visual_provider import LocalMotionVisualProvider
from app.services.media.uploaded_media_provider import UploadedMediaProvider
from app.services.media.veo_video_provider import VeoVideoProvider
from app.services.media.mock_media_provider import MockMediaProvider


def get_media_provider(provider_type: Optional[str] = None) -> SceneMediaProvider:
    """
    Retrieve configured or requested SceneMediaProvider instance.
    
    Args:
        provider_type: Explicit provider override ("motion_visual", "uploaded", "veo", "mock").
    """
    active_type = (provider_type or getattr(settings, "DEFAULT_MEDIA_PROVIDER", "motion_visual")).strip().lower()

    if active_type in ("motion_visual", "local", "default"):
        return LocalMotionVisualProvider()
    elif active_type in ("uploaded", "custom"):
        return UploadedMediaProvider()
    elif active_type == "veo":
        if not getattr(settings, "ENABLE_LIVE_VEO", False):
            raise PermissionError(
                "Live Google Veo video generation is blocked by safety configuration (ENABLE_LIVE_VEO=False). "
                "Both DEFAULT_MEDIA_PROVIDER and ENABLE_LIVE_VEO must explicitly allow live generation."
            )
        return VeoVideoProvider()
    elif active_type == "mock":
        return MockMediaProvider()
    else:
        raise ValueError(
            f"Unsupported Media provider: '{active_type}'. "
            "Supported providers: 'motion_visual', 'uploaded', 'veo', 'mock'."
        )

