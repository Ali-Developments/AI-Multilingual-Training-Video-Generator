"""FFmpeg media composition provider orchestrating direct subprocess commands."""

import subprocess
from pathlib import Path
from typing import List, Optional

from app.core.config import settings
from app.core.logging import logger
from app.models.schemas import SceneCompositionAsset, FinalVideoAsset
from app.services.composition.base import CompositionProvider
from app.services.composition.ffmpeg_utils import (
    check_ffmpeg_available,
    get_video_duration,
    escape_ffmpeg_filter_path,
)


class FFmpegCompositionProvider(CompositionProvider):
    """
    Primary video composition engine orchestrating native FFmpeg subprocess pipelines.
    """

    @property
    def provider_name(self) -> str:
        return "ffmpeg"

    def compose_scene(
        self,
        scene_id: str,
        locale: str,
        audio_path: Path,
        visual_image_path: Optional[Path] = None,
        avatar_video_path: Optional[Path] = None,
        subtitle_path: Optional[Path] = None,
        duration_seconds: float = 0.0,
        output_path: Optional[Path] = None,
        burn_subtitles: bool = True,
    ) -> SceneCompositionAsset:
        if not check_ffmpeg_available():
            raise RuntimeError(
                f"FFmpeg binary '{settings.FFMPEG_BINARY_PATH}' not found. "
                "Please install FFmpeg or set DEFAULT_COMPOSITION_PROVIDER='mock'."
            )

        if not audio_path.exists():
            raise FileNotFoundError(f"Required audio asset not found: {audio_path}")

        output_path.parent.mkdir(parents=True, exist_ok=True)
        has_avatar = bool(avatar_video_path and avatar_video_path.exists() and avatar_video_path.stat().st_size > 0)
        has_visual = bool(visual_image_path and visual_image_path.exists() and visual_image_path.stat().st_size > 0)

        if not has_avatar and not has_visual:
            raise FileNotFoundError(
                f"Scene '{scene_id}' requires either a visual image or avatar video segment."
            )

        sub_burned = False
        sub_filter = None
        if (
            burn_subtitles
            and subtitle_path
            and subtitle_path.exists()
            and subtitle_path.stat().st_size > 0
        ):
            ass_candidate = subtitle_path.with_suffix(".ass")
            if ass_candidate.exists() and ass_candidate.stat().st_size > 0:
                escaped_sub = escape_ffmpeg_filter_path(ass_candidate)
                sub_filter = f"ass={escaped_sub}:shaping=complex"
            else:
                escaped_sub = escape_ffmpeg_filter_path(subtitle_path)
                sub_filter = f"subtitles={escaped_sub}"

        def _execute_ffmpeg(cmd: List[str]) -> bool:
            try:
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
                if res.returncode == 0:
                    return True
                logger.warning("FFmpeg command failed with stderr: %s", res.stderr)
                return False
            except Exception as e:
                logger.error("FFmpeg execution error: %s", e)
                return False

        # Build audio standardization parameters
        audio_encoding_args = [
            "-c:a", settings.AUDIO_CODEC,
            "-ar", str(settings.AUDIO_SAMPLE_RATE),
            "-ac", str(settings.AUDIO_CHANNELS),
            "-b:a", str(settings.AUDIO_BITRATE),
        ]

        norm_filter = (
            f"scale={settings.VIDEO_WIDTH}:{settings.VIDEO_HEIGHT}:force_original_aspect_ratio=decrease,"
            f"pad={settings.VIDEO_WIDTH}:{settings.VIDEO_HEIGHT}:(ow-iw)/2:(oh-ih)/2:black,setsar=1"
        )

        use_pip = (
            has_avatar
            and has_visual
            and getattr(settings, "AVATAR_LAYOUT", "pip").lower() == "pip"
        )

        if has_avatar and use_pip:
            logger.info("Composing avatar scene '%s' with PiP presenter panel layout", scene_id)
            pip_size = 540  # 540x540 panel on 1920x1080 background (~2x upscale of 256x256)
            base_pip_filter = (
                f"[1:v]scale={settings.VIDEO_WIDTH}:{settings.VIDEO_HEIGHT}:force_original_aspect_ratio=decrease,"
                f"pad={settings.VIDEO_WIDTH}:{settings.VIDEO_HEIGHT}:(ow-iw)/2:(oh-ih)/2:black,setsar=1[bg];"
                f"[0:v]scale={pip_size}:{pip_size}:force_original_aspect_ratio=decrease,setsar=1[pip];"
                f"[bg][pip]overlay=W-w-50:H-h-50"
            )
            final_pip_filter = f"{base_pip_filter},{sub_filter}" if sub_filter else base_pip_filter

            base_cmd = [
                settings.FFMPEG_BINARY_PATH,
                "-y",
                "-i", str(avatar_video_path.resolve()),
                "-loop", "1",
                "-i", str(visual_image_path.resolve()),
                "-i", str(audio_path.resolve()),
            ]

            cmd_with_sub = base_cmd + [
                "-filter_complex", final_pip_filter,
                "-map", "0:v" if not final_pip_filter else "[0:v]", # overridden below
                "-map", "2:a:0",
                "-c:v", settings.VIDEO_CODEC,
                *audio_encoding_args,
                "-pix_fmt", "yuv420p",
                "-shortest",
                "-t", str(duration_seconds),
                str(output_path.resolve()),
            ]
            # When filter_complex is used without labeled output in overlay:
            # The filter graph outputs the composite on the default output stream.
            cmd_with_sub = base_cmd + [
                "-filter_complex", final_pip_filter,
                "-map", "2:a:0",
                "-c:v", settings.VIDEO_CODEC,
                *audio_encoding_args,
                "-pix_fmt", "yuv420p",
                "-shortest",
                "-t", str(duration_seconds),
                str(output_path.resolve()),
            ]

            if sub_filter and _execute_ffmpeg(cmd_with_sub):
                sub_burned = True
            else:
                if sub_filter:
                    logger.info("Subtitle burn-in failed on PiP scene '%s'; falling back to unburned", scene_id)
                cmd_no_sub = base_cmd + [
                    "-filter_complex", base_pip_filter,
                    "-map", "2:a:0",
                    "-c:v", settings.VIDEO_CODEC,
                    *audio_encoding_args,
                    "-pix_fmt", "yuv420p",
                    "-shortest",
                    "-t", str(duration_seconds),
                    str(output_path.resolve()),
                ]
                if not _execute_ffmpeg(cmd_no_sub):
                    logger.warning("PiP composition failed, falling back to centered avatar")
                    use_pip = False

        if has_avatar and not use_pip:
            logger.info("Composing avatar scene '%s' for locale '%s' (centered layout)", scene_id, locale)
            combined_filter = f"{norm_filter},{sub_filter}" if sub_filter else norm_filter
            base_cmd = [
                settings.FFMPEG_BINARY_PATH,
                "-y",
                "-i", str(avatar_video_path.resolve()),
                "-i", str(audio_path.resolve()),
            ]
            if sub_filter:
                cmd_with_sub = base_cmd + [
                    "-vf", combined_filter,
                    "-map", "0:v:0",
                    "-map", "1:a:0",
                    "-c:v", settings.VIDEO_CODEC,
                    *audio_encoding_args,
                    "-pix_fmt", "yuv420p",
                    "-t", str(duration_seconds),
                    str(output_path.resolve()),
                ]
                if _execute_ffmpeg(cmd_with_sub):
                    sub_burned = True
                else:
                    logger.info("Subtitle burn-in failed on scene '%s'; falling back to unburned render", scene_id)
            if not sub_burned:
                cmd_no_sub = base_cmd + [
                    "-vf", norm_filter,
                    "-map", "0:v:0",
                    "-map", "1:a:0",
                    "-c:v", settings.VIDEO_CODEC,
                    *audio_encoding_args,
                    "-pix_fmt", "yuv420p",
                    "-t", str(duration_seconds),
                    str(output_path.resolve()),
                ]
                if not _execute_ffmpeg(cmd_no_sub):
                    raise RuntimeError(f"FFmpeg composition failed for avatar scene '{scene_id}'")

        elif not has_avatar:
            logger.info("Composing visual slide scene '%s' for locale '%s'", scene_id, locale)
            combined_filter = f"{norm_filter},{sub_filter}" if sub_filter else norm_filter
            base_cmd = [
                settings.FFMPEG_BINARY_PATH,
                "-y",
                "-loop", "1",
                "-i", str(visual_image_path.resolve()),
                "-i", str(audio_path.resolve()),
            ]
            if sub_filter:
                cmd_with_sub = base_cmd + [
                    "-vf", combined_filter,
                    "-map", "0:v:0",
                    "-map", "1:a:0",
                    "-c:v", settings.VIDEO_CODEC,
                    "-tune", "stillimage",
                    *audio_encoding_args,
                    "-pix_fmt", "yuv420p",
                    "-shortest",
                    "-t", str(duration_seconds),
                    str(output_path.resolve()),
                ]
                if _execute_ffmpeg(cmd_with_sub):
                    sub_burned = True
                else:
                    logger.info("Subtitle burn-in failed on scene '%s'; falling back to unburned render", scene_id)
            if not sub_burned:
                cmd_no_sub = base_cmd + [
                    "-vf", norm_filter,
                    "-map", "0:v:0",
                    "-map", "1:a:0",
                    "-c:v", settings.VIDEO_CODEC,
                    "-tune", "stillimage",
                    *audio_encoding_args,
                    "-pix_fmt", "yuv420p",
                    "-shortest",
                    "-t", str(duration_seconds),
                    str(output_path.resolve()),
                ]
                if not _execute_ffmpeg(cmd_no_sub):
                    raise RuntimeError(f"FFmpeg composition failed for visual scene '{scene_id}'")

        measured_dur = get_video_duration(output_path) or duration_seconds

        return SceneCompositionAsset(
            scene_id=scene_id,
            locale=locale,
            video_path=str(output_path.resolve()),
            duration_seconds=measured_dur,
            has_avatar=has_avatar,
            has_subtitles=sub_burned,
            status="completed",
        )

    def concatenate_scenes(
        self,
        scene_videos: List[SceneCompositionAsset],
        locale: str,
        output_path: Path,
    ) -> FinalVideoAsset:
        if not check_ffmpeg_available():
            raise RuntimeError(f"FFmpeg binary '{settings.FFMPEG_BINARY_PATH}' not available.")

        if not scene_videos:
            raise ValueError(f"No scene video assets provided for concatenation in locale '{locale}'.")

        output_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path = output_path.parent / f"concat_{locale}.txt"

        lines = [f"file '{Path(s.video_path).resolve().as_posix()}'" for s in scene_videos]
        manifest_path.write_text("\n".join(lines), encoding="utf-8")

        expected_dur = sum(s.duration_seconds for s in scene_videos)

        audio_encoding_args = [
            "-c:a", settings.AUDIO_CODEC,
            "-ar", str(settings.AUDIO_SAMPLE_RATE),
            "-ac", str(settings.AUDIO_CHANNELS),
            "-b:a", str(settings.AUDIO_BITRATE),
        ]

        # 1. Attempt fast stream copy concat
        copy_cmd = [
            settings.FFMPEG_BINARY_PATH,
            "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", str(manifest_path.resolve()),
            "-c", "copy",
            str(output_path.resolve()),
        ]
        res = subprocess.run(copy_cmd, capture_output=True, text=True, timeout=300)
        measured_dur = get_video_duration(output_path) if res.returncode == 0 else 0.0

        # Check if stream copy succeeded AND duration is strictly consistent with expected scenes
        need_reencode = (res.returncode != 0) or (abs(measured_dur - expected_dur) > 0.5)

        if need_reencode:
            logger.info(
                "Stream copy concat check failed (returncode=%d, measured=%.2fs vs expected=%.2fs). Re-encoding concatenation.",
                res.returncode,
                measured_dur,
                expected_dur,
            )
            reencode_cmd = [
                settings.FFMPEG_BINARY_PATH,
                "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", str(manifest_path.resolve()),
                "-c:v", settings.VIDEO_CODEC,
                *audio_encoding_args,
                "-pix_fmt", "yuv420p",
                str(output_path.resolve()),
            ]
            res_re = subprocess.run(reencode_cmd, capture_output=True, text=True, timeout=600)
            if res_re.returncode != 0:
                raise RuntimeError(f"FFmpeg concatenation failed: {res_re.stderr}")
            measured_dur = get_video_duration(output_path)

        # Cleanup manifest
        try:
            manifest_path.unlink(missing_ok=True)
        except Exception:
            pass

        return FinalVideoAsset(
            locale=locale,
            video_path=str(output_path.resolve()),
            total_duration_seconds=measured_dur or expected_dur,
            scene_count=len(scene_videos),
            scene_videos=scene_videos,
            status="completed",
            metadata={"provider": self.provider_name},
        )
