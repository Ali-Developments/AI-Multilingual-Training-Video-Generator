"""Local Motion Visual Provider using FFmpeg.

Transforms static graphics and images into cinematic motion video segments
using slow Ken Burns zooms, gentle pans, and professional crossfades.
Zero API cost, fully local, fast execution.
"""

from pathlib import Path
from typing import Optional, List
import subprocess
from PIL import Image, ImageDraw

from app.core.config import settings
from app.core.logging import logger
from app.core.caching import hash_text, save_asset_metadata, load_asset_metadata
from app.models.schemas import LocalizedScene
from app.services.media.base import SceneMediaProvider


class LocalMotionVisualProvider(SceneMediaProvider):
    """Generates dynamic motion video clips from static visuals using FFmpeg."""

    @property
    def provider_name(self) -> str:
        return "local_motion"

    def supports_media_type(self, media_type: str) -> bool:
        return media_type in ("motion_visual", "broll", "diagram", "media_full", "media_with_overlay")

    def _generate_ambient_background(self, output_path: Path, title: str = "", width: int = 1920, height: int = 1080) -> Path:
        """Create a modern cinematic ambient dark gradient canvas if no image exists."""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        img = Image.new("RGB", (width, height), color=(10, 15, 30))
        draw = ImageDraw.Draw(img)

        # Draw subtle ambient circular glows
        draw.ellipse([width * 0.1, height * 0.1, width * 0.6, height * 0.8], fill=(15, 25, 55))
        draw.ellipse([width * 0.5, height * 0.2, width * 0.95, height * 0.9], fill=(12, 35, 60))
        draw.ellipse([width * 0.3, height * 0.4, width * 0.8, height * 1.1], fill=(18, 20, 45))

        # Modern top/bottom accent line
        draw.rectangle([0, 0, width, 6], fill=(0, 229, 255))
        draw.rectangle([0, height - 6, width, height], fill=(79, 70, 229))

        img.save(output_path, quality=95)
        return output_path

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
        Generate a 1920x1080 motion MP4 for the scene using Ken Burns motion.
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        out_video = output_dir / f"{scene.scene_id}_motion.mp4"

        # Check existing valid cache
        dur = max(duration_seconds, 1.0)
        cache_key = f"{scene.scene_id}:{locale}:{dur:.2f}:{scene.media_type}:{scene.layout_type}"
        cache_hash = hash_text(cache_key)

        if out_video.exists() and out_video.stat().st_size > 1024:
            meta = load_asset_metadata(out_video)
            if meta and meta.get("motion_hash") == cache_hash:
                logger.info("Reusing cached motion visual for scene '%s' (locale='%s')", scene.scene_id, locale)
                return out_video

        # Determine source image
        src_img: Path
        if custom_media_path and custom_media_path.exists():
            src_img = custom_media_path
        elif background_image_path and background_image_path.exists():
            src_img = background_image_path
        else:
            ambient_path = output_dir / f"{scene.scene_id}_ambient.png"
            src_img = self._generate_ambient_background(ambient_path, title=scene.title)

        logger.info("Rendering local motion visual for scene '%s' (duration=%.2fs) from '%s'", scene.scene_id, dur, src_img.name)

        fps = 25
        total_frames = int(dur * fps) + 5
        # Ken Burns zoom-pan filter: subtle zoom in from 1.0 to 1.12 with centered framing
        zoom_filter = (
            f"zoompan=z='min(zoom+0.0008,1.15)':d={total_frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1920x1080:fps={fps},"
            f"format=yuv420p"
        )

        cmd = [
            settings.FFMPEG_BINARY_PATH,
            "-y",
            "-loop", "1",
            "-i", str(src_img.resolve()),
            "-vf", zoom_filter,
            "-c:v", settings.VIDEO_CODEC,
            "-pix_fmt", "yuv420p",
            "-t", str(dur),
            str(out_video.resolve()),
        ]

        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
            if res.returncode == 0 and out_video.exists() and out_video.stat().st_size > 0:
                save_asset_metadata(out_video, {"motion_hash": cache_hash, "duration": dur, "scene_id": scene.scene_id})
                return out_video
            logger.warning("FFmpeg zoompan failed, falling back to simple loop: %s", res.stderr)
        except Exception as e:
            logger.warning("Error running FFmpeg zoompan: %s", e)

        # Fallback simple scale video
        fallback_filter = "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:black,setsar=1,format=yuv420p"
        fb_cmd = [
            settings.FFMPEG_BINARY_PATH,
            "-y",
            "-loop", "1",
            "-i", str(src_img.resolve()),
            "-vf", fallback_filter,
            "-c:v", settings.VIDEO_CODEC,
            "-pix_fmt", "yuv420p",
            "-t", str(dur),
            str(out_video.resolve()),
        ]
        subprocess.run(fb_cmd, capture_output=True, text=True, timeout=60)
        return out_video
