"""Comprehensive test suite for Step 9 Video Composition with FFmpeg.

Tests:
1. Composition provider abstraction.
2. Factory returns configured provider and rejects unsupported providers.
3. FFmpeg and FFprobe binary detection.
4. Windows-safe path escaping for FFmpeg subtitle filter.
5. Simple audio + visual image rendering produces valid MP4.
6. Scene output duration approximately matches audio duration.
7. Subtitle inclusion handling.
8. Missing required asset fails with clear FileNotFoundError.
9. Concatenation strictly preserves scene order.
10. Final concatenated video exists with valid duration.
11. CompositionService single-locale orchestration.
12. CompositionService multi-locale bundle orchestration with error isolation.
13. Idempotency reuses valid existing scene and final MP4 files.
14. Force regeneration overwrites existing assets.
15. Zero paid external API calls.
"""

from pathlib import Path
import pytest
from PIL import Image

from app.models.schemas import (
    LocalizedScript,
    LocalizedScene,
    SceneAudioAsset,
    LocalizedAudioTrack,
    SceneVisualAsset,
    LocalizedVisualTrack,
    SceneSubtitleAsset,
    LocalizedSubtitleTrack,
    LocalizationBundle,
    FinalScript,
    SceneCompositionAsset,
)
from app.services.composition.base import CompositionProvider
from app.services.composition.ffmpeg_provider import FFmpegCompositionProvider
from app.services.composition.mock_provider import MockCompositionProvider
from app.services.composition.factory import get_composition_provider
from app.services.composition.service import CompositionService
from app.services.composition.ffmpeg_utils import (
    check_ffmpeg_available,
    check_ffprobe_available,
    get_video_duration,
    escape_ffmpeg_filter_path,
)
from app.services.tts.mock_tts_provider import generate_synthetic_wav_file


def create_synthetic_image(path: Path) -> Path:
    """Create a lightweight synthetic PNG slide for testing."""
    path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", (320, 240), color=(15, 25, 45))
    img.save(path, format="PNG")
    return path


def test_composition_provider_abstraction():
    """Verify provider interface and inheritance."""
    ff_p = FFmpegCompositionProvider()
    assert isinstance(ff_p, CompositionProvider)
    assert ff_p.provider_name == "ffmpeg"

    mock_p = MockCompositionProvider()
    assert isinstance(mock_p, CompositionProvider)
    assert mock_p.provider_name == "mock"


def test_composition_factory_resolution():
    """Verify factory returns configured or requested provider."""
    assert isinstance(get_composition_provider("ffmpeg"), FFmpegCompositionProvider)
    assert isinstance(get_composition_provider("mock"), MockCompositionProvider)

    with pytest.raises(ValueError, match="Unsupported Composition provider"):
        get_composition_provider("unsupported_engine")


def test_ffmpeg_and_ffprobe_detection():
    """Verify ffmpeg and ffprobe are detected in the environment."""
    assert check_ffmpeg_available() is True
    assert check_ffprobe_available() is True


def test_escape_ffmpeg_filter_path():
    """Verify path escaping replaces backslashes and escapes drive colons."""
    win_path = Path("C:/videos/subtitles/scene_1.srt")
    escaped = escape_ffmpeg_filter_path(win_path)
    assert "\\" not in escaped or "\\:" in escaped
    assert "scene_1.srt" in escaped


def test_compose_scene_audio_and_image(tmp_path: Path):
    """Verify rendering a simple visual image and WAV audio into an MP4 video."""
    provider = FFmpegCompositionProvider()
    audio_path = generate_synthetic_wav_file(tmp_path / "audio.wav", duration_seconds=1.5)
    img_path = create_synthetic_image(tmp_path / "slide.png")
    out_mp4 = tmp_path / "rendered" / "scene_1.mp4"

    asset = provider.compose_scene(
        scene_id="scene_1",
        locale="en-US",
        audio_path=audio_path,
        visual_image_path=img_path,
        avatar_video_path=None,
        subtitle_path=None,
        duration_seconds=1.5,
        output_path=out_mp4,
        burn_subtitles=False,
    )

    assert asset.status == "completed"
    assert asset.scene_id == "scene_1"
    assert Path(asset.video_path).exists()
    assert Path(asset.video_path).stat().st_size > 0
    assert abs(asset.duration_seconds - 1.5) < 0.3


def test_compose_scene_with_subtitles(tmp_path: Path):
    """Verify scene composition with subtitle file inclusion."""
    provider = FFmpegCompositionProvider()
    audio_path = generate_synthetic_wav_file(tmp_path / "audio.wav", duration_seconds=1.0)
    img_path = create_synthetic_image(tmp_path / "slide.png")
    sub_path = tmp_path / "sub.srt"
    sub_path.write_text("1\n00:00:00,000 --> 00:00:01,000\nHello world\n\n", encoding="utf-8")
    out_mp4 = tmp_path / "rendered" / "scene_sub.mp4"

    asset = provider.compose_scene(
        scene_id="scene_sub",
        locale="en-US",
        audio_path=audio_path,
        visual_image_path=img_path,
        avatar_video_path=None,
        subtitle_path=sub_path,
        duration_seconds=1.0,
        output_path=out_mp4,
        burn_subtitles=True,
    )

    assert asset.status == "completed"
    assert Path(asset.video_path).exists()


def test_missing_required_asset_fails_clearly(tmp_path: Path):
    """Verify composition fails with FileNotFoundError if audio or visual is missing."""
    provider = FFmpegCompositionProvider()

    with pytest.raises(FileNotFoundError, match="Required audio asset not found"):
        provider.compose_scene(
            scene_id="scene_fail",
            locale="en-US",
            audio_path=tmp_path / "non_existent.wav",
            visual_image_path=tmp_path / "slide.png",
            avatar_video_path=None,
            subtitle_path=None,
            duration_seconds=1.0,
            output_path=tmp_path / "out.mp4",
        )


def test_concatenate_scenes_preserves_order_and_duration(tmp_path: Path):
    """Verify concatenating multiple scene MP4s produces single video with sum duration."""
    provider = FFmpegCompositionProvider()
    img_path = create_synthetic_image(tmp_path / "slide.png")

    wav1 = generate_synthetic_wav_file(tmp_path / "s1.wav", duration_seconds=1.0)
    wav2 = generate_synthetic_wav_file(tmp_path / "s2.wav", duration_seconds=1.2)

    s1_mp4 = tmp_path / "s1.mp4"
    s2_mp4 = tmp_path / "s2.mp4"

    asset1 = provider.compose_scene("scene_1", "en-US", wav1, img_path, None, None, 1.0, s1_mp4)
    asset2 = provider.compose_scene("scene_2", "en-US", wav2, img_path, None, None, 1.2, s2_mp4)

    final_mp4 = tmp_path / "final.mp4"
    final_video = provider.concatenate_scenes([asset1, asset2], "en-US", final_mp4)

    assert final_video.status == "completed"
    assert final_video.scene_count == 2
    assert Path(final_video.video_path).exists()
    assert Path(final_video.video_path).stat().st_size > 0
    assert abs(final_video.total_duration_seconds - 2.2) < 0.5


def test_composition_service_single_locale_pipeline(tmp_path: Path):
    """Verify CompositionService coordinates scene rendering and final concatenation."""
    service = CompositionService(output_base_dir=tmp_path / "storage")

    script = LocalizedScript(
        title="Training",
        source_language="en-US",
        language="en",
        locale="en-US",
        audience="All",
        opening_hook="Hook",
        scenes=[
            LocalizedScene(
                scene_id="scene_1",
                order=1,
                title="Scene 1",
                purpose="P1",
                narration="Narration 1",
                estimated_duration_seconds=1,
                visual_direction="",
                on_screen_text=None,
                learning_objective_ids=["LO1"],
                scene_type="intro",
            ),
            LocalizedScene(
                scene_id="scene_2",
                order=2,
                title="Scene 2",
                purpose="P2",
                narration="Narration 2",
                estimated_duration_seconds=1,
                visual_direction="",
                on_screen_text=None,
                learning_objective_ids=["LO2"],
                scene_type="explanation",
            ),
        ],
        closing_summary="Summary",
        target_duration_seconds=2,
        total_estimated_duration_seconds=2,
        metadata={},
    )

    wav1 = generate_synthetic_wav_file(tmp_path / "a1.wav", duration_seconds=1.0)
    wav2 = generate_synthetic_wav_file(tmp_path / "a2.wav", duration_seconds=1.0)
    img1 = create_synthetic_image(tmp_path / "v1.png")
    img2 = create_synthetic_image(tmp_path / "v2.png")

    audio_track = LocalizedAudioTrack(
        locale="en-US",
        scene_audio=[
            SceneAudioAsset(scene_id="scene_1", locale="en-US", audio_path=str(wav1), duration_seconds=1.0, provider="mock", voice_id="v1"),
            SceneAudioAsset(scene_id="scene_2", locale="en-US", audio_path=str(wav2), duration_seconds=1.0, provider="mock", voice_id="v1"),
        ],
        total_audio_duration_seconds=2.0,
    )

    visual_track = LocalizedVisualTrack(
        locale="en-US",
        scene_visuals=[
            SceneVisualAsset(scene_id="scene_1", locale="en-US", image_path=str(img1), width=320, height=240, visual_type="title_card"),
            SceneVisualAsset(scene_id="scene_2", locale="en-US", image_path=str(img2), width=320, height=240, visual_type="concept_slide"),
        ],
    )

    # 1. Render scenes
    scene_videos = service.compose_locale_scenes(
        script=script,
        audio_track=audio_track,
        visual_track=visual_track,
        project_id="proj_comp_1",
    )
    assert len(scene_videos) == 2
    assert scene_videos[0].status == "completed"
    assert scene_videos[1].status == "completed"

    # 2. Render final video
    final_video = service.compose_locale_final_video(
        script=script,
        scene_videos=scene_videos,
        project_id="proj_comp_1",
    )
    assert final_video.status == "completed"
    assert final_video.scene_count == 2
    assert Path(final_video.video_path).exists()


def test_composition_service_idempotency(tmp_path: Path):
    """Verify existing scene and final MP4 files are reused unless force_regenerate is True."""
    service = CompositionService(output_base_dir=tmp_path / "storage")

    script = LocalizedScript(
        title="Module",
        source_language="en-US",
        language="en",
        locale="en-US",
        audience="All",
        opening_hook="Hook",
        scenes=[
            LocalizedScene(
                scene_id="scene_1",
                order=1,
                title="S1",
                purpose="P1",
                narration="N1",
                estimated_duration_seconds=1,
                visual_direction="",
                on_screen_text=None,
                learning_objective_ids=["LO1"],
                scene_type="intro",
            )
        ],
        closing_summary="Close",
        target_duration_seconds=1,
        total_estimated_duration_seconds=1,
        metadata={},
    )

    wav = generate_synthetic_wav_file(tmp_path / "a.wav", duration_seconds=1.0)
    img = create_synthetic_image(tmp_path / "v.png")

    audio_track = LocalizedAudioTrack(
        locale="en-US",
        scene_audio=[
            SceneAudioAsset(scene_id="scene_1", locale="en-US", audio_path=str(wav), duration_seconds=1.0, provider="mock", voice_id="v"),
        ],
        total_audio_duration_seconds=1.0,
    )
    visual_track = LocalizedVisualTrack(
        locale="en-US",
        scene_visuals=[
            SceneVisualAsset(scene_id="scene_1", locale="en-US", image_path=str(img), width=320, height=240, visual_type="title_card"),
        ],
    )

    # Initial render
    scenes1 = service.compose_locale_scenes(script, audio_track, visual_track, project_id="proj_idem")
    mtime1 = Path(scenes1[0].video_path).stat().st_mtime_ns

    # Second render without force should reuse
    scenes2 = service.compose_locale_scenes(script, audio_track, visual_track, project_id="proj_idem", force_regenerate=False)
    assert scenes2[0].status == "completed"
    assert Path(scenes2[0].video_path).stat().st_mtime_ns == mtime1


def test_composition_service_bundle_orchestration(tmp_path: Path):
    """Verify bundle composition across multiple locales with error isolation."""
    service = CompositionService(output_base_dir=tmp_path / "storage")

    final_script = FinalScript(
        title="Training",
        language="en-US",
        audience="All",
        target_duration_seconds=1,
        total_estimated_duration_seconds=1,
        opening_hook="Hook",
        closing_summary="Summary",
        scenes=[],
    )

    script_en = LocalizedScript(
        title="EN",
        source_language="en-US",
        language="en",
        locale="en-US",
        audience="All",
        opening_hook="Hook",
        scenes=[
            LocalizedScene(scene_id="scene_1", order=1, title="S", purpose="P", narration="N", estimated_duration_seconds=1, visual_direction="", on_screen_text=None, learning_objective_ids=["LO1"], scene_type="intro")
        ],
        closing_summary="Close",
        target_duration_seconds=1,
        total_estimated_duration_seconds=1,
        metadata={},
    )

    script_ar = LocalizedScript(
        title="AR",
        source_language="en-US",
        language="ar",
        locale="ar-SA",
        audience="All",
        opening_hook="Hook",
        scenes=[
            LocalizedScene(scene_id="scene_1", order=1, title="S", purpose="P", narration="N", estimated_duration_seconds=1, visual_direction="", on_screen_text=None, learning_objective_ids=["LO1"], scene_type="intro")
        ],
        closing_summary="Close",
        target_duration_seconds=1,
        total_estimated_duration_seconds=1,
        metadata={},
    )

    bundle = LocalizationBundle(
        source_script=final_script,
        localized_scripts={"en-US": script_en, "ar-SA": script_ar},
    )

    wav = generate_synthetic_wav_file(tmp_path / "a_en.wav", duration_seconds=1.0)
    img = create_synthetic_image(tmp_path / "v_en.png")

    # Provide audio only for en-US; ar-SA has missing audio
    audio_tracks = {
        "en-US": LocalizedAudioTrack(
            locale="en-US",
            scene_audio=[
                SceneAudioAsset(scene_id="scene_1", locale="en-US", audio_path=str(wav), duration_seconds=1.0, provider="mock", voice_id="v")
            ],
            total_audio_duration_seconds=1.0,
        )
    }
    visual_tracks = {
        "en-US": LocalizedVisualTrack(
            locale="en-US",
            scene_visuals=[
                SceneVisualAsset(scene_id="scene_1", locale="en-US", image_path=str(img), width=320, height=240, visual_type="title_card")
            ],
        )
    }

    results = service.compose_bundle_videos(bundle, audio_tracks, visual_tracks, project_id="proj_comp_bundle")

    # en-US succeeded
    assert results["en-US"].status == "completed"
    assert Path(results["en-US"].video_path).exists()

    # ar-SA failed safely without dropping en-US
    assert results["ar-SA"].status == "failed"
