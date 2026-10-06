"""Tests for Streamlit frontend helpers and integration."""

from pathlib import Path
import pytest
from unittest.mock import patch, MagicMock

from frontend.helpers import (
    APIClientError,
    check_backend_health,
    create_project_via_api,
    fetch_project_manifest_via_api,
    fetch_projects_direct,
    fetch_projects_via_api,
    format_api_error_detail,
    get_direct_manifest_manager,
    load_manifest_direct,
    resume_project_via_api,
    run_project_via_api,
    serialize_create_project_payload,
)


def test_check_backend_health_success():
    with patch("httpx.get") as mock_get:
        mock_get.return_value = MagicMock(status_code=200, json=lambda: {"status": "ok"})
        res = check_backend_health("http://localhost:8000")
        assert res == {"status": "ok"}


def test_check_backend_health_failure():
    with patch("httpx.get") as mock_get:
        mock_get.side_effect = Exception("Connection refused")
        res = check_backend_health("http://localhost:8000")
        assert res is None


def test_fetch_projects_via_api():
    with patch("httpx.get") as mock_get:
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: [{"project_id": "proj-123", "status": "completed"}],
        )
        projects = fetch_projects_via_api("http://localhost:8000")
        assert len(projects) == 1
        assert projects[0]["project_id"] == "proj-123"


def test_fetch_project_manifest_via_api():
    with patch("httpx.get") as mock_get:
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"project_id": "proj-123", "status": "completed"},
        )
        manifest = fetch_project_manifest_via_api("http://localhost:8000", "proj-123")
        assert manifest is not None
        assert manifest["project_id"] == "proj-123"


def test_run_project_via_api():
    with patch("httpx.post") as mock_post:
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"project_id": "proj-123", "status": "completed"},
        )
        res = run_project_via_api("http://localhost:8000", "proj-123")
        assert res is not None
        assert res["status"] == "completed"


def test_resume_project_via_api():
    with patch("httpx.post") as mock_post:
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"project_id": "proj-123", "status": "completed"},
        )
        res = resume_project_via_api("http://localhost:8000", "proj-123")
        assert res is not None
        assert res["status"] == "completed"


def test_create_project_via_api():
    with patch("httpx.post") as mock_post:
        mock_post.return_value = MagicMock(
            status_code=201,
            json=lambda: {"project_id": "proj-456", "status": "pending"},
        )
        res = create_project_via_api("http://localhost:8000", {"topic": "Test"})
        assert res is not None
        assert res["project_id"] == "proj-456"
        # Verify httpx was called with the wrapped request schema
        call_kwargs = mock_post.call_args.kwargs
        assert "json" in call_kwargs
        sent_body = call_kwargs["json"]
        assert "request" in sent_body
        assert sent_body["request"]["topic"] == "Test"


def test_serialize_create_project_payload_en_to_ar():
    payload = serialize_create_project_payload(
        topic="Defensive Cybersecurity",
        source_content="Core guidelines on zero trust architecture.",
        audience="IT Staff",
        base_language="en-US",
        target_languages=["ar-SA"],
        target_duration_seconds=90,
        tone="authoritative",
        difficulty_level="advanced",
        learning_objectives=["Understand Zero Trust", "Apply MFA policies"],
    )
    assert payload["project_id"] is None
    req = payload["request"]
    assert req["topic"] == "Defensive Cybersecurity"
    assert req["source_content"] == "Core guidelines on zero trust architecture."
    assert req["audience"] == "IT Staff"
    assert req["base_language"] == "en-US"
    assert req["target_languages"] == ["ar-SA"]
    assert req["target_duration_seconds"] == 90
    assert req["tone"] == "authoritative"
    assert req["difficulty_level"] == "advanced"
    assert req["learning_objectives"] == ["Understand Zero Trust", "Apply MFA policies"]
    assert req["locale"] is None


def test_serialize_create_project_payload_legacy_kwargs():
    payload = serialize_create_project_payload(
        topic="Legacy Mapping Test",
        target_locales=["ar-SA"],
        difficulty="beginner",
    )
    req = payload["request"]
    assert req["target_languages"] == ["ar-SA"]
    assert req["difficulty_level"] == "beginner"
    assert req["topic"] == "Legacy Mapping Test"


def test_format_api_error_detail():
    pydantic_detail = [
        {"type": "missing", "loc": ["body", "request", "topic"], "msg": "Field required"},
        {"type": "value_error", "loc": ["body", "request"], "msg": "Invalid duration"},
    ]
    formatted = format_api_error_detail(pydantic_detail)
    assert "request -> topic" in formatted
    assert "Field required" in formatted
    assert "Invalid duration" in formatted

    str_formatted = format_api_error_detail("Custom backend error message")
    assert str_formatted == "Custom backend error message"


def test_create_project_via_api_raises_api_client_error():
    with patch("httpx.post") as mock_post:
        mock_post.return_value = MagicMock(
            status_code=422,
            json=lambda: {"detail": [{"type": "missing", "loc": ["body", "request"], "msg": "Field required"}]},
        )
        with pytest.raises(APIClientError) as exc_info:
            create_project_via_api("http://localhost:8000", {"topic": "Bad Payload"}, raise_for_status=True)

        err = exc_info.value
        assert err.status_code == 422
        assert "Field required" in err.message
        assert isinstance(err.detail, list)


def test_direct_manifest_manager_resolution(tmp_path):
    with patch("frontend.helpers.settings") as mock_settings:
        mock_settings.STORAGE_PATH = Path(tmp_path)
        mgr = get_direct_manifest_manager()
        assert mgr is not None
        assert mgr.storage_base_dir == tmp_path


def test_fetch_projects_direct_empty(tmp_path):
    with patch("frontend.helpers.settings") as mock_settings:
        mock_settings.STORAGE_PATH = Path(tmp_path)
        projects = fetch_projects_direct()
        assert isinstance(projects, list)
