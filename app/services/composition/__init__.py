"""Video composition package."""

from app.services.composition.base import CompositionProvider
from app.services.composition.ffmpeg_provider import FFmpegCompositionProvider
from app.services.composition.mock_provider import MockCompositionProvider
from app.services.composition.factory import get_composition_provider
from app.services.composition.service import CompositionService
from app.services.composition.ffmpeg_utils import (
    check_ffmpeg_available,
    check_ffprobe_available,
    get_video_duration,
    escape_ffmpeg_filter_path,
)

__all__ = [
    "CompositionProvider",
    "FFmpegCompositionProvider",
    "MockCompositionProvider",
    "get_composition_provider",
    "CompositionService",
    "check_ffmpeg_available",
    "check_ffprobe_available",
    "get_video_duration",
    "escape_ffmpeg_filter_path",
]
