"""Abstract base class for subtitle providers."""

from abc import ABC, abstractmethod
from pathlib import Path
from app.models.schemas import SceneSubtitleAsset


class SubtitleProvider(ABC):
    """Abstract interface defining subtitle generation providers."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Return unique provider identifier."""
        pass

    @abstractmethod
    def generate_scene_subtitles(
        self,
        scene_id: str,
        narration: str,
        duration_seconds: float,
        locale: str,
        output_dir: Path,
    ) -> SceneSubtitleAsset:
        """
        Generate aligned subtitle assets (.srt and .vtt) for a scene.
        """
        pass
