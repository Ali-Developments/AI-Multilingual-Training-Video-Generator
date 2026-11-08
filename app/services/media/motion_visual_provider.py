"""Local Motion Visual Provider using FFmpeg and Motion Animator.

Generates dynamic, rich instructional animated video clips with smooth easing,
progressive highlighting, interactive cursors, and structured cards
matching scene narration. Zero API cost, fully local, fast execution.
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
from app.services.media.motion_animator import generate_animated_motion_video


class LocalMotionVisualProvider(SceneMediaProvider):
    """Generates dynamic motion video clips from instructional scenes using FFmpeg."""

    @property
    def provider_name(self) -> str:
        return "local_motion"

    def supports_media_type(self, media_type: str) -> bool:
        return media_type in ("motion_visual", "broll", "diagram", "media_full", "media_with_overlay")

    def _generate_ambient_background(self, output_path: Path, title: str = "", width: int = 1920, height: int = 1080) -> Path:
        """Create a modern cinematic ambient dark gradient canvas if no image exists."""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        img = Image.new("RGB", (width, height), color=(9, 13, 26))
        draw = ImageDraw.Draw(img)

        # Draw subtle ambient circular glows
        draw.ellipse([int(width * 0.1), int(height * 0.1), int(width * 0.65), int(height * 0.8)], fill=(15, 24, 48))
        draw.ellipse([int(width * 0.5), int(height * 0.2), int(width * 0.95), int(height * 0.9)], fill=(13, 34, 58))
        draw.ellipse([int(width * 0.3), int(height * 0.4), int(width * 0.8), int(height * 1.1)], fill=(18, 20, 45))

        # Modern top/bottom accent line
        draw.rectangle([0, 0, width, 5], fill=(0, 229, 255))
        draw.rectangle([0, height - 5, width, height], fill=(79, 70, 229))

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
        Generate a 1920x1080 motion MP4 for the scene with true animated elements.
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        out_video = output_dir / f"{scene.scene_id}_motion.mp4"

        dur = max(duration_seconds, 1.0)
        cache_key = f"{scene.scene_id}:{locale}:{dur:.2f}:{scene.media_type}:{scene.layout_type}:v3_motion"
        cache_hash = hash_text(cache_key)

        if out_video.exists() and out_video.stat().st_size > 1024:
            meta = load_asset_metadata(out_video)
            if meta and meta.get("motion_hash") == cache_hash:
                logger.info("Reusing cached motion visual for scene '%s' (locale='%s')", scene.scene_id, locale)
                return out_video

        fps = max(int(getattr(settings, "VIDEO_FPS", 25) or 25), 1)

        # If custom media file provided by user (e.g. uploaded video/photo), use Ken Burns motion
        if custom_media_path and custom_media_path.exists():
            logger.info("Rendering custom media Ken Burns motion for scene '%s' from '%s'", scene.scene_id, custom_media_path.name)
            total_frames = max(int(dur * fps) + 5, 1)
            zoom_filter = (
                f"zoompan=z='min(zoom+0.0008,1.15)':d={total_frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1920x1080:fps={fps},"
                f"format=yuv420p"
            )
            cmd = [
                settings.FFMPEG_BINARY_PATH,
                "-y",
                "-loop", "1",
                "-i", str(custom_media_path.resolve()),
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
            except Exception as e:
                logger.warning("Error running FFmpeg zoompan on custom media: %s", e)

        # Primary: Generate rich programmatic animated instructional motion graphic
        try:
            logger.info("Rendering high-impact animated instructional motion visual for scene '%s' (%.2fs)", scene.scene_id, dur)
            generate_animated_motion_video(
                scene=scene,
                duration_seconds=dur,
                output_path=out_video,
                width=1920,
                height=1080,
                fps=fps,
                custom_background_path=background_image_path,
            )
            if out_video.exists() and out_video.stat().st_size > 0:
                save_asset_metadata(out_video, {"motion_hash": cache_hash, "duration": dur, "scene_id": scene.scene_id, "animated": True})
                return out_video
        except Exception as ex:
            logger.warning("Animated motion video generation failed for scene '%s' (%s); attempting fallback", scene.scene_id, ex)

        # Fallback: ambient Ken Burns loop
        ambient_path = output_dir / f"{scene.scene_id}_ambient.png"
        src_img = self._generate_ambient_background(ambient_path, title=scene.title)
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
