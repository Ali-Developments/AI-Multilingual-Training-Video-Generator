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
        layout_type: str = "presenter_split",
        presenter_position: str = "right",
        motion_video_path: Optional[Path] = None,
    ) -> SceneCompositionAsset:
        if not check_ffmpeg_available():
            raise RuntimeError(
                f"FFmpeg binary '{settings.FFMPEG_BINARY_PATH}' not found. "
                "Please install FFmpeg or set DEFAULT_COMPOSITION_PROVIDER='mock'."
            )

        if not audio_path.exists():
            raise FileNotFoundError(f"Required audio asset not found: {audio_path}")

        if duration_seconds <= 0.0:
            try:
                from app.services.tts.audio_probe import get_audio_duration
                duration_seconds = get_audio_duration(audio_path)
            except Exception:
                pass
            if duration_seconds <= 0.0:
                logger.warning("Scene '%s' has non-positive duration_seconds (%.2f); using safe fallback 1.0s.", scene_id, duration_seconds)
                duration_seconds = 1.0

        output_path.parent.mkdir(parents=True, exist_ok=True)
        has_avatar = bool(avatar_video_path and avatar_video_path.exists() and avatar_video_path.stat().st_size > 0)
        has_motion = bool(motion_video_path and motion_video_path.exists() and motion_video_path.stat().st_size > 0)
        has_image = bool(visual_image_path and visual_image_path.exists() and visual_image_path.stat().st_size > 0)
        has_visual = has_motion or has_image

        if not has_avatar and not has_visual:
            raise FileNotFoundError(
                f"Scene '{scene_id}' requires either a visual image, motion video, or avatar video segment."
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
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
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

        layout = (layout_type or "presenter_split").lower()
        pos = (presenter_position or "right").lower()

        # CASE 1: Presenter-Led Layouts
        if has_avatar:
            if layout in ("presenter_split", "presenter_overlay") and has_visual:
                logger.info("Composing presenter_split scene '%s' (presenter_pos=%s)", scene_id, pos)
                # Split proportions: Presenter = 42% (806px), Supporting Media = 58% (1114px)
                # Base media input: motion video or image
                media_input = str(motion_video_path.resolve()) if has_motion else str(visual_image_path.resolve())
                media_is_loop = not has_motion

                # Input 0: avatar, Input 1: media, Input 2: audio
                base_cmd = [settings.FFMPEG_BINARY_PATH, "-y", "-i", str(avatar_video_path.resolve())]
                if media_is_loop:
                    base_cmd.extend(["-loop", "1"])
                else:
                    base_cmd.extend(["-stream_loop", "-1"])
                base_cmd.extend(["-i", media_input, "-i", str(audio_path.resolve())])

                # Build filter complex with full-bleed presenter framing (no black bars)
                av_filter = "[0:v]scale=806:1080:force_original_aspect_ratio=increase,crop=806:1080,setsar=1[av];"
                med_filter = "[1:v]scale=1114:1080:force_original_aspect_ratio=increase,crop=1114:1080,setsar=1[med];"
                if pos == "left":
                    stack_filter = f"{av_filter}{med_filter}[av][med]hstack=inputs=2[stacked];[stacked]drawbox=x=805:y=0:w=3:h=1080:color=0x00E5FF@0.7:t=fill[composed]"
                else:  # right (default for RTL & modern studio)
                    stack_filter = f"{av_filter}{med_filter}[med][av]hstack=inputs=2[stacked];[stacked]drawbox=x=1112:y=0:w=3:h=1080:color=0x00E5FF@0.7:t=fill[composed]"

                final_split_filter = f"{stack_filter};[composed]{sub_filter}[sub_out]" if sub_filter else stack_filter
                out_map = "[sub_out]" if sub_filter else "[composed]"

                cmd_split = base_cmd + [
                    "-filter_complex", final_split_filter,
                    "-map", out_map,
                    "-map", "2:a:0",
                    "-c:v", settings.VIDEO_CODEC,
                    *audio_encoding_args,
                    "-pix_fmt", "yuv420p",
                    "-t", str(duration_seconds),
                    str(output_path.resolve()),
                ]

                if _execute_ffmpeg(cmd_split):
                    sub_burned = bool(sub_filter)
                else:
                    logger.warning("Presenter split with subtitles failed; retrying unburned")
                    cmd_split_no_sub = base_cmd + [
                        "-filter_complex", stack_filter,
                        "-map", "[composed]",
                        "-map", "2:a:0",
                        "-c:v", settings.VIDEO_CODEC,
                        *audio_encoding_args,
                        "-pix_fmt", "yuv420p",
                        "-t", str(duration_seconds),
                        str(output_path.resolve()),
                    ]
                    if _execute_ffmpeg(cmd_split_no_sub):
                        sub_burned = False
                    else:
                        logger.warning("Presenter split composition failed, falling back to centered presenter")
                        layout = "presenter_full"
            else:
                layout = "presenter_full"

            if layout in ("presenter_full", "pip", "presenter_overlay") and not sub_burned:
                # Presenter Full or Centered
                logger.info("Composing broadcast presenter_full scene '%s' for locale '%s'", scene_id, locale)
                # Dual-layer broadcast framing:
                # Layer 1 (Background): ambient blurred office background filled edge-to-edge (1920x1080)
                # Layer 2 (Foreground): crisp centered 1080p presenter
                bg_filter = "[0:v]split=2[fg][bg];[bg]scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,boxblur=25:25,eq=brightness=-0.15[bg_blur];"
                fg_filter = "[fg]scale=1080:1080:force_original_aspect_ratio=decrease[fg_scaled];"
                layer_filter = f"{bg_filter}{fg_filter}[bg_blur][fg_scaled]overlay=420:0[composed]"
                combined_filter = f"{layer_filter};[composed]{sub_filter}[sub_out]" if sub_filter else layer_filter
                out_map = "[sub_out]" if sub_filter else "[composed]"

                base_cmd = [
                    settings.FFMPEG_BINARY_PATH,
                    "-y",
                    "-i", str(avatar_video_path.resolve()),
                    "-i", str(audio_path.resolve()),
                ]
                cmd_full = base_cmd + [
                    "-filter_complex", combined_filter,
                    "-map", out_map,
                    "-map", "1:a:0",
                    "-c:v", settings.VIDEO_CODEC,
                    *audio_encoding_args,
                    "-pix_fmt", "yuv420p",
                    "-t", str(duration_seconds),
                    str(output_path.resolve()),
                ]
                if _execute_ffmpeg(cmd_full):
                    sub_burned = bool(sub_filter)
                else:
                    # Fallback unburned
                    cmd_no_sub = base_cmd + [
                        "-filter_complex", layer_filter,
                        "-map", "[composed]",
                        "-map", "1:a:0",
                        "-c:v", settings.VIDEO_CODEC,
                        *audio_encoding_args,
                        "-pix_fmt", "yuv420p",
                        "-t", str(duration_seconds),
                        str(output_path.resolve()),
                    ]
                    if not _execute_ffmpeg(cmd_no_sub):
                        raise RuntimeError(f"FFmpeg composition failed for avatar scene '{scene_id}'")

        # CASE 2: Non-Avatar Scenes (Media Full, Motion Visual, Quiz, Diagram)
        else:
            logger.info("Composing supporting media scene '%s' (has_motion=%s)", scene_id, has_motion)
            media_src = str(motion_video_path.resolve()) if has_motion else str(visual_image_path.resolve())
            combined_filter = f"{norm_filter},{sub_filter}" if sub_filter else norm_filter

            base_cmd = [settings.FFMPEG_BINARY_PATH, "-y"]
            if not has_motion:
                base_cmd.extend(["-loop", "1"])
            else:
                base_cmd.extend(["-stream_loop", "-1"])
            base_cmd.extend(["-i", media_src, "-i", str(audio_path.resolve())])

            cmd_media = base_cmd + [
                "-vf", combined_filter,
                "-map", "0:v:0",
                "-map", "1:a:0",
                "-c:v", settings.VIDEO_CODEC,
                *audio_encoding_args,
                "-pix_fmt", "yuv420p",
                "-t", str(duration_seconds),
                str(output_path.resolve()),
            ]
            if _execute_ffmpeg(cmd_media):
                sub_burned = bool(sub_filter)
            else:
                logger.info("Subtitle burn-in failed on media scene '%s'; rendering unburned", scene_id)
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
                    raise RuntimeError(f"FFmpeg composition failed for visual scene '{scene_id}'")

        measured_dur = get_video_duration(output_path) or duration_seconds

        # Technical validation with ffprobe
        from app.services.composition.ffmpeg_utils import validate_video_file
        try:
            validate_video_file(output_path, min_duration=0.1, require_video=True, require_audio=True)
        except Exception as ex:
            logger.error("Composed scene '%s' failed technical validation: %s", scene_id, ex)
            raise

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

        # Technical validation of final concatenated video with ffprobe
        from app.services.composition.ffmpeg_utils import validate_video_file
        try:
            validate_video_file(output_path, min_duration=0.5, require_video=True, require_audio=True)
        except Exception as ex:
            logger.error("Final concatenated video '%s' failed technical validation: %s", output_path, ex)
            raise

        return FinalVideoAsset(
            locale=locale,
            video_path=str(output_path.resolve()),
            total_duration_seconds=measured_dur or expected_dur,
            scene_count=len(scene_videos),
            scene_videos=scene_videos,
            status="completed",
            metadata={"provider": self.provider_name},
        )
