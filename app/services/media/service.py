"""Scene Media Service coordinating multimodal visual asset providers."""

from pathlib import Path
from typing import Optional, Dict
from app.core.config import settings
from app.core.logging import logger
from app.models.schemas import LocalizedScene
from app.services.media.base import SceneMediaProvider
from app.services.media.motion_visual_provider import LocalMotionVisualProvider
from app.services.media.uploaded_media_provider import UploadedMediaProvider
from app.services.media.factory import get_media_provider


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

        # 2. Check if Veo AI Video was explicitly requested for this scene or globally
        media_type = getattr(scene, "media_type", None)
        mt_str = str(getattr(media_type, "value", media_type) or "").lower()
        pref_prov = str(getattr(scene, "preferred_provider", "") or "").lower()
        default_prov = str(getattr(settings, "DEFAULT_MEDIA_PROVIDER", "motion_visual") or "").lower()

        if mt_str in ("veo", "ai_video") or pref_prov == "veo" or default_prov == "veo":
            logger.info("Dispatching scene '%s' to Google Veo video provider.", scene.scene_id)
            try:
                veo_provider = get_media_provider("veo")
                return veo_provider.generate_scene_media(
                    scene=scene,
                    locale=locale,
                    output_dir=output_dir,
                    duration_seconds=duration_seconds,
                    background_image_path=background_image_path,
                    custom_media_path=custom_path,
                )
            except Exception as e:
                logger.warning(
                    "Veo video generation unavailable for scene '%s' (%s); falling back to continuous motion visual",
                    scene.scene_id, e
                )

        # 3. Default to cinematic local motion visual
        return self.motion_provider.generate_scene_media(
            scene=scene,
            locale=locale,
            output_dir=output_dir,
            duration_seconds=duration_seconds,
            background_image_path=background_image_path,
        )
