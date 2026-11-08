"""Scene Media Service coordinating multimodal visual asset providers."""

from pathlib import Path
from typing import Optional, Dict
from app.core.logging import logger
from app.models.schemas import LocalizedScene
from app.services.media.base import SceneMediaProvider
from app.services.media.motion_visual_provider import LocalMotionVisualProvider
from app.services.media.uploaded_media_provider import UploadedMediaProvider


class SceneMediaService:
    """Dispatches media generation to appropriate providers based on scene specification."""

    def __init__(self):
        self.motion_provider = LocalMotionVisualProvider()
        self.uploaded_provider = UploadedMediaProvider()

    def generate_scene_media(
        self,
        scene: LocalizedScene,
        locale: str,
        output_dir: Path,
        duration_seconds: float,
        background_image_path: Optional[Path] = None,
        project_storage_dir: Optional[Path] = None,
    ) -> Path:
        """
        Produce or adapt the visual media segment for the scene.
        """
        # 1. Check custom uploaded asset if assigned
        custom_path: Optional[Path] = None
        if scene.media_asset_path:
            p = Path(scene.media_asset_path)
            if p.is_absolute() and p.exists():
                custom_path = p
            elif project_storage_dir and (project_storage_dir / "media" / scene.media_asset_path).exists():
                custom_path = project_storage_dir / "media" / scene.media_asset_path

        if custom_path:
            return self.uploaded_provider.generate_scene_media(
                scene=scene,
                locale=locale,
                output_dir=output_dir,
                duration_seconds=duration_seconds,
                background_image_path=background_image_path,
                custom_media_path=custom_path,
            )

        # 2. Default to cinematic local motion visual
        return self.motion_provider.generate_scene_media(
            scene=scene,
            locale=locale,
            output_dir=output_dir,
            duration_seconds=duration_seconds,
            background_image_path=background_image_path,
        )
