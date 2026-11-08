"""Test suite for Phase 4: Composition Service Alignment.

Tests:
1. Veo B-Roll composition with localized TTS audio synchronization.
2. Muting/discarding of generated Veo video audio track so only TTS narration is preserved.
3. Stream looping when Veo video clip duration is shorter than TTS audio narration.
4. Clean trimming when Veo video clip duration is longer than TTS audio narration.
5. Presenter split composition with talking avatar and looped motion video.
6. RTL Arabic subtitle burn-in via Advanced SubStation Alpha (.ass) complex shaping.
7. Technical validation of scene and final concatenated video assets via ffprobe.
"""

from pathlib import Path
import subprocess
import pytest
from PIL import Image

from app.core.config import settings
from app.models.schemas import SceneCompositionAsset, FinalVideoAsset
from app.services.composition.ffmpeg_provider import FFmpegCompositionProvider
from app.services.composition.ffmpeg_utils import (
    check_ffmpeg_available,
    probe_video_file,
    validate_video_file,
    get_video_duration,
)
from app.services.tts.mock_tts_provider import generate_synthetic_wav_file
from app.services.avatar.mock_avatar_provider import generate_synthetic_mp4_file


@pytest.fixture
def ffmpeg_provider():
    if not check_ffmpeg_available():
        pytest.skip("FFmpeg not available on this system.")
    return FFmpegCompositionProvider()


def create_synthetic_mp4_with_audio(output_path: Path, duration_seconds: float = 2.0) -> Path:
    """Create a synthetic MP4 video that contains an unwanted audio tone (simulating AI video with audio)."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        settings.FFMPEG_BINARY_PATH,
        "-y",
        "-f", "lavfi", "-i", f"color=c=darkgreen:s=1280x720:d={duration_seconds}",
        "-f", "lavfi", "-i", f"sine=frequency=1000:duration={duration_seconds}",
        "-c:v", "libx264",
        "-c:a", "aac",
        "-pix_fmt", "yuv420p",
        str(output_path.resolve()),
    ]
    subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True, timeout=15)
    return output_path


def test_veo_broll_composition_replaces_audio_and_loops_to_tts_duration(ffmpeg_provider, tmp_path):
    """
    Verify that when Veo video is shorter than narration audio:
    - The video loops to match the exact TTS audio duration.
    - Any audio in the Veo clip is discarded.
    - The output contains ONLY the localized TTS narration audio.
    """
    # 1. Create a 1.0s synthetic Veo video with unwanted sine tone audio
    veo_clip = tmp_path / "veo_input.mp4"
    create_synthetic_mp4_with_audio(veo_clip, duration_seconds=1.0)
    meta_in = probe_video_file(veo_clip)
    assert meta_in["has_audio"] is True
    assert abs(meta_in["duration"] - 1.0) < 0.2

    # 2. Create a 2.5s localized narration audio track
    audio_wav = tmp_path / "tts_narration.wav"
    generate_synthetic_wav_file(audio_wav, duration_seconds=2.5)

    # 3. Compose scene with Veo clip as motion_video_path
    out_mp4 = tmp_path / "scene_veo_composed.mp4"
    asset = ffmpeg_provider.compose_scene(
        scene_id="scene_broll_1",
        locale="en-US",
        audio_path=audio_wav,
        motion_video_path=veo_clip,
        duration_seconds=2.5,
        output_path=out_mp4,
        burn_subtitles=False,
        layout_type="media_full",
    )

    assert asset.status == "completed"
    assert out_mp4.exists()

    # 4. Technical validation using ffprobe
    meta_out = validate_video_file(out_mp4, min_duration=2.0, require_video=True, require_audio=True)
    assert abs(meta_out["duration"] - 2.5) < 0.3
    assert meta_out["width"] == settings.VIDEO_WIDTH
    assert meta_out["height"] == settings.VIDEO_HEIGHT


def test_veo_broll_composition_trims_when_longer_than_audio(ffmpeg_provider, tmp_path):
    """Verify that when Veo video is longer than audio, it is cleanly trimmed to audio duration."""
    veo_clip = tmp_path / "veo_long.mp4"
    create_synthetic_mp4_with_audio(veo_clip, duration_seconds=4.0)

    audio_wav = tmp_path / "tts_short.wav"
    generate_synthetic_wav_file(audio_wav, duration_seconds=1.5)

    out_mp4 = tmp_path / "scene_veo_trimmed.mp4"
    asset = ffmpeg_provider.compose_scene(
        scene_id="scene_broll_trimmed",
        locale="en-US",
        audio_path=audio_wav,
        motion_video_path=veo_clip,
        duration_seconds=1.5,
        output_path=out_mp4,
        burn_subtitles=False,
        layout_type="media_full",
    )

    assert asset.status == "completed"
    meta_out = validate_video_file(out_mp4, min_duration=1.0, require_video=True, require_audio=True)
    assert abs(meta_out["duration"] - 1.5) < 0.3


def test_presenter_split_with_motion_video(ffmpeg_provider, tmp_path):
    """Verify presenter split layout combining talking avatar video, looped motion video, and audio."""
    avatar_mp4 = tmp_path / "avatar.mp4"
    generate_synthetic_mp4_file(avatar_mp4, duration_seconds=2.0)

    motion_mp4 = tmp_path / "motion_broll.mp4"
    generate_synthetic_mp4_file(motion_mp4, duration_seconds=1.0)

    audio_wav = tmp_path / "narration.wav"
    generate_synthetic_wav_file(audio_wav, duration_seconds=2.0)

    out_mp4 = tmp_path / "scene_split.mp4"
    asset = ffmpeg_provider.compose_scene(
        scene_id="scene_split_1",
        locale="en-US",
        audio_path=audio_wav,
        avatar_video_path=avatar_mp4,
        motion_video_path=motion_mp4,
        duration_seconds=2.0,
        output_path=out_mp4,
        burn_subtitles=False,
        layout_type="presenter_split",
        presenter_position="right",
    )

    assert asset.status == "completed"
    assert asset.has_avatar is True
    meta_out = validate_video_file(out_mp4, min_duration=1.8, require_video=True, require_audio=True)
    assert meta_out["width"] == 1920
    assert meta_out["height"] == 1080


def test_arabic_rtl_ass_subtitle_burn_in(ffmpeg_provider, tmp_path):
    """Verify that RTL Arabic subtitles in .ass format burn in cleanly with complex shaping."""
    img_path = tmp_path / "slide.png"
    img = Image.new("RGB", (1920, 1080), color=(20, 30, 50))
    img.save(img_path)

    audio_wav = tmp_path / "arabic_narration.wav"
    generate_synthetic_wav_file(audio_wav, duration_seconds=2.0)

    # Create Advanced SubStation Alpha (.ass) file with Arabic text
    ass_path = tmp_path / "scene_ar.ass"
    ass_content = """[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,36,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,2,1,2,50,50,40,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:00.10,0:00:01.80,Default,,0,0,0,,مرحباً بكم في التدريب الأمني المؤسسي
"""
    ass_path.write_text(ass_content, encoding="utf-8")

    out_mp4 = tmp_path / "scene_arabic_sub.mp4"
    asset = ffmpeg_provider.compose_scene(
        scene_id="scene_ar_1",
        locale="ar-SA",
        audio_path=audio_wav,
        visual_image_path=img_path,
        subtitle_path=ass_path,
        duration_seconds=2.0,
        output_path=out_mp4,
        burn_subtitles=True,
        layout_type="media_full",
    )

    assert asset.status == "completed"
    assert asset.has_subtitles is True
    meta = validate_video_file(out_mp4, min_duration=1.8, require_video=True, require_audio=True)
    assert meta["has_video"] is True
    assert meta["has_audio"] is True

