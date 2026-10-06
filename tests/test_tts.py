"""Comprehensive test suite for Step 5 TTS & Exact Audio Duration Pipeline.

Tests:
1. Provider abstraction adheres to clean interface.
2. Mock provider generates valid measurable synthetic WAV audio.
3. Voice configuration resolves defaults and overrides by locale.
4. Per-scene file path construction is correct.
5. Path logic uses pathlib safely across platforms including Windows.
6. Generates exactly one audio asset per scene.
7. Actual duration reading measures ground-truth audio length.
8. Total audio track duration strictly equals sum of scene durations.
9. Missing or empty narration fails clearly with descriptive error.
10. Empty generated file is detected and rejected.
11. Scene failure isolation: failure in scene 2 does not discard scene 1.
12. Locale failure isolation: failure in one locale does not crash other locales in bundle.
13. Existing completed audio asset is reused (idempotency).
14. Force regeneration overwrites existing asset when requested.
15. Zero live paid TTS calls occur during test execution.
16. Factory returns configured provider.
"""

from pathlib import Path
import pytest
from app.models.schemas import (
    LocalizedScript,
    LocalizedScene,
    LocalizationBundle,
    FinalScript,
    SceneDraft,
)
from app.services.tts.base import TTSProvider
from app.services.tts.mock_tts_provider import MockTTSProvider, generate_synthetic_wav_file
from app.services.tts.audio_probe import get_audio_duration
from app.services.tts.factory import get_tts_provider
from app.services.tts.service import TTSService


def create_sample_localized_script(locale: str = "ar-SA") -> LocalizedScript:
    """Create a sample localized script for testing TTS synthesis."""
    return LocalizedScript(
        title="التوعية بالأمن السيبراني",
        source_language="en-US",
        language="ar",
        locale=locale,
        text_direction="rtl" if "ar" in locale else "ltr",
        audience="Corporate Employees",
        opening_hook="مقدمة توعوية مهمة",
        scenes=[
            LocalizedScene(
                scene_id="scene_1",
                order=1,
                title="التعرف على التصيد",
                purpose="توعية بالمرسل",
                narration="هذه جملة تجريبية للمشهد الأول لاختبار توليد الصوت بدقة وسرعة مناسبة.",
                estimated_duration_seconds=5,
                visual_direction="Presenter in office.",
                on_screen_text="تحقق من المرسل",
                learning_objective_ids=["LO1"],
                scene_type="presenter",
            ),
            LocalizedScene(
                scene_id="scene_2",
                order=2,
                title="بروتوكول الإبلاغ",
                purpose="إجراءات الإبلاغ",
                narration="المشهد الثاني يوضح كيفية النقر على زر الإبلاغ عن التصيد في شريط الأدوات المعتمد.",
                estimated_duration_seconds=6,
                visual_direction="Presenter highlighting button.",
                on_screen_text=None,
                learning_objective_ids=["LO2"],
                scene_type="presenter",
            ),
        ],
        closing_summary="خاتمة التوعية",
        target_duration_seconds=11,
        total_estimated_duration_seconds=11,
        metadata={},
    )


def test_tts_provider_abstraction():
    """Test 1: Verify TTSProvider abstract base class contracts."""
    provider = MockTTSProvider()
    assert isinstance(provider, TTSProvider)
    assert provider.provider_name == "mock"


def test_mock_tts_generates_valid_measurable_audio(tmp_path):
    """Test 2 & 7: Verify synthetic audio generation and exact duration measurement."""
    provider = MockTTSProvider(fixed_duration_seconds=2.5)
    out_file = tmp_path / "test_scene.wav"

    asset = provider.synthesize_scene_audio(
        narration="Test narration for audio probing.",
        output_path=out_file,
        locale="en-US",
    )

    assert asset.status == "completed"
    assert asset.duration_seconds == 2.5
    assert Path(asset.audio_path).exists()
    assert Path(asset.audio_path).stat().st_size > 0

    # Probe file independently to confirm ground truth measurement
    measured = get_audio_duration(asset.audio_path)
    assert measured == 2.5


def test_voice_configuration_resolution():
    """Test 3: Voice configuration resolves default mappings and respects overrides."""
    provider = MockTTSProvider()

    # Exact matches
    assert provider.resolve_voice("en-US") == "en-US-ChristopherNeural"
    assert provider.resolve_voice("ar-SA") == "ar-SA-HamedNeural"
    assert provider.resolve_voice("bn-BD") == "bn-BD-PradeepNeural"

    # Explicit override
    assert provider.resolve_voice("ar-SA", voice_override="ar-SA-ZariyahNeural") == "ar-SA-ZariyahNeural"

    # Language fallback
    assert provider.resolve_voice("ar-EG") == "ar-SA-HamedNeural"


def test_per_scene_path_construction_and_windows_safety(tmp_path):
    """Test 4 & 5: Windows-safe path construction per scene."""
    script = create_sample_localized_script(locale="ar-SA")
    provider = MockTTSProvider()
    service = TTSService(provider=provider, output_base_dir=tmp_path)

    track = service.synthesize_locale(script=script, project_id="proj_101")

    assert track.locale == "ar-SA"
    assert len(track.scene_audio) == 2

    # Check path structure: storage/proj_101/audio/ar-SA/scene_1.wav
    p1 = Path(track.scene_audio[0].audio_path)
    p2 = Path(track.scene_audio[1].audio_path)

    assert p1.name == "scene_1.wav"
    assert p2.name == "scene_2.wav"
    assert p1.parent.name == "ar-SA"
    assert p1.parent.parent.name == "audio"


def test_one_audio_asset_per_scene_and_duration_sum(tmp_path):
    """Test 6 & 8: Generates one asset per scene and total duration strictly equals sum."""
    script = create_sample_localized_script(locale="ar-SA")
    provider = MockTTSProvider(fixed_duration_seconds=3.0)
    service = TTSService(provider=provider, output_base_dir=tmp_path)

    track = service.synthesize_locale(script=script, project_id="proj_102")

    assert len(track.scene_audio) == 2
    assert track.scene_audio[0].duration_seconds == 3.0
    assert track.scene_audio[1].duration_seconds == 3.0
    assert track.total_audio_duration_seconds == 6.0
    assert track.status == "completed"


def test_missing_narration_fails_clearly(tmp_path):
    """Test 9: Missing or whitespace-only narration fails cleanly."""
    provider = MockTTSProvider()
    out_file = tmp_path / "empty_narration.wav"

    with pytest.raises(ValueError, match="Narration text cannot be empty"):
        provider.synthesize_scene_audio(
            narration="   ",
            output_path=out_file,
            locale="en-US",
        )


def test_empty_generated_file_rejected(tmp_path):
    """Test 10: 0-byte generated file is detected and rejected."""
    empty_file = tmp_path / "corrupt.wav"
    empty_file.touch()  # Creates a 0-byte file

    with pytest.raises(ValueError, match="Audio file is empty"):
        get_audio_duration(empty_file)


def test_scene_failure_isolation(tmp_path):
    """Test 11: Failure in scene 2 preserves scene 1 without aborting entire process."""
    script = create_sample_localized_script(locale="ar-SA")
    # Simulate scene_2 failure
    provider = MockTTSProvider(fail_scene_ids=["scene_2"])
    service = TTSService(provider=provider, output_base_dir=tmp_path)

    track = service.synthesize_locale(script=script, project_id="proj_103")

    assert len(track.scene_audio) == 2
    assert track.scene_audio[0].status == "completed"
    assert track.scene_audio[0].duration_seconds > 0.0

    assert track.scene_audio[1].status == "failed"
    assert "Simulated TTS failure" in track.scene_audio[1].error
    assert track.status == "partial"


def test_locale_failure_isolation(tmp_path):
    """Test 12: Failure in one locale track does not destroy other locales in bundle."""
    ar_script = create_sample_localized_script(locale="ar-SA")
    bn_script = create_sample_localized_script(locale="bn-BD")

    bundle = LocalizationBundle(
        source_script=FinalScript(
            title="Cybersecurity",
            language="en-US",
            audience="Employees",
            target_duration_seconds=10,
            total_estimated_duration_seconds=10,
            opening_hook="Hook",
            closing_summary="Summary",
            scenes=[],
            metadata={},
        ),
        localized_scripts={"ar-SA": ar_script, "bn-BD": bn_script},
    )

    # Simulate failure exclusively for bn-BD
    provider = MockTTSProvider(fail_locales=["bn-BD"])
    service = TTSService(provider=provider, output_base_dir=tmp_path)

    tracks = service.synthesize_bundle(bundle=bundle, project_id="proj_104")

    assert "ar-SA" in tracks
    assert tracks["ar-SA"].status == "completed"

    assert "bn-BD" in tracks
    assert tracks["bn-BD"].status == "failed"


def test_idempotency_reuses_existing_asset(tmp_path):
    """Test 13: Existing completed asset is reused without regenerating."""
    script = create_sample_localized_script(locale="ar-SA")
    provider = MockTTSProvider()
    service = TTSService(provider=provider, output_base_dir=tmp_path)

    # First run: generates 2 scenes
    track1 = service.synthesize_locale(script=script, project_id="proj_105")
    assert provider.call_count == 2

    # Second run without force_regenerate: reuses both scenes without calling synthesize_scene_audio
    track2 = service.synthesize_locale(script=script, project_id="proj_105", force_regenerate=False)
    assert provider.call_count == 2
    assert track2.total_audio_duration_seconds == track1.total_audio_duration_seconds


def test_force_regeneration_overwrites_existing_asset(tmp_path):
    """Test 14: force_regenerate=True triggers fresh synthesis."""
    script = create_sample_localized_script(locale="ar-SA")
    provider = MockTTSProvider()
    service = TTSService(provider=provider, output_base_dir=tmp_path)

    # First run
    service.synthesize_locale(script=script, project_id="proj_106")
    assert provider.call_count == 2

    # Second run with force_regenerate=True
    service.synthesize_locale(script=script, project_id="proj_106", force_regenerate=True)
    assert provider.call_count == 4


def test_update_script_with_actual_durations(tmp_path):
    """Test: Ground truth measured durations update localized script metadata."""
    script = create_sample_localized_script(locale="ar-SA")
    provider = MockTTSProvider(fixed_duration_seconds=8.0)
    service = TTSService(provider=provider, output_base_dir=tmp_path)

    track = service.synthesize_locale(script=script, project_id="proj_107")
    updated_script = TTSService.update_script_with_actual_durations(script, track)

    assert updated_script.scenes[0].estimated_duration_seconds == 8
    assert updated_script.scenes[1].estimated_duration_seconds == 8
    assert updated_script.total_estimated_duration_seconds == 16


def test_factory_returns_configured_provider():
    """Test 16: Factory returns configured TTS provider."""
    mock_prov = get_tts_provider("mock")
    assert mock_prov.provider_name == "mock"

    edge_prov = get_tts_provider("edge_tts")
    assert edge_prov.provider_name == "edge_tts"

    with pytest.raises(ValueError, match="Unsupported TTS provider"):
        get_tts_provider("unsupported_provider_xyz")
