"""Uploaded Media Provider for user-supplied videos and images."""

from pathlib import Path
from typing import Optional
import subprocess

from app.core.config import settings
from app.core.logging import logger
from app.models.schemas import LocalizedScene
from app.services.media.base import SceneMediaProvider
from app.services.media.motion_visual_provider import LocalMotionVisualProvider


class UploadedMediaProvider(SceneMediaProvider):
    """Processes user-uploaded video footage and images for scene presentation."""

    def __init__(self):
        self.motion_provider = LocalMotionVisualProvider()

    @property
    def provider_name(self) -> str:
        return "uploaded_media"

    def supports_media_type(self, media_type: str) -> bool:
        return media_type in ("uploaded_video", "uploaded_image", "broll")

    def generate_scene_media(
        self,
        scene: LocalizedScene,
        locale: str,
        output_dir: Path,
        duration_seconds: float,
        background_image_path: Optional[Path] = None,
        custom_media_path: Optional[Path] = None,
    ) -> Path:
        output_dir.mkdir(parents=True, exist_ok=True)
        dur = max(duration_seconds, 1.0)

        # If custom media is not provided, fall back to motion provider
        if not custom_media_path or not custom_media_path.exists():
            return self.motion_provider.generate_scene_media(
                scene, locale, output_dir, dur, background_image_path
            )

        suffix = custom_media_path.suffix.lower()
        is_video = suffix in (".mp4", ".mov", ".webm", ".mkv", ".avi")

        if not is_video:
            # Image asset: apply cinematic motion
            return self.motion_provider.generate_scene_media(
                scene, locale, output_dir, dur, custom_media_path=custom_media_path
            )

        # Video asset: loop or trim to exact duration and scale to 1920x1080
        out_video = output_dir / f"{scene.scene_id}_uploaded_video.mp4"
        norm_filter = (
            f"scale=1920:1080:force_original_aspect_ratio=decrease,"
            f"pad=1920:1080:(ow-iw)/2:(oh-ih)/2:black,setsar=1,format=yuv420p"
        )

        cmd = [
            settings.FFMPEG_BINARY_PATH,
            "-y",
            "-stream_loop", "-1",
            "-i", str(custom_media_path.resolve()),
            "-vf", norm_filter,
            "-an",  # Strip original audio; scene uses narration voiceover
            "-c:v", settings.VIDEO_CODEC,
            "-pix_fmt", "yuv420p",
            "-t", str(dur),
            str(out_video.resolve()),
        ]

        logger.info("Processing uploaded video for scene '%s' (duration=%.2fs)", scene.scene_id, dur)
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            if res.returncode == 0 and out_video.exists() and out_video.stat().st_size > 0:
                return out_video
            logger.warning("Uploaded video processing failed: %s", res.stderr)
        except Exception as e:
            logger.error("Error processing uploaded video: %s", e)

        # Fallback to motion visual
        return self.motion_provider.generate_scene_media(
            scene, locale, output_dir, dur, background_image_path
        )
