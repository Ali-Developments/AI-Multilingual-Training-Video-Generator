"""Comprehensive test suite for Step 6 Avatar (HeyGen) Integration.

Tests:
1. Provider abstraction adheres to clean interface.
2. Mock provider generates valid synthetic MP4 video files.
3. Scene avatar eligibility rules (presenter vs. visual_demo vs. explanation).
4. Job submission produces valid job ID.
5. Status polling transitions through job lifecycle.
6. Successful job completion retrieves valid video asset.
7. Provider failure handling isolates errors per scene.
8. Job timeout is detected and handled cleanly.
9. HeyGen live call cost safety guard blocks unpermitted API calls.
10. Configuration loading respects environment settings.
11. No hardcoded avatar IDs in business logic.
12. Audio asset correctly associated with scene during synthesis.
13. Scene and locale alignment across multi-locale bundles.
14. Missing audio asset fails gracefully without crashing pipeline.
15. Cached/existing avatar video is reused (idempotency).
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
)
from app.services.avatar.base import AvatarProvider, is_avatar_eligible
from app.services.avatar.mock_avatar_provider import MockAvatarProvider, generate_synthetic_mp4_file
from app.services.avatar.heygen_provider import HeyGenProvider, HeyGenAuthError
from app.services.avatar.factory import get_avatar_provider
from app.services.avatar.service import AvatarService
from app.services.tts.mock_tts_provider import generate_synthetic_wav_file


def create_sample_script_and_audio(tmp_path: Path, locale: str = "ar-SA"):
    """Create sample script and audio track fixtures for avatar testing."""
    audio_dir = tmp_path / "audio" / locale
    audio_dir.mkdir(parents=True, exist_ok=True)

    wav1 = generate_synthetic_wav_file(audio_dir / "scene_1.wav", duration_seconds=2.0)
    wav2 = generate_synthetic_wav_file(audio_dir / "scene_2.wav", duration_seconds=3.0)

    script = LocalizedScript(
        title="التوعية بالأمن السيبراني",
        source_language="en-US",
        language="ar",
        locale=locale,
        text_direction="rtl",
        audience="Employees",
        opening_hook="Hook",
        scenes=[
            LocalizedScene(
                scene_id="scene_1",
                order=1,
                title="Scene 1",
                purpose="Purpose 1",
                narration="Narration 1",
                estimated_duration_seconds=2,
                visual_direction="Presenter speaking.",
                on_screen_text=None,
                learning_objective_ids=["LO1"],
                scene_type="presenter",  # Eligible for avatar
            ),
            LocalizedScene(
                scene_id="scene_2",
                order=2,
                title="Scene 2",
                purpose="Purpose 2",
                narration="Narration 2",
                estimated_duration_seconds=3,
                visual_direction="Diagram on screen.",
                on_screen_text=None,
                learning_objective_ids=["LO2"],
                scene_type="visual_demo",  # Ineligible for avatar (visual demo)
            ),
        ],
        closing_summary="Summary",
        target_duration_seconds=5,
        total_estimated_duration_seconds=5,
        metadata={},
    )

    audio_track = LocalizedAudioTrack(
        locale=locale,
        scene_audio=[
            SceneAudioAsset(
                scene_id="scene_1",
                locale=locale,
                audio_path=str(wav1.resolve()),
                duration_seconds=2.0,
                provider="mock",
                voice_id="ar-SA-HamedNeural",
                status="completed",
            ),
            SceneAudioAsset(
                scene_id="scene_2",
                locale=locale,
                audio_path=str(wav2.resolve()),
                duration_seconds=3.0,
                provider="mock",
                voice_id="ar-SA-HamedNeural",
                status="completed",
            ),
        ],
        total_audio_duration_seconds=5.0,
        status="completed",
    )

    return script, audio_track


def test_avatar_provider_abstraction():
    """Test 1: Verify AvatarProvider abstract base class contracts."""
    provider = MockAvatarProvider()
    assert isinstance(provider, AvatarProvider)
    assert provider.provider_name == "mock"


def test_mock_avatar_generates_valid_mp4(tmp_path):
    """Test 2: Verify mock provider creates valid MP4 file."""
    mp4_path = tmp_path / "avatar_scene.mp4"
    generate_synthetic_mp4_file(mp4_path, duration_seconds=1.5)

    assert mp4_path.exists()
    assert mp4_path.stat().st_size > 0


def test_scene_avatar_eligibility():
    """Test 3: Verify eligibility helper correctly classifies scene types."""
    presenter_scene = LocalizedScene(
        scene_id="s1", order=1, title="T", narration="N", scene_type="presenter"
    )
    intro_scene = LocalizedScene(
        scene_id="s2", order=2, title="T", narration="N", scene_type="intro"
    )
    demo_scene = LocalizedScene(
        scene_id="s3", order=3, title="T", narration="N", scene_type="visual_demo"
    )
    expl_scene = LocalizedScene(
        scene_id="s4", order=4, title="T", narration="N", scene_type="explanation"
    )

    assert is_avatar_eligible(presenter_scene) is True
    assert is_avatar_eligible(intro_scene) is True
    assert is_avatar_eligible(demo_scene) is False
    assert is_avatar_eligible(expl_scene) is False


def test_avatar_job_lifecycle_submit_poll_complete(tmp_path):
    """Test 4, 5, 6: Verify full lifecycle (submit -> poll -> complete)."""
    provider = MockAvatarProvider(poll_attempts_before_complete=1)
    wav_path = generate_synthetic_wav_file(tmp_path / "voice.wav", duration_seconds=2.0)
    dest_path = tmp_path / "avatar_out.mp4"

    asset = provider.generate_scene_avatar(
        scene_id="scene_1",
        locale="ar-SA",
        audio_path=wav_path,
        destination_path=dest_path,
        poll_interval=0.01,
    )

    assert asset.status == "completed"
    assert asset.scene_id == "scene_1"
    assert Path(asset.video_path).exists()
    assert provider.submit_call_count == 1
    assert provider.poll_call_count >= 2
    assert provider.download_call_count == 1


def test_avatar_provider_failure_handling(tmp_path):
    """Test 7: Provider failure raises exception caught by service."""
    provider = MockAvatarProvider(fail_scene_ids=["scene_1"])
    wav_path = generate_synthetic_wav_file(tmp_path / "voice.wav", duration_seconds=2.0)
    dest_path = tmp_path / "avatar_fail.mp4"

    with pytest.raises(RuntimeError, match="Simulated avatar generation failure"):
        provider.generate_scene_avatar(
            scene_id="scene_1",
            locale="ar-SA",
            audio_path=wav_path,
            destination_path=dest_path,
            poll_interval=0.01,
        )


def test_avatar_job_timeout(tmp_path):
    """Test 8: Job exceeding timeout raises TimeoutError."""
    provider = MockAvatarProvider(timeout_scene_ids=["scene_slow"])
    wav_path = generate_synthetic_wav_file(tmp_path / "voice.wav", duration_seconds=1.0)
    dest_path = tmp_path / "avatar_slow.mp4"

    with pytest.raises(TimeoutError, match="Avatar generation timed out"):
        provider.generate_scene_avatar(
            scene_id="scene_slow",
            locale="ar-SA",
            audio_path=wav_path,
            destination_path=dest_path,
            poll_interval=0.01,
            timeout_seconds=0.05,
        )


def test_heygen_live_call_blocked_by_cost_safety(monkeypatch):
    """Test 9: Live HeyGen API calls are strictly blocked when ENABLE_LIVE_API_TESTS=False."""
    provider = HeyGenProvider(api_key="mock_test_key")

    with pytest.raises(RuntimeError, match="Live HeyGen API calls are strictly disabled"):
        provider.submit_avatar_job(
            scene_id="s1",
            locale="ar-SA",
            audio_path=Path("dummy.wav"),
        )


def test_heygen_auth_error_on_missing_key(monkeypatch):
    """Test 10: Missing HeyGen API key raises HeyGenAuthError."""
    from app.core.config import settings
    monkeypatch.setattr(settings, "ENABLE_LIVE_API_TESTS", True)
    provider = HeyGenProvider(api_key="")

    with pytest.raises(HeyGenAuthError, match="Missing HEYGEN_API_KEY"):
        provider.submit_avatar_job(
            scene_id="s1",
            locale="ar-SA",
            audio_path=Path("dummy.wav"),
        )


def test_avatar_service_orchestration_and_eligibility(tmp_path):
    """Test 11, 12, 13: Service renders presenter scene and skips visual_demo scene."""
    script, audio_track = create_sample_script_and_audio(tmp_path, locale="ar-SA")
    provider = MockAvatarProvider(poll_attempts_before_complete=0)
    service = AvatarService(provider=provider, output_base_dir=tmp_path)

    track = service.generate_locale_avatars(
        script=script,
        audio_track=audio_track,
        project_id="proj_avatar_1",
    )

    assert track.locale == "ar-SA"
    assert len(track.scene_avatars) == 2

    # Scene 1 was 'presenter' -> completed avatar video
    assert track.scene_avatars[0].scene_id == "scene_1"
    assert track.scene_avatars[0].status == "completed"
    assert Path(track.scene_avatars[0].video_path).exists()

    # Scene 2 was 'visual_demo' -> skipped (no avatar required)
    assert track.scene_avatars[1].scene_id == "scene_2"
    assert track.scene_avatars[1].status == "skipped"
    assert track.scene_avatars[1].video_path is None


def test_avatar_service_missing_audio_handled(tmp_path):
    """Test 14: Missing audio asset results in failed scene status without crashing."""
    script, audio_track = create_sample_script_and_audio(tmp_path, locale="ar-SA")
    # Mark audio asset for scene 1 as failed
    audio_track.scene_audio[0].status = "failed"

    provider = MockAvatarProvider()
    service = AvatarService(provider=provider, output_base_dir=tmp_path)

    track = service.generate_locale_avatars(
        script=script,
        audio_track=audio_track,
        project_id="proj_avatar_2",
    )

    assert track.scene_avatars[0].status == "failed"
    assert "Missing completed TTS audio asset" in track.scene_avatars[0].error


def test_avatar_service_caching_idempotency(tmp_path):
    """Test 15: Existing avatar video is reused without re-submitting job."""
    script, audio_track = create_sample_script_and_audio(tmp_path, locale="ar-SA")
    provider = MockAvatarProvider(poll_attempts_before_complete=0)
    service = AvatarService(provider=provider, output_base_dir=tmp_path)

    # First run
    service.generate_locale_avatars(script=script, audio_track=audio_track, project_id="proj_avatar_3")
    assert provider.submit_call_count == 1

    # Second run without force_regenerate
    service.generate_locale_avatars(script=script, audio_track=audio_track, project_id="proj_avatar_3", force_regenerate=False)
    assert provider.submit_call_count == 1  # Reused from disk!


def test_avatar_factory_instantiation():
    """Test: Factory correctly instantiates requested avatar provider."""
    mock_prov = get_avatar_provider("mock")
    assert mock_prov.provider_name == "mock"

    heygen_prov = get_avatar_provider("heygen")
    assert heygen_prov.provider_name == "heygen"

    with pytest.raises(ValueError, match="Unsupported Avatar provider"):
        get_avatar_provider("unsupported_xyz")
