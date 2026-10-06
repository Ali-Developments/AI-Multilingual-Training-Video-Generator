"""Abstract base class for supporting visual asset providers."""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional
from app.models.schemas import LocalizedScene, CulturalGuidance, SceneVisualAsset


def classify_visual_type(scene_type: str) -> str:
    """Classify scene into visual template type."""
    st = (scene_type or "").strip().lower()
    if st == "intro":
        return "title_card"
    elif st == "outro" or st == "recap":
        return "summary_card"
    elif st == "visual_demo":
        return "demo_slide"
    elif st == "explanation":
        return "concept_slide"
    elif st == "presenter":
        return "presentation_slide"
    return "concept_slide"


class VisualAssetProvider(ABC):
    """Abstract interface defining visual slide/background providers."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Return unique provider identifier."""
        pass

    @abstractmethod
    def generate_scene_visual(
        self,
        scene: LocalizedScene,
        locale: str,
        output_dir: Path,
        width: int = 1920,
        height: int = 1080,
        cultural_guidance: Optional[CulturalGuidance] = None,
    ) -> SceneVisualAsset:
        """
        Generate a supporting visual slide/background image for the scene.
        """
        pass
