"""Comprehensive Isolated Unit Test Suite for Google Veo Video Provider (Phase 2).

Strict Safety Policy:
- All tests are fully mocked.
- Zero live paid API calls or credit consumption.
- Verifies official Vertex AI Veo predictLongRunning schema, Text-to-Video,
  Image-to-Video, operation polling, GCS retrieval, ffprobe technical validation,
  rate limiting, quota exhaustion, safe idempotency, and zero silent fallbacks.
"""

import base64
import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
import requests

from app.core.config import settings
from app.models.schemas import LocalizedScene
from app.services.media.base import SceneMediaProvider
from app.services.media.veo_video_provider import (
    VeoVideoProvider,
    VeoError,
    VeoConfigError,
    VeoAuthError,
    VeoQuotaError,
    VeoRateLimitError,
    VeoTimeoutError,
    VeoGenerationError,
    VeoStorageError,
    VeoValidationError,
)
from app.services.media.motion_visual_provider import LocalMotionVisualProvider
from app.services.media.mock_media_provider import MockMediaProvider
from app.services.media.factory import get_media_provider
from app.services.media.service import SceneMediaService


# Fixture for sample localized scene
@pytest.fixture
def sample_scene():
    return LocalizedScene(
        scene_id="scene_broll_01",
        order=1,
        title="Phishing Email Attack Surface",
        purpose="Explain attack vectors",
        narration="Attackers disguise malicious hyperlinks inside seemingly legitimate corporate communications.",
        estimated_duration_seconds=6,
        scene_type="instructional",
        media_type="veo",
        visual_description="Cinematic macro shot of an office desk with a glowing computer monitor showing an encrypted login portal.",
        motion_description="Slow tracking forward camera movement with soft focus depth of field.",
    )


# ---------------------------------------------------------------------------
# 1. Configuration & Safety Gates
# ---------------------------------------------------------------------------

def test_veo_configuration_validation():
    """Test 1: Missing project or location raises VeoConfigError."""
    # Missing project
    provider_no_proj = VeoVideoProvider(project="", location="us-central1")
    with pytest.raises(VeoConfigError, match="Missing GOOGLE_CLOUD_PROJECT"):
        provider_no_proj.validate_configuration()

    # Missing location
    provider_no_loc = VeoVideoProvider(project="my-project-123", location="")
    with pytest.raises(VeoConfigError, match="Missing GOOGLE_CLOUD_LOCATION"):
        provider_no_loc.validate_configuration()


def test_veo_safety_gate_enforcement(monkeypatch):
    """Test 2: VeoProvider strictly blocks live operations when ENABLE_LIVE_VEO=False."""
    monkeypatch.setattr(settings, "ENABLE_LIVE_VEO", False)
    provider = VeoVideoProvider(project="test-proj", location="us-central1")

    with pytest.raises(RuntimeError, match="ENABLE_LIVE_VEO=False"):
        provider.submit_generation_operation(prompt="A cyber laboratory")

    with pytest.raises(RuntimeError, match="ENABLE_LIVE_VEO=False"):
        provider.poll_operation("projects/test-proj/locations/us-central1/operations/123")


def test_veo_safety_gate_blocks_in_pytest_without_test_flag(monkeypatch):
    """Test 2B: Even if ENABLE_LIVE_VEO=True, automated tests require ENABLE_LIVE_API_TESTS=True."""
    monkeypatch.setattr(settings, "ENABLE_LIVE_VEO", True)
    monkeypatch.setattr(settings, "ENABLE_LIVE_API_TESTS", False)
    provider = VeoVideoProvider(project="test-proj", location="us-central1")

    with pytest.raises(RuntimeError, match="ENABLE_LIVE_API_TESTS=False"):
        provider.submit_generation_operation(prompt="A cyber laboratory")


# ---------------------------------------------------------------------------
# 3. Text-to-Video Submission
# ---------------------------------------------------------------------------

def test_veo_text_to_video_submission(monkeypatch):
    """Test 3: Text-to-Video creates valid Vertex AI predictLongRunning payload with 16:9 aspect ratio."""
    monkeypatch.setattr(settings, "ENABLE_LIVE_VEO", True)
    monkeypatch.setattr(settings, "ENABLE_LIVE_API_TESTS", True)

    mock_resp = MagicMock(spec=requests.Response)
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "name": "projects/my-test-proj/locations/us-central1/operations/op_veo_txt_12345"
    }

    mock_session = MagicMock(spec=requests.Session)
    mock_session.post.return_value = mock_resp

    provider = VeoVideoProvider(
        project="my-test-proj",
        location="us-central1",
        model="veo-3.1-fast-generate-001",
        access_token="mock_bearer_token",
        session=mock_session,
    )

    op_name = provider.submit_generation_operation(
        prompt="Cinematic shot of network servers blinking in a dark data center",
        image_path=None,
        duration_seconds=6.0,
        resolution="1080p",
        aspect_ratio="16:9",
    )

    assert op_name == "projects/my-test-proj/locations/us-central1/operations/op_veo_txt_12345"
    assert mock_session.post.call_count == 1

    call_args = mock_session.post.call_args
    url = call_args[0][0]
    assert "veo-3.1-fast-generate-001:predictLongRunning" in url
    assert "Authorization" in call_args[1]["headers"]
    assert call_args[1]["headers"]["Authorization"] == "Bearer mock_bearer_token"

    payload = call_args[1]["json"]
    assert len(payload["instances"]) == 1
    assert payload["instances"][0]["prompt"] == "Cinematic shot of network servers blinking in a dark data center"
    assert "image" not in payload["instances"][0]
    assert payload["parameters"]["aspectRatio"] == "16:9"
    assert payload["parameters"]["durationSeconds"] == 6
    assert payload["parameters"]["resolution"] == "1080p"


# ---------------------------------------------------------------------------
# 4. Image-to-Video Submission
# ---------------------------------------------------------------------------

def test_veo_image_to_video_submission(monkeypatch, tmp_path):
    """Test 4: Image-to-Video embeds base64 encoded image and mimeType in instances."""
    monkeypatch.setattr(settings, "ENABLE_LIVE_VEO", True)
    monkeypatch.setattr(settings, "ENABLE_LIVE_API_TESTS", True)

    img_file = tmp_path / "reference_frame.png"
    dummy_img_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 256
    img_file.write_bytes(dummy_img_bytes)

    mock_resp = MagicMock(spec=requests.Response)
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "name": "projects/my-test-proj/locations/us-central1/operations/op_veo_img_67890"
    }

    mock_session = MagicMock(spec=requests.Session)
    mock_session.post.return_value = mock_resp

    provider = VeoVideoProvider(
        project="my-test-proj",
        location="us-central1",
        model="veo-3.1-generate-001",
        access_token="mock_bearer_token",
        session=mock_session,
    )

    op_name = provider.submit_generation_operation(
        prompt="Animate this terminal interface with incoming security alerts",
        image_path=img_file,
        duration_seconds=5.0,
        resolution="720p",
    )

    assert op_name == "projects/my-test-proj/locations/us-central1/operations/op_veo_img_67890"

    payload = mock_session.post.call_args[1]["json"]
    inst = payload["instances"][0]
    assert "image" in inst
    assert inst["image"]["mimeType"] == "image/png"
    assert inst["image"]["bytesBase64Encoded"] == base64.b64encode(dummy_img_bytes).decode("ascii")


# ---------------------------------------------------------------------------
# 5. Operation Polling (In-Flight, Completed, Failed)
# ---------------------------------------------------------------------------

def test_veo_operation_polling_in_flight(monkeypatch):
    """Test 5: Polling returning done=False maps to status 'processing'."""
    monkeypatch.setattr(settings, "ENABLE_LIVE_VEO", True)
    monkeypatch.setattr(settings, "ENABLE_LIVE_API_TESTS", True)

    mock_resp = MagicMock(spec=requests.Response)
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "name": "projects/p/locations/l/operations/op_123",
        "done": False,
    }

    mock_session = MagicMock(spec=requests.Session)
    mock_session.get.return_value = mock_resp

    provider = VeoVideoProvider(project="p", location="l", access_token="tok", session=mock_session)
    res = provider.poll_operation("projects/p/locations/l/operations/op_123")

    assert res["done"] is False
    assert res["status"] == "processing"


def test_veo_operation_successful_completion_with_bytes(monkeypatch):
    """Test 6: Successful completion with base64 video bytes decodes correctly."""
    monkeypatch.setattr(settings, "ENABLE_LIVE_VEO", True)
    monkeypatch.setattr(settings, "ENABLE_LIVE_API_TESTS", True)

    fake_raw_video = b"MP4_VIDEO_RAW_HEADER_DATA_" + b"0" * 1024
    b64_str = base64.b64encode(fake_raw_video).decode("ascii")

    mock_resp = MagicMock(spec=requests.Response)
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "name": "projects/p/locations/l/operations/op_123",
        "done": True,
        "response": {
            "generateVideoResponse": {
                "generatedSamples": [
                    {
                        "video": {
                            "bytesBase64Encoded": b64_str,
                        }
                    }
                ]
            }
        },
    }

    mock_session = MagicMock(spec=requests.Session)
    mock_session.get.return_value = mock_resp

    provider = VeoVideoProvider(project="p", location="l", access_token="tok", session=mock_session)
    res = provider.poll_operation("projects/p/locations/l/operations/op_123")

    assert res["done"] is True
    assert res["status"] == "completed"
    assert res["video_bytes"] == fake_raw_video
    assert res["gcs_uri"] is None


def test_veo_operation_failure_handling(monkeypatch):
    """Test 7: Operation level error reports status 'failed' with server message."""
    monkeypatch.setattr(settings, "ENABLE_LIVE_VEO", True)
    monkeypatch.setattr(settings, "ENABLE_LIVE_API_TESTS", True)

    mock_resp = MagicMock(spec=requests.Response)
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "name": "projects/p/locations/l/operations/op_fail",
        "done": True,
        "error": {
            "code": 3,
            "message": "Prompt violated safety guidelines: blocked keywords detected",
        },
    }

    mock_session = MagicMock(spec=requests.Session)
    mock_session.get.return_value = mock_resp

    provider = VeoVideoProvider(project="p", location="l", access_token="tok", session=mock_session)
    res = provider.poll_operation("projects/p/locations/l/operations/op_fail")

    assert res["done"] is True
    assert res["status"] == "failed"
    assert "Prompt violated safety guidelines" in res["error"]


def test_veo_quota_exhaustion_raises_veo_quota_error(monkeypatch):
    """Test 7B: Quota exhaustion in operation error raises explicit VeoQuotaError."""
    monkeypatch.setattr(settings, "ENABLE_LIVE_VEO", True)
    monkeypatch.setattr(settings, "ENABLE_LIVE_API_TESTS", True)

    mock_resp = MagicMock(spec=requests.Response)
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "name": "projects/p/locations/l/operations/op_quota",
        "done": True,
        "error": {
            "code": 8,
            "message": "Resource exhausted: quota exceeded for video generation requests per day",
        },
    }

    mock_session = MagicMock(spec=requests.Session)
    mock_session.get.return_value = mock_resp

    provider = VeoVideoProvider(project="p", location="l", access_token="tok", session=mock_session)
    with pytest.raises(VeoQuotaError, match="quota exhausted"):
        provider.poll_operation("projects/p/locations/l/operations/op_quota")


# ---------------------------------------------------------------------------
# 6. Rate Limit & Retries
# ---------------------------------------------------------------------------

def test_veo_rate_limit_handling(monkeypatch):
    """Test 8: HTTP 429 applies exponential backoff retry and succeeds on subsequent try."""
    monkeypatch.setattr(settings, "ENABLE_LIVE_VEO", True)
    monkeypatch.setattr(settings, "ENABLE_LIVE_API_TESTS", True)

    resp_429 = MagicMock(spec=requests.Response)
    resp_429.status_code = 429
    resp_429.text = "Too Many Requests"

    resp_200 = MagicMock(spec=requests.Response)
    resp_200.status_code = 200
    resp_200.json.return_value = {"name": "projects/p/locations/l/operations/op_retry_ok"}

    mock_session = MagicMock(spec=requests.Session)
    mock_session.post.side_effect = [resp_429, resp_200]

    with patch("time.sleep") as mock_sleep:
        provider = VeoVideoProvider(project="p", location="l", access_token="tok", session=mock_session)
        op_name = provider.submit_generation_operation(prompt="Cybersecurity shield")

        assert op_name == "projects/p/locations/l/operations/op_retry_ok"
        assert mock_session.post.call_count == 2
        mock_sleep.assert_called_once()


# ---------------------------------------------------------------------------
# 7. Cloud Storage Download & Validation
# ---------------------------------------------------------------------------

def test_veo_cloud_storage_download(monkeypatch, tmp_path):
    """Test 9: download_gcs_asset parses gs:// URI and retrieves object via Storage REST API."""
    monkeypatch.setattr(settings, "ENABLE_LIVE_VEO", True)
    monkeypatch.setattr(settings, "ENABLE_LIVE_API_TESTS", True)

    dest_mp4 = tmp_path / "downloaded_veo.mp4"
    fake_bytes = b"GCS_STORED_MP4_CONTENT_" + b"0" * 2048

    mock_resp = MagicMock(spec=requests.Response)
    mock_resp.status_code = 200
    mock_resp.iter_content.return_value = [fake_bytes]
    mock_resp.__enter__.return_value = mock_resp

    mock_session = MagicMock(spec=requests.Session)
    mock_session.get.return_value = mock_resp

    provider = VeoVideoProvider(project="p", location="l", access_token="tok", session=mock_session)
    res_path = provider.download_gcs_asset("gs://my-training-bucket/veo/scene_1.mp4", dest_mp4)

    assert res_path == dest_mp4
    assert dest_mp4.exists()
    assert dest_mp4.stat().st_size == len(fake_bytes)

    # Verify storage endpoint URL format
    get_url = mock_session.get.call_args[0][0]
    assert "https://storage.googleapis.com/storage/v1/b/my-training-bucket/o/veo%2Fscene_1.mp4" in get_url


def test_veo_invalid_mp4_rejection(monkeypatch, tmp_path, sample_scene):
    """Test 10: Corrupted MP4 output is rejected and raises VeoValidationError without saving bad file."""
    monkeypatch.setattr(settings, "ENABLE_LIVE_VEO", True)
    monkeypatch.setattr(settings, "ENABLE_LIVE_API_TESTS", True)

    provider = VeoVideoProvider(project="p", location="l", access_token="tok")

    with patch.object(provider, "submit_generation_operation", return_value="projects/p/locations/l/operations/op_val"):
        with patch.object(provider, "poll_operation") as mock_poll:
            mock_poll.return_value = {
                "done": True,
                "status": "completed",
                "video_bytes": b"corrupt_broken_file_bytes",
            }

            with patch("app.services.media.veo_video_provider.validate_video_file", side_effect=ValueError("No video stream found")):
                with pytest.raises(VeoValidationError, match="failed technical validation"):
                    provider.generate_scene_media(
                        scene=sample_scene,
                        locale="en-US",
                        output_dir=tmp_path,
                        duration_seconds=5.0,
                    )

                # Ensure corrupted output was unlinked
                assert not (tmp_path / f"{sample_scene.scene_id}_veo.mp4").exists()


# ---------------------------------------------------------------------------
# 8. Safe Idempotency & Duplicate Prevention
# ---------------------------------------------------------------------------

def test_veo_idempotency_prevents_duplicate_submission(monkeypatch, tmp_path, sample_scene):
    """Test 11: Resumes polling existing in-flight operation from job file without submitting new paid operation."""
    monkeypatch.setattr(settings, "ENABLE_LIVE_VEO", True)
    monkeypatch.setattr(settings, "ENABLE_LIVE_API_TESTS", True)

    job_file = tmp_path / f"{sample_scene.scene_id}.veo_job.json"
    in_flight_job = {
        "operation_name": "projects/p/locations/l/operations/op_in_flight_999",
        "scene_id": sample_scene.scene_id,
        "locale": "en-US",
        "status": "processing",
        "submitted_at": 1000.0,
    }
    job_file.write_text(json.dumps(in_flight_job), encoding="utf-8")

    provider = VeoVideoProvider(project="p", location="l", access_token="tok", poll_interval=0.01)

    with patch.object(provider, "submit_generation_operation") as mock_submit:
        with patch.object(provider, "poll_operation") as mock_poll:
            with patch("app.services.media.veo_video_provider.validate_video_file") as mock_val:
                mock_poll.return_value = {
                    "done": True,
                    "status": "completed",
                    "video_bytes": b"VALID_VIDEO_DATA" + b"0" * 2048,
                }
                mock_val.return_value = {
                    "duration": 5.0,
                    "width": 1920,
                    "height": 1080,
                    "has_video": True,
                    "video_codec": "h264",
                }

                out_path = provider.generate_scene_media(
                    scene=sample_scene,
                    locale="en-US",
                    output_dir=tmp_path,
                    duration_seconds=5.0,
                )

                # CRITICAL: submit_generation_operation was NEVER called!
                mock_submit.assert_not_called()
                assert out_path.exists()

                # Verify job file was marked completed
                completed_job = json.loads(job_file.read_text(encoding="utf-8"))
                assert completed_job["status"] == "completed"
                assert completed_job["duration_seconds"] == 5.0


def test_veo_timeout_handling(monkeypatch, tmp_path, sample_scene):
    """Test 12: VeoTimeoutError is raised when polling exceeds timeout_seconds."""
    monkeypatch.setattr(settings, "ENABLE_LIVE_VEO", True)
    monkeypatch.setattr(settings, "ENABLE_LIVE_API_TESTS", True)

    provider = VeoVideoProvider(
        project="p",
        location="l",
        access_token="tok",
        poll_interval=0.01,
        timeout_seconds=0.05,
    )

    with patch.object(provider, "submit_generation_operation", return_value="projects/p/locations/l/operations/op_slow"):
        with patch.object(provider, "poll_operation") as mock_poll:
            mock_poll.return_value = {"done": False, "status": "processing"}

            with pytest.raises(VeoTimeoutError, match="timed out"):
                provider.generate_scene_media(
                    scene=sample_scene,
                    locale="en-US",
                    output_dir=tmp_path,
                    duration_seconds=5.0,
                )


# ---------------------------------------------------------------------------
# 9. No Silent Fallback Policy
# ---------------------------------------------------------------------------

def test_veo_never_silently_falls_back_to_ken_burns(monkeypatch, tmp_path, sample_scene):
    """Test 13: When Veo fails, provider raises exception and never produces a static Ken Burns video."""
    monkeypatch.setattr(settings, "ENABLE_LIVE_VEO", True)
    monkeypatch.setattr(settings, "ENABLE_LIVE_API_TESTS", True)

    provider = VeoVideoProvider(project="p", location="l", access_token="tok", poll_interval=0.01)

    with patch.object(provider, "submit_generation_operation", return_value="projects/p/locations/l/operations/op_broken"):
        with patch.object(provider, "poll_operation") as mock_poll:
            mock_poll.return_value = {
                "done": True,
                "status": "failed",
                "error": "Internal Vertex AI accelerator failure",
            }

            with pytest.raises(VeoGenerationError, match="accelerator failure"):
                provider.generate_scene_media(
                    scene=sample_scene,
                    locale="en-US",
                    output_dir=tmp_path,
                    duration_seconds=5.0,
                )

            # Assert no fallback MP4 was written
            assert not (tmp_path / f"{sample_scene.scene_id}_veo.mp4").exists()


# ---------------------------------------------------------------------------
# 10. Provider Factory & Compatibility
# ---------------------------------------------------------------------------

def test_media_factory_and_provider_compatibility(monkeypatch):
    """Test 14: get_media_provider returns correct instances and respects safety gate."""
    # 1. Motion visual default
    mv_provider = get_media_provider("motion_visual")
    assert isinstance(mv_provider, LocalMotionVisualProvider)
    assert mv_provider.provider_name == "local_motion"

    # 2. Mock provider
    mock_prov = get_media_provider("mock")
    assert isinstance(mock_prov, MockMediaProvider)
    assert mock_prov.provider_name == "mock"

    # 3. Veo blocked when ENABLE_LIVE_VEO=False
    monkeypatch.setattr(settings, "ENABLE_LIVE_VEO", False)
    with pytest.raises(PermissionError, match="ENABLE_LIVE_VEO=False"):
        get_media_provider("veo")

    # 4. Veo allowed when ENABLE_LIVE_VEO=True
    monkeypatch.setattr(settings, "ENABLE_LIVE_VEO", True)
    veo_prov = get_media_provider("veo")
    assert isinstance(veo_prov, VeoVideoProvider)
    assert veo_prov.provider_name == "veo"


def test_scene_media_service_veo_dispatch(monkeypatch, tmp_path, sample_scene):
    """Test 15: SceneMediaService dispatches scene with media_type='veo' to VeoVideoProvider."""
    monkeypatch.setattr(settings, "ENABLE_LIVE_VEO", True)
    service = SceneMediaService()

    fake_veo_out = tmp_path / "mock_veo_out.mp4"
    fake_veo_out.write_bytes(b"dummy mp4")

    with patch("app.services.media.service.get_media_provider") as mock_factory:
        mock_veo = MagicMock()
        mock_veo.generate_scene_media.return_value = fake_veo_out
        mock_factory.return_value = mock_veo

        res = service.generate_scene_media(
            scene=sample_scene,
            locale="en-US",
            output_dir=tmp_path,
            duration_seconds=5.0,
        )

        assert res == fake_veo_out
        mock_factory.assert_called_once_with("veo")
        mock_veo.generate_scene_media.assert_called_once()
