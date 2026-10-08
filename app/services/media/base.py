"""Abstract Base Class for Scene Media Providers."""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional, Any
from app.models.schemas import LocalizedScene


class SceneMediaProvider(ABC):
    """Abstract provider for generating or sourcing scene visual media (video or image)."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Unique provider identifier name."""
        pass

    @abstractmethod
    def supports_media_type(self, media_type: str) -> bool:
        """Whether this provider can generate the requested media type."""
        pass

    @abstractmethod
    def generate_scene_media(
        self,
        scene: LocalizedScene,
        locale: str,
        output_dir: Path,
        duration_seconds: float,
        background_image_path: Optional[Path] = None,
        custom_media_path: Optional[Path] = None,
    ) -> Path:
        """
        Generate or process media asset for the scene.
        Returns the path to the produced video or image asset.
        """
        pass
