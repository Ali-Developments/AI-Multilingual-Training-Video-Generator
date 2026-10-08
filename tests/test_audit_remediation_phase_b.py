"""Tests for Audit Remediation Phase B:
- ISSUE-003: Dynamic Provider Status & Metadata Exposure Prevention
- ISSUE-004: Manifest Structured Error Recording, Deduplication & Retry Clearing
- ISSUE-002: Avatar Safety Gate & Live HeyGen Control
"""

import asyncio
from pathlib import Path
import pytest
from pydantic import ValidationError
from unittest.mock import patch

from app.core.config import settings
from app.models.schemas import TrainingVideoRequest, ProjectManifest, ManifestError
from app.services.avatar.factory import get_avatar_provider
from app.services.avatar.mock_avatar_provider import MockAvatarProvider
from app.services.avatar.heygen_provider import HeyGenProvider
from app.api.v1.health import get_health


def test_issue_003_health_endpoint_dynamic_provider_metadata():
    """Verify health endpoint dynamically returns provider metadata without leaking keys."""
    resp = asyncio.run(get_health())
    status_dict = resp.model_dump()
    assert "details" in status_dict
    details = status_dict["details"]
    assert "llm_provider" in details
    assert "llm_model" in details
    assert "default_tts" in details
    assert "default_avatar" in details
    assert "enable_live_heygen" in details

    # Ensure sensitive credentials are never leaked
    raw_status_str = str(status_dict).lower()
    assert "api_key" not in raw_status_str
    assert "gsk_" not in raw_status_str


def test_issue_004_manifest_error_deduplication():
    """Verify duplicate errors increment occurrence_count rather than spamming manifest."""
    manifest = ProjectManifest(
        project_id="test_manifest_err",
        source_request=TrainingVideoRequest(
            topic="Security Awareness",
            base_language="en-US",
            target_languages=["es-ES"],
        ),
    )

    # Record first error
    manifest.record_error(stage="localization", message="Timeout contacting LLM", code="TIMEOUT")
    assert len(manifest.error_details) == 1
    assert manifest.error_details[0].occurrence_count == 1
    assert manifest.error_details[0].stage == "localization"
    assert manifest.error_details[0].code == "TIMEOUT"
    assert len(manifest.errors) == 1

    # Record exact same error again (e.g. on retry)
    manifest.record_error(stage="localization", message="Timeout contacting LLM", code="TIMEOUT")
    assert len(manifest.error_details) == 1, "Duplicate error must not be appended"
    assert manifest.error_details[0].occurrence_count == 2, "occurrence_count must increment"
    assert len(manifest.errors) == 1, "errors string list must not have duplicates"

    # Record a different error in the same stage
    manifest.record_error(stage="localization", message="Invalid JSON output", code="PARSE_ERROR")
    assert len(manifest.error_details) == 2, "Distinct error must be preserved"
    assert manifest.error_details[1].code == "PARSE_ERROR"

    # Record error in a different stage
    manifest.record_error(stage="tts", message="Audio synthesis failed", code="AUDIO_FAIL")
    assert len(manifest.error_details) == 3


def test_issue_004_manifest_clear_stage_errors_on_retry():
    """Verify successful retries clear previous errors for that stage while keeping other stages intact."""
    manifest = ProjectManifest(
        project_id="test_manifest_clear",
        source_request=TrainingVideoRequest(
            topic="Security Awareness",
            base_language="en-US",
            target_languages=["es-ES"],
        ),
    )

    manifest.record_error(stage="localization", message="Fail 1", code="E1")
    manifest.record_error(stage="localization", message="Fail 2", code="E2")
    manifest.record_error(stage="composition", message="FFmpeg missing", code="E3")
    assert len(manifest.error_details) == 3

    # Clear localization errors after successful retry
    manifest.clear_stage_errors("localization")
    assert len(manifest.error_details) == 1
    assert manifest.error_details[0].stage == "composition"
    assert manifest.error_details[0].code == "E3"
    assert manifest.errors == ["FFmpeg missing"]


def test_issue_002_avatar_safety_gate_blocks_heygen_when_disabled():
    """Verify get_avatar_provider blocks live HeyGen when ENABLE_LIVE_HEYGEN is False."""
    with patch.object(settings, "ENABLE_LIVE_HEYGEN", False):
        with pytest.raises(PermissionError) as exc_info:
            get_avatar_provider("heygen")
        assert "ENABLE_LIVE_HEYGEN=False" in str(exc_info.value)


def test_issue_002_avatar_safety_gate_allows_heygen_only_when_explicitly_enabled():
    """Verify live HeyGen is instantiable when ENABLE_LIVE_HEYGEN is True."""
    with patch.object(settings, "ENABLE_LIVE_HEYGEN", True):
        provider = get_avatar_provider("heygen")
        assert isinstance(provider, HeyGenProvider)


def test_issue_002_request_requires_ack_paid_credits_for_heygen():
    """Verify TrainingVideoRequest validation rejects heygen without explicit credit acknowledgement."""
    # When ENABLE_LIVE_HEYGEN is False, attempting heygen is blocked by config safety gate
    with patch.object(settings, "ENABLE_LIVE_HEYGEN", False):
        with pytest.raises(ValidationError) as exc_info:
            TrainingVideoRequest(
                topic="Workplace Phishing Defense Essentials",
                base_language="en-US",
                target_languages=["ar-SA"],
                avatar_provider="heygen",
                ack_paid_credits=True,
            )
        assert "ENABLE_LIVE_HEYGEN is False" in str(exc_info.value)

    # When ENABLE_LIVE_HEYGEN is True, ack_paid_credits=False is rejected
    with patch.object(settings, "ENABLE_LIVE_HEYGEN", True):
        with pytest.raises(ValidationError) as exc_info:
            TrainingVideoRequest(
                topic="Workplace Phishing Defense Essentials",
                base_language="en-US",
                target_languages=["ar-SA"],
                avatar_provider="heygen",
                ack_paid_credits=False,
            )
        assert "paid credits" in str(exc_info.value)

        # When both ENABLE_LIVE_HEYGEN is True and ack_paid_credits=True, request is valid
        valid_req = TrainingVideoRequest(
            topic="Workplace Phishing Defense Essentials",
            base_language="en-US",
            target_languages=["ar-SA"],
            avatar_provider="heygen",
            ack_paid_credits=True,
        )
        assert valid_req.avatar_provider == "heygen"
        assert valid_req.ack_paid_credits is True


def test_issue_002_mock_avatar_remains_safe_default():
    """Verify mock avatar is default and requires no special credit acknowledgements."""
    default_req = TrainingVideoRequest(
        topic="Workplace Phishing Defense Essentials",
        base_language="en-US",
        target_languages=["ar-SA"],
    )
    assert default_req.avatar_provider == "mock"
    assert default_req.ack_paid_credits is False

    provider = get_avatar_provider("mock")
    assert isinstance(provider, MockAvatarProvider)


def test_diagnostic_secret_safety_redaction():
    """Verify API keys and sensitive tokens are redacted from manifest diagnostics."""
    manifest = ProjectManifest(
        project_id="test_security_leak_prevention",
        source_request=TrainingVideoRequest(
            topic="Security Test",
            base_language="en-US",
            target_languages=["en-US"],
        ),
    )

    fake_groq_key = "gsk_1234567890abcdef1234567890"
    raw_error_message = f"Failed contacting Groq with key {fake_groq_key} and Authorization: Bearer secret_session_token_12345678"

    manifest.record_error(stage="script", message=raw_error_message, code="GROQ_AUTH_FAIL")

    assert len(manifest.error_details) == 1
    recorded = manifest.error_details[0]

    assert fake_groq_key not in recorded.message
    assert "gsk_[REDACTED]" in recorded.message
    assert "secret_session_token" not in recorded.message
    assert fake_groq_key not in manifest.errors[0]


def test_heygen_runtime_flag_separation():
    """Verify application runtime can instantiate HeyGen when ENABLE_LIVE_HEYGEN=True without ENABLE_LIVE_API_TESTS."""
    with patch.object(settings, "ENABLE_LIVE_HEYGEN", True):
        with patch.object(settings, "ENABLE_LIVE_API_TESTS", False):
            with patch.object(settings, "HEYGEN_API_KEY", "dummy_key"):
                provider = get_avatar_provider("heygen")
                assert isinstance(provider, HeyGenProvider)


def test_heygen_test_suite_blocked_without_live_api_tests_flag():
    """Verify automated tests running in pytest cannot submit real HeyGen jobs when ENABLE_LIVE_API_TESTS=False."""
    with patch.object(settings, "ENABLE_LIVE_HEYGEN", True):
        with patch.object(settings, "ENABLE_LIVE_API_TESTS", False):
            provider = HeyGenProvider(api_key="valid_dummy_key")
            with pytest.raises(RuntimeError) as exc_info:
                provider.submit_avatar_job(
                    scene_id="scene_1",
                    locale="ar-SA",
                    audio_path=Path("dummy.mp3"),
                )
            assert "ENABLE_LIVE_API_TESTS=False" in str(exc_info.value)


