"""Unit tests for SadTalkerProvider (Free Local Avatar Generation).

All tests execute with mocked subprocesses to ensure pytest is fast,
safe, and does not require local GPU inference or large model weights.
"""

import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest

from app.core.config import settings
from app.models.schemas import LocalizedScript, LocalizedScene, LocalizedAudioTrack, SceneAudioAsset
from app.services.avatar.factory import get_avatar_provider
from app.services.avatar.sadtalker_provider import (
    SadTalkerProvider,
    SadTalkerConfigurationError,
    SadTalkerInferenceError,
)
from app.services.avatar.service import AvatarService


@pytest.fixture
def dummy_source_image(tmp_path):
    img = tmp_path / "test_portrait.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 1024)
    return img


@pytest.fixture
def dummy_audio_file(tmp_path):
    audio = tmp_path / "test_audio.mp3"
    audio.write_bytes(b"ID3" + b"\x00" * 2048)
    return audio


def test_sadtalker_provider_construction_and_defaults():
    """Test 1: Provider instantiates with configured settings and proper provider_name."""
    provider = SadTalkerProvider()
    assert provider.provider_name == "sadtalker"
    assert provider.size == settings.SADTALKER_SIZE
    assert provider.still_mode == settings.SADTALKER_STILL
    assert provider.preprocess == settings.SADTALKER_PREPROCESS


def test_sadtalker_factory_selection():
    """Test 2: Factory get_avatar_provider('sadtalker') returns SadTalkerProvider."""
    provider = get_avatar_provider("sadtalker")
    assert isinstance(provider, SadTalkerProvider)
    assert provider.provider_name == "sadtalker"


def test_sadtalker_readiness_check(tmp_path, dummy_source_image):
    """Test 3: Readiness check accurately inspects local prerequisites without running inference."""
    fake_python = tmp_path / "python.exe"
    fake_python.write_text("fake")
    fake_root = tmp_path / "sadtalker"
    fake_root.mkdir()
    (fake_root / "inference.py").write_text("print('test')")
    fake_checkpoints = fake_root / "checkpoints"
    fake_checkpoints.mkdir()
    (fake_checkpoints / "SadTalker_V0.0.2_256.safetensors").write_text("model")

    provider = SadTalkerProvider(
        python_path=fake_python,
        sadtalker_root=fake_root,
        checkpoint_dir=fake_checkpoints,
        default_source_image=dummy_source_image,
    )

    readiness = provider.check_readiness()
    assert isinstance(readiness, dict)
    assert "ready" in readiness
    assert readiness["python_exists"] is True
    assert readiness["root_exists"] is True
    assert readiness["checkpoints_ok"] is True
    assert readiness["source_image_ok"] is True


def test_sadtalker_source_image_resolution(tmp_path, dummy_source_image):
    """Test 4: Source portrait image resolution handles custom or default image."""
    provider = SadTalkerProvider(default_source_image=dummy_source_image)
    resolved = provider.resolve_source_image()
    assert resolved == dummy_source_image.resolve()

    # Explicit avatar_id pointing to another file
    custom_img = tmp_path / "custom.png"
    custom_img.write_bytes(b"PNGDATA")
    resolved_custom = provider.resolve_source_image(str(custom_img))
    assert resolved_custom == custom_img.resolve()


def test_sadtalker_missing_source_image_raises_configuration_error(tmp_path):
    """Test 5: Missing source portrait raises SadTalkerConfigurationError."""
    non_existent = tmp_path / "does_not_exist.png"
    provider = SadTalkerProvider(default_source_image=non_existent)

    with pytest.raises(SadTalkerConfigurationError, match="SadTalker source portrait image not found"):
        provider.resolve_source_image()


def test_sadtalker_missing_audio_raises_error(dummy_source_image, tmp_path):
    """Test 6: Missing audio file raises SadTalkerConfigurationError."""
    provider = SadTalkerProvider(default_source_image=dummy_source_image)
    missing_audio = tmp_path / "missing.mp3"

    with pytest.raises(SadTalkerConfigurationError, match="Audio file missing"):
        provider.submit_avatar_job(
            scene_id="scene_1",
            locale="ar-SA",
            audio_path=missing_audio,
        )


def test_sadtalker_command_generation_safe_args(dummy_source_image, dummy_audio_file, tmp_path):
    """Test 7: Command generation uses safe list of arguments without shell string concatenation."""
    provider = SadTalkerProvider(
        default_source_image=dummy_source_image,
        size=256,
        still_mode=True,
    )
    result_dir = tmp_path / "results"
    cmd = provider.build_inference_command(
        audio_path=dummy_audio_file,
        source_image=dummy_source_image,
        result_dir=result_dir,
    )

    assert isinstance(cmd, list)
    assert "--driven_audio" in cmd
    assert str(dummy_audio_file) in cmd
    assert "--source_image" in cmd
    assert str(dummy_source_image) in cmd
    assert "--still" in cmd
    assert "--size" in cmd
    assert "256" in cmd
    assert "--batch_size" in cmd


def test_sadtalker_subprocess_inference_mocked_success(dummy_source_image, dummy_audio_file, tmp_path):
    """Test 8: Successful inference parses output MP4 and returns domain model."""
    provider = SadTalkerProvider(default_source_image=dummy_source_image)

    dest_mp4 = tmp_path / "final_scene_1.mp4"

    def mock_run(cmd, **kwargs):
        if "--result_dir" in cmd:
            res_idx = cmd.index("--result_dir") + 1
            res_dir = Path(cmd[res_idx])
            res_dir.mkdir(parents=True, exist_ok=True)
            # Create simulated generated MP4
            fake_mp4 = res_dir / "2026_10_07_output.mp4"
            fake_mp4.write_bytes(b"MOCK_MP4_HEADER_DATA" + b"\x00" * 4096)
            mock_res = MagicMock()
            mock_res.returncode = 0
            mock_res.stdout = "Inference completed successfully"
            mock_res.stderr = ""
            return mock_res
        mock_res = MagicMock()
        mock_res.returncode = 0
        mock_res.stdout = '{"format": {"duration": "8.35"}, "streams": [{"codec_type": "video", "width": 1024, "height": 1024, "codec_name": "h264"}]}'
        mock_res.stderr = ""
        return mock_res

    with patch("subprocess.run", side_effect=mock_run):
        with patch("app.services.avatar.base.get_audio_duration", return_value=8.35):
            asset = provider.generate_scene_avatar(
                scene_id="scene_1",
                locale="ar-SA",
                audio_path=dummy_audio_file,
                destination_path=dest_mp4,
            )

    assert dest_mp4.exists()
    assert dest_mp4.stat().st_size > 0
    assert asset.status == "completed"
    assert asset.provider == "sadtalker"
    assert asset.duration_seconds == 8.35
    assert asset.video_path == str(dest_mp4.resolve())


def test_sadtalker_subprocess_failure_raises_inference_error(dummy_source_image, dummy_audio_file, tmp_path):
    """Test 9: Subprocess exit code != 0 raises SadTalkerInferenceError with captured stderr."""
    provider = SadTalkerProvider(default_source_image=dummy_source_image)

    def mock_failed_run(cmd, **kwargs):
        mock_res = MagicMock()
        mock_res.returncode = 1
        mock_res.stdout = ""
        mock_res.stderr = "CUDA Out of Memory: failed allocating tensor"
        return mock_res

    with patch("subprocess.run", side_effect=mock_failed_run):
        with pytest.raises(SadTalkerInferenceError, match="CUDA Out of Memory"):
            provider.submit_avatar_job(
                scene_id="scene_1",
                locale="ar-SA",
                audio_path=dummy_audio_file,
            )


def test_sadtalker_timeout_enforced(dummy_source_image, dummy_audio_file):
    """Test 10: Subprocess timeout raises TimeoutError."""
    provider = SadTalkerProvider(default_source_image=dummy_source_image, timeout_seconds=10)

    def mock_timeout_run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=10)

    with patch("subprocess.run", side_effect=mock_timeout_run):
        with pytest.raises(TimeoutError, match="SadTalker inference timed out after 10 seconds"):
            provider.submit_avatar_job(
                scene_id="scene_1",
                locale="ar-SA",
                audio_path=dummy_audio_file,
            )


def test_sadtalker_avatar_service_integration(dummy_source_image, dummy_audio_file, tmp_path):
    """Test 11: AvatarService orchestrates SadTalkerProvider across scenes with failure isolation."""
    provider = SadTalkerProvider(default_source_image=dummy_source_image)
    service = AvatarService(provider=provider, output_base_dir=tmp_path)

    script = LocalizedScript(
        title="عنوان",
        source_language="en-US",
        language="ar",
        locale="ar-SA",
        text_direction="rtl",
        audience="General",
        opening_hook="Hook",
        closing_summary="Summary",
        target_duration_seconds=10,
        scenes=[
            LocalizedScene(scene_id="s1", order=1, title="Intro", narration="مرحبا", visual_description="Intro", scene_type="presenter"),
            LocalizedScene(scene_id="s2", order=2, title="Diagram", narration="الشرح", visual_description="Diagram", scene_type="visual_demo"),
        ],
    )
    audio_track = LocalizedAudioTrack(
        locale="ar-SA",
        scene_audio=[
            SceneAudioAsset(scene_id="s1", locale="ar-SA", provider="edge_tts", voice_id="ar-SA-HamedNeural", audio_path=str(dummy_audio_file), duration_seconds=5.0, status="completed"),
            SceneAudioAsset(scene_id="s2", locale="ar-SA", provider="edge_tts", voice_id="ar-SA-HamedNeural", audio_path=str(dummy_audio_file), duration_seconds=5.0, status="completed"),
        ],
    )

    def mock_run(cmd, **kwargs):
        res_idx = cmd.index("--result_dir") + 1
        res_dir = Path(cmd[res_idx])
        res_dir.mkdir(parents=True, exist_ok=True)
        (res_dir / "out.mp4").write_bytes(b"MOCK_VIDEO_DATA")
        m = MagicMock()
        m.returncode = 0
        return m

    with patch("subprocess.run", side_effect=mock_run):
        with patch("app.services.avatar.base.get_audio_duration", return_value=5.0):
            track = service.generate_locale_avatars(script=script, audio_track=audio_track, project_id="proj_sadtalker_test")

    assert track.locale == "ar-SA"
    # s1 presenter rendered
    assert track.scene_avatars[0].status == "completed"
    assert track.scene_avatars[0].provider == "sadtalker"
    # s2 visual_demo skipped as ineligible
    assert track.scene_avatars[1].status == "skipped"
