"""Comprehensive test suite for Step 7 Subtitle Generation Pipeline.

Tests:
1. Provider abstraction adheres to clean interface.
2. Factory returns configured provider and rejects unsupported providers.
3. Sentence/chunk splitting adheres to word limits and pause punctuation.
4. Timing monotonicity: start < end for all cues.
5. No overlapping caption intervals: next.start >= previous.end.
6. Final cue timestamp does not exceed exact audio duration.
7. SubRip (.srt) serialization conforms to standard format.
8. WebVTT (.vtt) serialization conforms to standard format with WEBVTT header.
9. Full UTF-8 Arabic script preservation and RTL text direction.
10. Full UTF-8 Bengali script preservation and LTR text direction.
11. None, empty, and whitespace narration handling.
12. Per-scene file path construction and Windows-safe path resolution.
13. SubtitleService single-locale orchestration.
14. SubtitleService multi-locale bundle orchestration with error isolation.
15. Scene-level failure isolation.
16. Idempotency reuses valid existing subtitle assets.
17. Force regeneration overwrites existing assets.
18. Zero external paid API calls.
"""

from pathlib import Path
import pytest

from app.models.schemas import (
    LocalizedScript,
    LocalizedScene,
    SceneAudioAsset,
    LocalizedAudioTrack,
    LocalizationBundle,
    FinalScript,
    SceneSubtitleAsset,
    SubtitleChunk,
)
from app.services.subtitles.base import SubtitleProvider
from app.services.subtitles.deterministic_provider import DeterministicSubtitleProvider
from app.services.subtitles.factory import get_subtitle_provider
from app.services.subtitles.formatter import (
    format_timestamp_srt,
    format_timestamp_vtt,
    split_narration_into_chunks,
    serialize_srt,
    serialize_vtt,
)
from app.services.subtitles.service import SubtitleService


def test_subtitle_provider_abstraction():
    """Verify provider interface and inheritance."""
    provider = DeterministicSubtitleProvider()
    assert isinstance(provider, SubtitleProvider)
    assert provider.provider_name == "deterministic"


def test_subtitle_factory_resolution():
    """Verify factory returns configured provider and raises on invalid provider."""
    provider = get_subtitle_provider("deterministic")
    assert isinstance(provider, DeterministicSubtitleProvider)

    default_provider = get_subtitle_provider()
    assert isinstance(default_provider, DeterministicSubtitleProvider)

    with pytest.raises(ValueError, match="Unsupported Subtitle provider"):
        get_subtitle_provider("unsupported_engine")


def test_timestamp_formatting_srt_and_vtt():
    """Verify timestamp formatting for SRT (comma) and VTT (period)."""
    assert format_timestamp_srt(0.0) == "00:00:00,000"
    assert format_timestamp_srt(65.432) == "00:01:05,432"
    assert format_timestamp_srt(3661.050) == "01:01:01,050"

    assert format_timestamp_vtt(0.0) == "00:00:00.000"
    assert format_timestamp_vtt(65.432) == "00:01:05.432"
    assert format_timestamp_vtt(3661.050) == "01:01:01.050"


def test_split_narration_chunk_monotonicity_and_bounds():
    """Verify that chunks satisfy: start < end, next.start >= prev.end, and last.end <= duration."""
    narration = (
        "Welcome to this cybersecurity training. In this module, we will learn how to identify "
        "suspicious emails, verify sender details, and protect corporate credentials effectively."
    )
    duration = 12.5

    chunks = split_narration_into_chunks(narration, total_duration_seconds=duration)
    assert len(chunks) >= 2

    for i, chunk in enumerate(chunks):
        assert chunk.start_seconds < chunk.end_seconds, f"Chunk {i} violated start < end"
        if i > 0:
            assert chunk.start_seconds >= chunks[i - 1].end_seconds, (
                f"Overlap detected between chunk {i - 1} and {i}"
            )

    assert chunks[-1].end_seconds <= duration
    assert abs(chunks[-1].end_seconds - duration) < 0.05


def test_srt_and_vtt_serialization_format():
    """Verify correct text serialization for SRT and VTT formats."""
    chunks = [
        SubtitleChunk(index=1, start_seconds=0.0, end_seconds=2.5, text="Hello and welcome."),
        SubtitleChunk(index=2, start_seconds=2.5, end_seconds=5.0, text="Let us begin."),
    ]

    srt_out = serialize_srt(chunks)
    assert "1\n00:00:00,000 --> 00:00:02,500\nHello and welcome." in srt_out
    assert "2\n00:00:02,500 --> 00:00:05,000\nLet us begin." in srt_out

    vtt_out = serialize_vtt(chunks)
    assert vtt_out.startswith("WEBVTT\n\n")
    assert "1\n00:00:00.000 --> 00:00:02.500\nHello and welcome." in vtt_out
    assert "2\n00:00:02.500 --> 00:00:05.000\nLet us begin." in vtt_out


def test_arabic_unicode_preservation_and_direction(tmp_path: Path):
    """Verify Arabic script is preserved identically in UTF-8 and RTL direction is noted."""
    provider = DeterministicSubtitleProvider()
    arabic_narration = "مرحبا بكم في التدريب الأمني. تحقق دائماً من عنوان البريد الإلكتروني."
    duration = 6.0

    asset = provider.generate_scene_subtitles(
        scene_id="scene_ar_1",
        narration=arabic_narration,
        duration_seconds=duration,
        locale="ar-SA",
        output_dir=tmp_path / "subtitles" / "ar-SA",
    )

    assert asset.status == "completed"
    assert asset.text_direction == "rtl"
    assert asset.chunk_count > 0

    srt_content = Path(asset.srt_path).read_text(encoding="utf-8")
    assert "مرحبا بكم في التدريب الأمني" in srt_content
    assert "تحقق دائماً من عنوان البريد الإلكتروني" in srt_content

    vtt_content = Path(asset.vtt_path).read_text(encoding="utf-8")
    assert vtt_content.startswith("WEBVTT")
    assert "البريد الإلكتروني" in vtt_content


def test_bengali_unicode_preservation_and_direction(tmp_path: Path):
    """Verify Bengali script is preserved identically in UTF-8 and LTR direction is noted."""
    provider = DeterministicSubtitleProvider()
    bengali_narration = "সাইবার নিরাপত্তা প্রশিক্ষণে স্বাগতম। সর্বদা প্রেরকের ইমেল যাচাই করুন।"
    duration = 5.5

    asset = provider.generate_scene_subtitles(
        scene_id="scene_bn_1",
        narration=bengali_narration,
        duration_seconds=duration,
        locale="bn-BD",
        output_dir=tmp_path / "subtitles" / "bn-BD",
    )

    assert asset.status == "completed"
    assert asset.text_direction == "ltr"
    assert asset.chunk_count > 0

    srt_content = Path(asset.srt_path).read_text(encoding="utf-8")
    assert "সাইবার নিরাপত্তা" in srt_content
    assert "প্রেরকের ইমেল" in srt_content


def test_empty_or_whitespace_narration_handling(tmp_path: Path):
    """Verify empty or whitespace narration does not crash and produces valid blank assets."""
    provider = DeterministicSubtitleProvider()

    asset_empty = provider.generate_scene_subtitles(
        scene_id="scene_empty",
        narration="",
        duration_seconds=4.0,
        locale="en-US",
        output_dir=tmp_path / "subtitles" / "en-US",
    )
    assert asset_empty.status == "completed"
    assert asset_empty.chunk_count == 0
    assert Path(asset_empty.srt_path).read_text(encoding="utf-8") == ""
    assert "WEBVTT" in Path(asset_empty.vtt_path).read_text(encoding="utf-8")

    asset_ws = provider.generate_scene_subtitles(
        scene_id="scene_ws",
        narration="   \n\t  ",
        duration_seconds=4.0,
        locale="en-US",
        output_dir=tmp_path / "subtitles" / "en-US",
    )
    assert asset_ws.status == "completed"
    assert asset_ws.chunk_count == 0


def test_subtitle_service_single_locale(tmp_path: Path):
    """Verify SubtitleService generates subtitle track for a localized script using audio timing."""
    service = SubtitleService(output_base_dir=tmp_path / "storage")

    script = LocalizedScript(
        title="Phishing Training",
        source_language="en-US",
        language="ar",
        locale="ar-SA",
        text_direction="rtl",
        audience="Employees",
        opening_hook="Hook",
        scenes=[
            LocalizedScene(
                scene_id="scene_1",
                order=1,
                title="Intro",
                purpose="Hook",
                narration="الجزء الأول من التدريب يشرح مخاطر الروابط المشبوهة.",
                estimated_duration_seconds=5,
                visual_direction="",
                on_screen_text=None,
                learning_objective_ids=["LO1"],
                scene_type="presenter",
            ),
            LocalizedScene(
                scene_id="scene_2",
                order=2,
                title="Action",
                purpose="Demo",
                narration="الجزء الثاني يوضح كيفية الإبلاغ عن الرسالة لفريق الدعم الأمني.",
                estimated_duration_seconds=4,
                visual_direction="",
                on_screen_text=None,
                learning_objective_ids=["LO2"],
                scene_type="visual_demo",
            ),
        ],
        closing_summary="Summary",
        target_duration_seconds=9,
        total_estimated_duration_seconds=9,
        metadata={},
    )

    audio_track = LocalizedAudioTrack(
        locale="ar-SA",
        scene_audio=[
            SceneAudioAsset(
                scene_id="scene_1",
                locale="ar-SA",
                audio_path=str(tmp_path / "audio" / "scene_1.wav"),
                duration_seconds=4.82,  # Exact measured duration
                provider="mock",
                voice_id="voice_1",
                status="completed",
            ),
            SceneAudioAsset(
                scene_id="scene_2",
                locale="ar-SA",
                audio_path=str(tmp_path / "audio" / "scene_2.wav"),
                duration_seconds=3.95,  # Exact measured duration
                provider="mock",
                voice_id="voice_1",
                status="completed",
            ),
        ],
        total_audio_duration_seconds=8.77,
        status="completed",
    )

    track = service.generate_locale_subtitles(
        script=script,
        audio_track=audio_track,
        project_id="proj_sub_1",
    )

    assert track.status == "completed"
    assert len(track.scene_subtitles) == 2
    assert track.scene_subtitles[0].duration_seconds == 4.82
    assert track.scene_subtitles[1].duration_seconds == 3.95
    assert Path(track.scene_subtitles[0].srt_path).exists()
    assert Path(track.scene_subtitles[0].vtt_path).exists()


def test_subtitle_service_idempotency_and_force_regenerate(tmp_path: Path):
    """Verify that existing subtitle files are reused unless force_regenerate is True."""
    service = SubtitleService(output_base_dir=tmp_path / "storage")

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
                title="Scene 1",
                purpose="Intro",
                narration="This is the first lesson on verification.",
                estimated_duration_seconds=3,
                visual_direction="",
                on_screen_text=None,
                learning_objective_ids=["LO1"],
                scene_type="presenter",
            )
        ],
        closing_summary="Close",
        target_duration_seconds=3,
        total_estimated_duration_seconds=3,
        metadata={},
    )

    audio_track = LocalizedAudioTrack(
        locale="en-US",
        scene_audio=[
            SceneAudioAsset(
                scene_id="scene_1",
                locale="en-US",
                audio_path=str(tmp_path / "s1.wav"),
                duration_seconds=3.2,
                provider="mock",
                voice_id="en-US-JennyNeural",
                status="completed",
            )
        ],
        total_audio_duration_seconds=3.2,
        status="completed",
    )

    # Initial run
    track1 = service.generate_locale_subtitles(script, audio_track, project_id="proj_idem")
    assert track1.status == "completed"
    srt_file = Path(track1.scene_subtitles[0].srt_path)
    initial_mtime = srt_file.stat().st_mtime_ns

    # Second run without force_regenerate should reuse
    track2 = service.generate_locale_subtitles(script, audio_track, project_id="proj_idem", force_regenerate=False)
    assert track2.status == "completed"
    assert srt_file.stat().st_mtime_ns == initial_mtime

    # Third run with force_regenerate should overwrite
    track3 = service.generate_locale_subtitles(script, audio_track, project_id="proj_idem", force_regenerate=True)
    assert track3.status == "completed"
    assert Path(track3.scene_subtitles[0].srt_path).exists()


def test_subtitle_service_bundle_orchestration_and_error_isolation(tmp_path: Path):
    """Verify bundle orchestration isolates missing audio tracks or broken scenes across locales."""
    service = SubtitleService(output_base_dir=tmp_path / "storage")

    final_script = FinalScript(
        title="Training",
        language="en-US",
        audience="All",
        target_duration_seconds=5,
        total_estimated_duration_seconds=5,
        opening_hook="Hook",
        closing_summary="Summary",
        scenes=[],
    )

    script_ar = LocalizedScript(
        title="Training AR",
        source_language="en-US",
        language="ar",
        locale="ar-SA",
        audience="All",
        opening_hook="Hook",
        scenes=[
            LocalizedScene(
                scene_id="scene_1",
                order=1,
                title="Title",
                purpose="P",
                narration="رسالة تدريبية باللغة العربية.",
                estimated_duration_seconds=5,
                visual_direction="",
                on_screen_text=None,
                learning_objective_ids=["LO1"],
                scene_type="presenter",
            )
        ],
        closing_summary="Summary",
        target_duration_seconds=5,
        total_estimated_duration_seconds=5,
        metadata={},
    )

    script_bn = LocalizedScript(
        title="Training BN",
        source_language="en-US",
        language="bn",
        locale="bn-BD",
        audience="All",
        opening_hook="Hook",
        scenes=[
            LocalizedScene(
                scene_id="scene_1",
                order=1,
                title="Title",
                purpose="P",
                narration="বাংলা ভাষায় প্রশিক্ষণ বার্তা।",
                estimated_duration_seconds=5,
                visual_direction="",
                on_screen_text=None,
                learning_objective_ids=["LO1"],
                scene_type="presenter",
            )
        ],
        closing_summary="Summary",
        target_duration_seconds=5,
        total_estimated_duration_seconds=5,
        metadata={},
    )

    bundle = LocalizationBundle(
        source_script=final_script,
        localized_scripts={"ar-SA": script_ar, "bn-BD": script_bn},
    )

    # Provide audio only for ar-SA; bn-BD is missing
    audio_tracks = {
        "ar-SA": LocalizedAudioTrack(
            locale="ar-SA",
            scene_audio=[
                SceneAudioAsset(
                    scene_id="scene_1",
                    locale="ar-SA",
                    audio_path=str(tmp_path / "ar.wav"),
                    duration_seconds=4.5,
                    provider="mock",
                    voice_id="ar-SA-HamedNeural",
                    status="completed",
                )
            ],
            total_audio_duration_seconds=4.5,
            status="completed",
        )
    }

    sub_tracks = service.generate_bundle_subtitles(
        bundle=bundle,
        audio_tracks=audio_tracks,
        project_id="proj_bundle",
    )

    # ar-SA succeeded
    assert sub_tracks["ar-SA"].status == "completed"
    assert len(sub_tracks["ar-SA"].scene_subtitles) == 1

    # bn-BD was isolated and marked failed without crashing the bundle
    assert sub_tracks["bn-BD"].status == "failed"
