"""Abstract base class for video composition providers."""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import List, Optional

from app.models.schemas import SceneCompositionAsset, FinalVideoAsset


class CompositionProvider(ABC):
    """Abstract interface defining scene composition and concatenation engines."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Return unique provider identifier."""
        pass

    @abstractmethod
    def compose_scene(
        self,
        scene_id: str,
        locale: str,
        audio_path: Path,
        visual_image_path: Optional[Path] = None,
        avatar_video_path: Optional[Path] = None,
        subtitle_path: Optional[Path] = None,
        duration_seconds: float = 0.0,
        output_path: Optional[Path] = None,
        burn_subtitles: bool = True,
    ) -> SceneCompositionAsset:
        """Compose individual scene audio, visuals, avatar, and subtitles into scene MP4."""
        pass

    @abstractmethod
    def concatenate_scenes(
        self,
        scene_videos: List[SceneCompositionAsset],
        locale: str,
        output_path: Path,
    ) -> FinalVideoAsset:
        """Concatenate ordered scene video files into a final full-length video."""
        pass
