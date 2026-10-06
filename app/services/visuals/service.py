"""High-level service coordinating supporting visual asset generation."""

from pathlib import Path
from typing import Optional, Dict
from PIL import Image

from app.core.config import settings
from app.core.logging import logger
from app.models.schemas import (
    LocalizedScript,
    LocalizationBundle,
    SceneVisualAsset,
    LocalizedVisualTrack,
)
from app.services.visuals.base import VisualAssetProvider
from app.services.visuals.factory import get_visual_provider


class VisualService:
    """
    Coordinates visual asset synthesis across localized scripts and bundles.
    """

    def __init__(
        self,
        provider: Optional[VisualAssetProvider] = None,
        output_base_dir: Optional[Path] = None,
    ) -> None:
        self.provider = provider or get_visual_provider()
        self.output_base_dir = output_base_dir or settings.STORAGE_PATH

    def generate_locale_visuals(
        self,
        script: LocalizedScript,
        project_id: str,
        force_regenerate: bool = False,
    ) -> LocalizedVisualTrack:
        """
        Generate visual slide graphics for every scene in a localized script.
        """
        locale = script.locale
        vis_dir = self.output_base_dir / project_id / "visuals" / locale
        vis_dir.mkdir(parents=True, exist_ok=True)

        scene_visuals = []
        for scene in script.scenes:
            img_dest = vis_dir / f"{scene.scene_id}.png"

            # Idempotency check: reuse existing valid PNG image
            if not force_regenerate and img_dest.exists() and img_dest.stat().st_size > 0:
                try:
                    with Image.open(img_dest) as im:
                        w, h = im.size
                    logger.info("Reusing existing visual slide for scene '%s' (%s)", scene.scene_id, locale)
                    scene_visuals.append(
                        SceneVisualAsset(
                            scene_id=scene.scene_id,
                            locale=locale,
                            image_path=str(img_dest.resolve()),
                            width=w,
                            height=h,
                            visual_type="slide",
                            provider=self.provider.provider_name,
                            status="completed",
                        )
                    )
                    continue
                except Exception as e:
                    logger.warning("Existing image for '%s' was invalid (%s); regenerating.", scene.scene_id, e)

            try:
                asset = self.provider.generate_scene_visual(
                    scene=scene,
                    locale=locale,
                    output_dir=vis_dir,
                    width=settings.VISUAL_WIDTH,
                    height=settings.VISUAL_HEIGHT,
                    cultural_guidance=script.cultural_guidance,
                )
                scene_visuals.append(asset)
            except Exception as e:
                logger.error("Visual generation failed for scene '%s': %s", scene.scene_id, str(e))
                scene_visuals.append(
                    SceneVisualAsset(
                        scene_id=scene.scene_id,
                        locale=locale,
                        image_path="",
                        width=settings.VISUAL_WIDTH,
                        height=settings.VISUAL_HEIGHT,
                        visual_type="slide",
                        provider=self.provider.provider_name,
                        status="failed",
                        error=str(e),
                    )
                )

        completed_count = sum(1 for v in scene_visuals if v.status == "completed")
        failed_count = sum(1 for v in scene_visuals if v.status == "failed")

        if failed_count == 0:
            track_status = "completed"
        elif completed_count > 0:
            track_status = "partial"
        else:
            track_status = "failed"

        return LocalizedVisualTrack(
            locale=locale,
            scene_visuals=scene_visuals,
            status=track_status,
            metadata={
                "provider": self.provider.provider_name,
                "total_scenes": len(script.scenes),
                "completed_count": completed_count,
                "failed_count": failed_count,
            },
        )

    def generate_bundle_visuals(
        self,
        bundle: LocalizationBundle,
        project_id: str,
        force_regenerate: bool = False,
    ) -> Dict[str, LocalizedVisualTrack]:
        """
        Generate visual tracks for all localized scripts in a bundle with failure isolation.
        """
        tracks = {}
        for locale, script in bundle.localized_scripts.items():
            try:
                tracks[locale] = self.generate_locale_visuals(
                    script=script,
                    project_id=project_id,
                    force_regenerate=force_regenerate,
                )
            except Exception as e:
                logger.error("Failed to generate visuals for locale '%s': %s", locale, str(e))
                tracks[locale] = LocalizedVisualTrack(
                    locale=locale,
                    scene_visuals=[],
                    status="failed",
                    metadata={"error": str(e)},
                )
        return tracks
