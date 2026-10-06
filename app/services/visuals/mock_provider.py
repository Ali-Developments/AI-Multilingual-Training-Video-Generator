"""Mock visual asset provider for rapid testing and dry runs."""

from pathlib import Path
from typing import Optional
from PIL import Image

from app.models.schemas import LocalizedScene, CulturalGuidance, SceneVisualAsset
from app.services.visuals.base import VisualAssetProvider, classify_visual_type


class MockVisualProvider(VisualAssetProvider):
    """Mock visual provider creating simple solid-color PNG images."""

    @property
    def provider_name(self) -> str:
        return "mock"

    def generate_scene_visual(
        self,
        scene: LocalizedScene,
        locale: str,
        output_dir: Path,
        width: int = 1920,
        height: int = 1080,
        cultural_guidance: Optional[CulturalGuidance] = None,
    ) -> SceneVisualAsset:
        output_dir.mkdir(parents=True, exist_ok=True)
        img_path = output_dir / f"{scene.scene_id}.png"
        visual_type = classify_visual_type(scene.scene_type)

        # Create lightweight 1920x1080 image
        image = Image.new("RGB", (width, height), color=(20, 30, 50))
        image.save(img_path, format="PNG")

        return SceneVisualAsset(
            scene_id=scene.scene_id,
            locale=locale,
            image_path=str(img_path.resolve()),
            width=width,
            height=height,
            visual_type=visual_type,
            provider=self.provider_name,
            status="completed",
        )
