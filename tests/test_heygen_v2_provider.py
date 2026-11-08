"""Comprehensive Isolated Unit Test Suite for Production-Ready HeyGen Avatar Integration (Phase 1).

Strict Safety Policy:
- All tests are fully mocked.
- Zero live paid API calls are permitted.
- Verifies official HeyGen v2/v1 endpoints, audio-driven & script-driven modes,
  rate limits, auth errors, payment required errors, webhook payloads,
  ffprobe validation, and safe idempotency preventing duplicate billing.
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
import requests

from app.core.config import settings
from app.services.avatar.base import AvatarProvider
from app.services.avatar.heygen_provider import (
    HeyGenProvider,
    HeyGenAPIError,
    HeyGenAuthError,
    HeyGenRateLimitError,
    HeyGenPaymentRequiredError,
)
from app.services.avatar.mock_avatar_provider import MockAvatarProvider
from app.services.avatar.sadtalker_provider import SadTalkerProvider
from app.services.avatar.factory import get_avatar_provider


# ---------------------------------------------------------------------------
# 1. Safety Gates & Authentication
# ---------------------------------------------------------------------------

def test_heygen_safety_gate_blocks_live_calls_by_default(monkeypatch):
    """Test 1: HeyGenProvider blocks API execution when ENABLE_LIVE_HEYGEN=False."""
    monkeypatch.setattr(settings, "ENABLE_LIVE_HEYGEN", False)
    provider = HeyGenProvider(api_key="mock_test_key")

    with pytest.raises(RuntimeError, match="ENABLE_LIVE_HEYGEN=False"):
        provider.submit_avatar_job(scene_id="s1", locale="en-US", audio_path=Path("dummy.mp3"))

    with pytest.raises(RuntimeError, match="ENABLE_LIVE_HEYGEN=False"):
        provider.poll_avatar_job("job_123")

    with pytest.raises(RuntimeError, match="ENABLE_LIVE_HEYGEN=False"):
        provider.download_avatar_video("https://heygen.cdn/vid.mp4", Path("out.mp4"))


def test_heygen_safety_gate_blocks_in_test_environment_without_test_flag(monkeypatch):
    """Test 2: When in test suite, ENABLE_LIVE_API_TESTS must be True even if ENABLE_LIVE_HEYGEN=True."""
    monkeypatch.setattr(settings, "ENABLE_LIVE_HEYGEN", True)
    monkeypatch.setattr(settings, "ENABLE_LIVE_API_TESTS", False)
    provider = HeyGenProvider(api_key="mock_test_key")

    with pytest.raises(RuntimeError, match="ENABLE_LIVE_API_TESTS=False"):
        provider.submit_avatar_job(scene_id="s1", locale="en-US", audio_path=Path("dummy.mp3"))


def test_heygen_auth_error_on_missing_key(monkeypatch):
    """Test 3: Missing or whitespace API key raises HeyGenAuthError."""
    monkeypatch.setattr(settings, "ENABLE_LIVE_HEYGEN", True)
    monkeypatch.setattr(settings, "ENABLE_LIVE_API_TESTS", True)

    provider = HeyGenProvider(api_key="")
    with pytest.raises(HeyGenAuthError, match="Missing HEYGEN_API_KEY"):
        provider._get_headers()


def test_heygen_auth_error_on_401_or_403(monkeypatch, tmp_path):
    """Test 4: HTTP 401 or 403 from HeyGen raises HeyGenAuthError."""
    monkeypatch.setattr(settings, "ENABLE_LIVE_HEYGEN", True)
    monkeypatch.setattr(settings, "ENABLE_LIVE_API_TESTS", True)

    audio_file = tmp_path / "test.mp3"
    audio_file.write_bytes(b"dummy audio data")
    asset_cache = tmp_path / "test.asset_url"
    asset_cache.write_text("https://heygen.cdn/audio.mp3")

    mock_resp = MagicMock(spec=requests.Response)
    mock_resp.status_code = 401
    mock_resp.text = '{"error": "Unauthorized: Invalid API key"}'

    mock_session = MagicMock(spec=requests.Session)
    mock_session.post.return_value = mock_resp

    provider = HeyGenProvider(api_key="invalid_key", session=mock_session)
    with pytest.raises(HeyGenAuthError, match="authentication error"):
        provider.submit_avatar_job(scene_id="scene_1", locale="en-US", audio_path=audio_file)


# ---------------------------------------------------------------------------
# 2. Payment & Credit Enforcement
# ---------------------------------------------------------------------------

def test_heygen_payment_required_on_402(monkeypatch, tmp_path):
    """Test 5: HTTP 402 raises HeyGenPaymentRequiredError for insufficient account balance."""
    monkeypatch.setattr(settings, "ENABLE_LIVE_HEYGEN", True)
    monkeypatch.setattr(settings, "ENABLE_LIVE_API_TESTS", True)

    audio_file = tmp_path / "test.mp3"
    audio_file.write_bytes(b"dummy audio")
    (tmp_path / "test.asset_url").write_text("https://heygen.cdn/audio.mp3")

    mock_resp = MagicMock(spec=requests.Response)
    mock_resp.status_code = 402
    mock_resp.text = '{"code": 402, "message": "Insufficient credits remaining"}'

    mock_session = MagicMock(spec=requests.Session)
    mock_session.post.return_value = mock_resp

    provider = HeyGenProvider(api_key="valid_key", session=mock_session)
    with pytest.raises(HeyGenPaymentRequiredError, match="insufficient account balance or credits"):
        provider.submit_avatar_job(scene_id="scene_1", locale="en-US", audio_path=audio_file)


# ---------------------------------------------------------------------------
# 3. Rate Limit & Retries
# ---------------------------------------------------------------------------

def test_heygen_rate_limit_429_retries_and_succeeds(monkeypatch, tmp_path):
    """Test 6: HTTP 429 applies exponential backoff retry and succeeds when subsequent attempt returns 200."""
    monkeypatch.setattr(settings, "ENABLE_LIVE_HEYGEN", True)
    monkeypatch.setattr(settings, "ENABLE_LIVE_API_TESTS", True)

    audio_file = tmp_path / "test.mp3"
    audio_file.write_bytes(b"dummy audio")
    (tmp_path / "test.asset_url").write_text("https://heygen.cdn/audio.mp3")

    resp_429 = MagicMock(spec=requests.Response)
    resp_429.status_code = 429
    resp_429.text = '{"message": "Too Many Requests"}'

    resp_200 = MagicMock(spec=requests.Response)
    resp_200.status_code = 200
    resp_200.json.return_value = {"code": 100, "data": {"video_id": "v_success_123"}}

    mock_session = MagicMock(spec=requests.Session)
    mock_session.post.side_effect = [resp_429, resp_200]

    with patch("time.sleep") as mock_sleep:
        provider = HeyGenProvider(api_key="valid_key", max_retries=3, session=mock_session)
        video_id = provider.submit_avatar_job(scene_id="s1", locale="en-US", audio_path=audio_file)

        assert video_id == "v_success_123"
        assert mock_session.post.call_count == 2
        mock_sleep.assert_called_once()


def test_heygen_rate_limit_exhausted_raises_error(monkeypatch, tmp_path):
    """Test 7: Repeated 429 exhausting max retries raises HeyGenRateLimitError."""
    monkeypatch.setattr(settings, "ENABLE_LIVE_HEYGEN", True)
    monkeypatch.setattr(settings, "ENABLE_LIVE_API_TESTS", True)

    audio_file = tmp_path / "test.mp3"
    audio_file.write_bytes(b"dummy audio")
    (tmp_path / "test.asset_url").write_text("https://heygen.cdn/audio.mp3")

    resp_429 = MagicMock(spec=requests.Response)
    resp_429.status_code = 429
    resp_429.text = "Rate limit"

    mock_session = MagicMock(spec=requests.Session)
    mock_session.post.return_value = resp_429

    with patch("time.sleep"):
        provider = HeyGenProvider(api_key="valid_key", max_retries=2, session=mock_session)
        with pytest.raises(HeyGenRateLimitError, match="rate limit exceeded"):
            provider.submit_avatar_job(scene_id="s1", locale="en-US", audio_path=audio_file)


# ---------------------------------------------------------------------------
# 4. Job Submission Modes (Audio-Driven vs Script-Driven)
# ---------------------------------------------------------------------------

def test_heygen_successful_job_submission_audio_mode(monkeypatch, tmp_path):
    """Test 8: Audio-driven mode uploads audio or uses cache and constructs correct v2 payload."""
    monkeypatch.setattr(settings, "ENABLE_LIVE_HEYGEN", True)
    monkeypatch.setattr(settings, "ENABLE_LIVE_API_TESTS", True)

    audio_file = tmp_path / "test.mp3"
    audio_file.write_bytes(b"dummy audio content")

    # Mock audio asset upload
    resp_upload = MagicMock(spec=requests.Response)
    resp_upload.status_code = 200
    resp_upload.json.return_value = {"code": 100, "data": {"url": "https://heygen.cdn/uploaded_audio.mp3"}}

    # Mock video generation
    resp_gen = MagicMock(spec=requests.Response)
    resp_gen.status_code = 200
    resp_gen.json.return_value = {"code": 100, "data": {"video_id": "v_heygen_abc456"}}

    mock_session = MagicMock(spec=requests.Session)
    mock_session.post.side_effect = [resp_upload, resp_gen]

    provider = HeyGenProvider(api_key="valid_key", session=mock_session)
    job_id = provider.submit_avatar_job(
        scene_id="scene_1",
        locale="en-US",
        audio_path=audio_file,
        avatar_id="avatar_jennifer_suit",
        mode="audio",
    )

    assert job_id == "v_heygen_abc456"
    assert mock_session.post.call_count == 2

    # Verify generate payload
    gen_call_args = mock_session.post.call_args_list[1]
    assert gen_call_args[0][0] == "https://api.heygen.com/v2/video/generate"
    payload = gen_call_args[1]["json"]
    assert payload["video_inputs"][0]["character"]["avatar_id"] == "avatar_jennifer_suit"
    assert payload["video_inputs"][0]["voice"]["type"] == "audio"
    assert payload["video_inputs"][0]["voice"]["audio_url"] == "https://heygen.cdn/uploaded_audio.mp3"
    assert payload["dimension"] == {"width": 1920, "height": 1080}

    # Verify cached asset url file was written
    cache_file = tmp_path / "test.asset_url"
    assert cache_file.exists()
    assert cache_file.read_text().strip() == "https://heygen.cdn/uploaded_audio.mp3"


def test_heygen_successful_job_submission_script_mode(monkeypatch, tmp_path):
    """Test 9: Script-driven mode passes text and voice_id without requiring audio upload."""
    monkeypatch.setattr(settings, "ENABLE_LIVE_HEYGEN", True)
    monkeypatch.setattr(settings, "ENABLE_LIVE_API_TESTS", True)

    resp_gen = MagicMock(spec=requests.Response)
    resp_gen.status_code = 200
    resp_gen.json.return_value = {"code": 100, "data": {"video_id": "v_script_xyz789"}}

    mock_session = MagicMock(spec=requests.Session)
    mock_session.post.return_value = resp_gen

    provider = HeyGenProvider(api_key="valid_key", session=mock_session)
    job_id = provider.submit_avatar_job(
        scene_id="scene_2",
        locale="es-ES",
        audio_path=None,
        avatar_id="avatar_brody_suit",
        script_text="Bienvenido a la capacitación en ciberseguridad.",
        voice_id="voice_es_alvaro",
        mode="script",
    )

    assert job_id == "v_script_xyz789"
    assert mock_session.post.call_count == 1

    payload = mock_session.post.call_args[1]["json"]
    assert payload["video_inputs"][0]["character"]["avatar_id"] == "avatar_brody_suit"
    assert payload["video_inputs"][0]["voice"]["type"] == "text"
    assert payload["video_inputs"][0]["voice"]["input_text"] == "Bienvenido a la capacitación en ciberseguridad."
    assert payload["video_inputs"][0]["voice"]["voice_id"] == "voice_es_alvaro"


def test_heygen_webhook_payload_injection(monkeypatch, tmp_path):
    """Test 10: Configured HEYGEN_WEBHOOK_URL injects callback_url and callback_id."""
    monkeypatch.setattr(settings, "ENABLE_LIVE_HEYGEN", True)
    monkeypatch.setattr(settings, "ENABLE_LIVE_API_TESTS", True)
    monkeypatch.setattr(settings, "HEYGEN_WEBHOOK_URL", "https://api.mycorp.com/api/v1/callbacks/heygen")

    resp_gen = MagicMock(spec=requests.Response)
    resp_gen.status_code = 200
    resp_gen.json.return_value = {"code": 100, "data": {"video_id": "v_webhook_123"}}

    mock_session = MagicMock(spec=requests.Session)
    mock_session.post.return_value = resp_gen

    provider = HeyGenProvider(api_key="valid_key", session=mock_session)
    provider.submit_avatar_job(
        scene_id="scene_1",
        locale="ar-SA",
        script_text="مرحبا بكم",
        mode="script",
        project_id="proj_cyber_01",
    )

    payload = mock_session.post.call_args[1]["json"]
    assert payload["callback_url"] == "https://api.mycorp.com/api/v1/callbacks/heygen"
    assert payload["callback_id"] == "proj_cyber_01:scene_1:ar-SA"


# ---------------------------------------------------------------------------
# 5. Polling & Status Tracking
# ---------------------------------------------------------------------------

def test_heygen_polling_states(monkeypatch):
    """Test 11: Polling handles processing, completed, and failed status correctly."""
    monkeypatch.setattr(settings, "ENABLE_LIVE_HEYGEN", True)
    monkeypatch.setattr(settings, "ENABLE_LIVE_API_TESTS", True)

    mock_session = MagicMock(spec=requests.Session)

    # 1. Processing state
    r_proc = MagicMock(spec=requests.Response)
    r_proc.status_code = 200
    r_proc.json.return_value = {"code": 100, "data": {"status": "processing"}}

    # 2. Completed state
    r_comp = MagicMock(spec=requests.Response)
    r_comp.status_code = 200
    r_comp.json.return_value = {
        "code": 100,
        "data": {
            "status": "completed",
            "video_url": "https://heygen.cdn/final.mp4",
            "duration": 8.45,
        },
    }

    # 3. Failed state
    r_fail = MagicMock(spec=requests.Response)
    r_fail.status_code = 200
    r_fail.json.return_value = {
        "code": 100,
        "data": {
            "status": "failed",
            "error": "Audio file unreadable or invalid format",
        },
    }

    mock_session.get.side_effect = [r_proc, r_comp, r_fail]

    provider = HeyGenProvider(api_key="valid_key", session=mock_session)

    res1 = provider.poll_avatar_job("job_1")
    assert res1["status"] == "processing"

    res2 = provider.poll_avatar_job("job_1")
    assert res2["status"] == "completed"
    assert res2["video_url"] == "https://heygen.cdn/final.mp4"
    assert res2["duration"] == 8.45

    res3 = provider.poll_avatar_job("job_1")
    assert res3["status"] == "failed"
    assert "Audio file unreadable" in res3["error"]


# ---------------------------------------------------------------------------
# 6. Asset Download & Technical Validation
# ---------------------------------------------------------------------------

def test_heygen_download_and_technical_validation(monkeypatch, tmp_path):
    """Test 12: Stream download saves MP4 and validates streams via ffprobe."""
    monkeypatch.setattr(settings, "ENABLE_LIVE_HEYGEN", True)
    monkeypatch.setattr(settings, "ENABLE_LIVE_API_TESTS", True)

    dest_mp4 = tmp_path / "avatar.mp4"
    fake_video_bytes = b"FAKE_MP4_CONTENT_" + b"0" * 4096

    mock_resp = MagicMock(spec=requests.Response)
    mock_resp.status_code = 200
    mock_resp.iter_content.return_value = [fake_video_bytes]
    mock_resp.__enter__.return_value = mock_resp

    mock_session = MagicMock(spec=requests.Session)
    mock_session.get.return_value = mock_resp

    provider = HeyGenProvider(api_key="valid_key", session=mock_session)

    with patch("app.services.avatar.heygen_provider.validate_video_file") as mock_validate:
        mock_validate.return_value = {
            "duration": 8.0,
            "width": 1920,
            "height": 1080,
            "has_video": True,
            "video_codec": "h264",
        }

        res = provider.download_avatar_video("https://heygen.cdn/video.mp4", dest_mp4)
        assert res == dest_mp4
        assert dest_mp4.exists()
        assert dest_mp4.stat().st_size == len(fake_video_bytes)
        mock_validate.assert_called_once()


def test_heygen_download_corrupted_raises_error(monkeypatch, tmp_path):
    """Test 13: Corrupted or invalid video file download raises HeyGenAPIError and cleans up bad file."""
    monkeypatch.setattr(settings, "ENABLE_LIVE_HEYGEN", True)
    monkeypatch.setattr(settings, "ENABLE_LIVE_API_TESTS", True)

    dest_mp4 = tmp_path / "corrupt.mp4"
    mock_resp = MagicMock(spec=requests.Response)
    mock_resp.status_code = 200
    mock_resp.iter_content.return_value = [b"bad_bytes"]
    mock_resp.__enter__.return_value = mock_resp

    mock_session = MagicMock(spec=requests.Session)
    mock_session.get.return_value = mock_resp

    provider = HeyGenProvider(api_key="valid_key", session=mock_session)

    with patch("app.services.avatar.heygen_provider.validate_video_file", side_effect=ValueError("No video stream found")):
        with pytest.raises(HeyGenAPIError, match="Failed to download or validate"):
            provider.download_avatar_video("https://heygen.cdn/corrupt.mp4", dest_mp4)

        # Ensure corrupted file was removed
        assert not dest_mp4.exists()


# ---------------------------------------------------------------------------
# 7. Safe Idempotency (Zero Duplicate Paid Submissions)
# ---------------------------------------------------------------------------

def test_heygen_idempotency_prevents_duplicate_submission(monkeypatch, tmp_path):
    """Test 14: generate_scene_avatar resumes polling existing in-flight job without calling submit_avatar_job."""
    monkeypatch.setattr(settings, "ENABLE_LIVE_HEYGEN", True)
    monkeypatch.setattr(settings, "ENABLE_LIVE_API_TESTS", True)

    dest_mp4 = tmp_path / "scene_1.mp4"
    job_file = tmp_path / "scene_1.job.json"

    # Pre-existing in-flight job persisted from earlier attempt
    job_record = {
        "job_id": "v_existing_paid_123",
        "scene_id": "scene_1",
        "locale": "en-US",
        "avatar_id": "avatar_brody",
        "provider": "heygen",
        "status": "processing",
        "submitted_at": 1000.0,
    }
    job_file.write_text(json.dumps(job_record), encoding="utf-8")

    provider = HeyGenProvider(api_key="valid_key")

    with patch.object(provider, "submit_avatar_job") as mock_submit:
        with patch.object(provider, "poll_avatar_job") as mock_poll:
            with patch.object(provider, "download_avatar_video") as mock_download:
                with patch("app.services.composition.ffmpeg_utils.validate_video_file") as mock_val:
                    mock_poll.return_value = {
                        "status": "completed",
                        "video_url": "https://heygen.cdn/existing.mp4",
                    }
                    mock_download.return_value = dest_mp4
                    dest_mp4.write_bytes(b"dummy mp4")
                    mock_val.return_value = {"duration": 7.5, "width": 1920, "height": 1080, "video_codec": "h264"}

                    asset = provider.generate_scene_avatar(
                        scene_id="scene_1",
                        locale="en-US",
                        audio_path=Path("audio.mp3"),
                        destination_path=dest_mp4,
                        avatar_id="avatar_brody",
                        poll_interval=0.01,
                    )

                    # CRITICAL: submit_avatar_job was NEVER called!
                    mock_submit.assert_not_called()
                    assert asset.job_id == "v_existing_paid_123"
                    assert asset.status == "completed"
                    assert asset.duration_seconds == 7.5


# ---------------------------------------------------------------------------
# 8. No Silent Fallback Policy
# ---------------------------------------------------------------------------

def test_heygen_never_silently_falls_back(monkeypatch, tmp_path):
    """Test 15: If HeyGen fails, generate_scene_avatar raises RuntimeError and never produces a static image."""
    monkeypatch.setattr(settings, "ENABLE_LIVE_HEYGEN", True)
    monkeypatch.setattr(settings, "ENABLE_LIVE_API_TESTS", True)

    dest_mp4 = tmp_path / "scene_failed.mp4"
    provider = HeyGenProvider(api_key="valid_key")

    with patch.object(provider, "submit_avatar_job", return_value="v_fail_999"):
        with patch.object(provider, "poll_avatar_job") as mock_poll:
            mock_poll.return_value = {
                "status": "failed",
                "error": "Face detection failed on custom portrait",
            }

            with pytest.raises(RuntimeError, match="Face detection failed"):
                provider.generate_scene_avatar(
                    scene_id="scene_failed",
                    locale="en-US",
                    audio_path=Path("audio.mp3"),
                    destination_path=dest_mp4,
                    poll_interval=0.01,
                )

            # File must NOT exist as a static fake image
            assert not dest_mp4.exists()


# ---------------------------------------------------------------------------
# 9. Provider Quota & Listing
# ---------------------------------------------------------------------------

def test_heygen_list_avatars_and_quota(monkeypatch):
    """Test 16: list_avatars and get_remaining_quota parse upstream responses correctly."""
    monkeypatch.setattr(settings, "ENABLE_LIVE_HEYGEN", True)
    monkeypatch.setattr(settings, "ENABLE_LIVE_API_TESTS", True)

    mock_session = MagicMock(spec=requests.Session)

    # 1. list_avatars response
    r_avatars = MagicMock(spec=requests.Response)
    r_avatars.status_code = 200
    r_avatars.json.return_value = {
        "code": 100,
        "data": {
            "avatars": [
                {"avatar_id": "a_1", "avatar_name": "Brody", "gender": "male"},
                {"avatar_id": "a_2", "avatar_name": "Jennifer", "gender": "female"},
            ]
        },
    }

    # 2. quota response
    r_quota = MagicMock(spec=requests.Response)
    r_quota.status_code = 200
    r_quota.json.return_value = {
        "code": 100,
        "data": {"quota": 14.5, "unit": "credits"},
    }

    mock_session.get.side_effect = [r_avatars, r_quota]

    provider = HeyGenProvider(api_key="valid_key", session=mock_session)

    avatars = provider.list_avatars()
    assert len(avatars) == 2
    assert avatars[0]["avatar_name"] == "Brody"

    quota_info = provider.get_remaining_quota()
    assert quota_info["remaining_quota"] == 14.5


# ---------------------------------------------------------------------------
# 10. Mock and SadTalker Compatibility
# ---------------------------------------------------------------------------

def test_mock_and_sadtalker_compatibility(tmp_path):
    """Test 17: MockAvatarProvider and SadTalkerProvider satisfy AvatarProvider interface and accept new kwargs."""
    mock_prov = MockAvatarProvider()
    assert isinstance(mock_prov, AvatarProvider)
    assert mock_prov.provider_name == "mock"

    # Mock provider submit accepts script_text, mode, etc.
    job_id = mock_prov.submit_avatar_job(
        scene_id="s1",
        locale="en-US",
        audio_path=None,
        script_text="Hello world",
        mode="script",
    )
    assert job_id.startswith("mock_job_")

    sadtalker_prov = SadTalkerProvider()
    assert isinstance(sadtalker_prov, AvatarProvider)
    assert sadtalker_prov.provider_name == "sadtalker"
