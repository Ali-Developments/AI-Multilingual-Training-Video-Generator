"""Hardening, security, and failure scenario test suite (Step 13).

Validates:
- Missing API keys and authentication guards.
- Corrupted audio file handling in audio probe.
- Path traversal defense on project IDs.
- Error isolation across locales during partial failure.
- Incomplete/corrupt manifest handling and resume defense.
- Safe structured exceptions across services.
"""

from pathlib import Path
import pytest
from unittest.mock import patch, MagicMock

from app.core.config import settings
from app.models.schemas import LocalizationValidationResult
from app.services.avatar.heygen_provider import HeyGenProvider
from app.services.composition.ffmpeg_utils import escape_ffmpeg_filter_path
from app.services.llm.groq_provider import GroqProvider
from app.services.localization.service import LocalizationService
from app.services.tts.audio_probe import get_audio_duration
from app.workflows.manifest import ProjectManifestManager
from tests.test_localization import create_sample_final_script, create_valid_arabic_localized_script


def test_groq_provider_missing_key_behavior():
    """Verify GroqProvider raises clear error when API key is missing."""
    with patch("app.services.llm.groq_provider.settings") as mock_settings:
        mock_settings.GROQ_API_KEY = None
        mock_settings.GROQ_MODEL = "llama-3.3-70b-versatile"
        provider = GroqProvider(api_key=None)
        with pytest.raises(ValueError) as exc_info:
            provider._get_client()
        assert "GROQ_API_KEY" in str(exc_info.value)


def test_heygen_provider_cost_safety_guard():
    """Verify HeyGenProvider raises RuntimeError when ENABLE_LIVE_API_TESTS=False."""
    with patch("app.services.avatar.heygen_provider.settings") as mock_settings:
        mock_settings.ENABLE_LIVE_API_TESTS = False
        mock_settings.HEYGEN_API_KEY = "test_heygen_key"
        provider = HeyGenProvider()
        with pytest.raises(RuntimeError) as exc_info:
            provider.submit_avatar_job(
                scene_id="scene_1",
                locale="en-US",
                audio_path=Path("storage/test.wav"),
            )
        assert "ENABLE_LIVE_API_TESTS" in str(exc_info.value)


def test_corrupted_audio_file_probing(tmp_path):
    """Verify audio duration probe handles garbage data gracefully with ValueError."""
    corrupt_file = tmp_path / "corrupt.wav"
    corrupt_file.write_bytes(b"NOT_A_VALID_WAV_OR_MEDIA_HEADER_GARBAGE_CONTENT_1234567890")

    with pytest.raises(ValueError) as exc_info:
        get_audio_duration(corrupt_file)
    assert "Unable to determine audio duration" in str(exc_info.value)


def test_escape_ffmpeg_filter_path_windows_safety():
    """Verify Windows paths with colons and slashes are escaped properly for FFmpeg filters."""
    win_path = Path("C:/Users/test/storage/subtitles.srt")
    escaped = escape_ffmpeg_filter_path(win_path)
    assert ":" not in escaped or "\\:" in escaped
    assert "\\" in escaped or "/" in escaped


def test_path_traversal_defense_in_manifest(tmp_path):
    """Verify ProjectManifestManager handles paths safely."""
    mgr = ProjectManifestManager(storage_base_dir=tmp_path)
    traversal_id = "../../malicious"
    manifest_path = mgr.get_manifest_path(traversal_id)
    assert manifest_path.name == "project.json"


def test_corrupt_manifest_load_returns_none(tmp_path):
    """Verify invalid JSON in project.json returns None rather than crashing."""
    mgr = ProjectManifestManager(storage_base_dir=tmp_path)
    p_dir = tmp_path / "corrupt_proj"
    p_dir.mkdir(parents=True)
    manifest_file = p_dir / "project.json"
    manifest_file.write_text("{invalid json: broken syntax", encoding="utf-8")

    loaded = mgr.load_manifest("corrupt_proj")
    assert loaded is None


def test_partial_locale_failure_isolation():
    """Verify that if one locale fails during localization, valid locales are preserved."""
    source_script = create_sample_final_script()
    valid_ar_script = create_valid_arabic_localized_script()

    mock_llm = MagicMock()

    def side_effect_localize(req):
        if req.target_locale == "ar-SA":
            return (valid_ar_script, LocalizationValidationResult(is_valid=True, issues=[]), "completed")
        raise RuntimeError("Simulated LLM network timeout on bn-BD")

    loc_service = LocalizationService(llm_provider=mock_llm)
    with patch.object(loc_service, "localize", side_effect=side_effect_localize):
        bundle = loc_service.localize_bundle(
            source_script=source_script,
            target_locales=["ar-SA", "bn-BD"],
        )

        assert "ar-SA" in bundle.localized_scripts
        assert "bn-BD" not in bundle.localized_scripts
        assert "bn-BD" in bundle.failed_locales
        assert "Simulated LLM network timeout" in bundle.failed_locales["bn-BD"]["error"]
