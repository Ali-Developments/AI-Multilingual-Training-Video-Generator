"""Supporting visual assets package."""

from app.services.visuals.base import (
    VisualAssetProvider,
    classify_visual_type,
)
from app.services.visuals.local_provider import LocalVisualProvider
from app.services.visuals.mock_provider import MockVisualProvider
from app.services.visuals.factory import get_visual_provider
from app.services.visuals.service import VisualService

__all__ = [
    "VisualAssetProvider",
    "classify_visual_type",
    "LocalVisualProvider",
    "MockVisualProvider",
    "get_visual_provider",
    "VisualService",
]
