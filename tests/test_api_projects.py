"""Comprehensive integration tests for FastAPI project endpoints."""

from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.core.config import settings
from app.api.v1.projects import manifest_manager, orchestrator
from tests.test_orchestrator import UnifiedMockLLMProvider, create_test_orchestrator


@pytest.fixture
def client(tmp_path: Path, monkeypatch):
    """Create test client with isolated temporary storage directory."""
    test_storage = tmp_path / "storage"
    monkeypatch.setattr(settings, "STORAGE_PATH", test_storage)
    monkeypatch.setattr(manifest_manager, "storage_base_dir", test_storage)

    # Configure orchestrator with mock providers for fast, safe API testing
    mock_orch = create_test_orchestrator(tmp_path, llm=UnifiedMockLLMProvider())
    monkeypatch.setattr("app.api.v1.projects.orchestrator", mock_orch)

    app = create_app()
    with TestClient(app) as test_client:
        yield test_client


def test_create_project_success(client):
    """Verify POST /api/v1/projects creates a new project manifest."""
    payload = {
        "project_id": "proj_api_1",
        "request": {
            "topic": "Workplace Phishing Defense",
            "audience": "Employees",
            "base_language": "en-US",
            "target_languages": ["ar-SA"],
            "target_duration_seconds": 60,
        },
    }
    response = client.post("/api/v1/projects", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["project_id"] == "proj_api_1"
    assert data["status"] == "pending"
    assert data["source_request"]["topic"] == "Workplace Phishing Defense"


def test_create_project_auto_generated_id(client):
    """Verify POST /api/v1/projects auto-generates project ID when omitted."""
    payload = {
        "request": {
            "topic": "Data Protection Basics",
            "base_language": "en-US",
            "target_languages": ["en-US"],
        }
    }
    response = client.post("/api/v1/projects", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["project_id"].startswith("proj_")


def test_create_project_duplicate_conflict(client):
    """Verify POST /api/v1/projects returns 409 Conflict if project ID already exists."""
    payload = {
        "project_id": "proj_duplicate",
        "request": {
            "topic": "Topic A",
            "base_language": "en-US",
        },
    }
    res1 = client.post("/api/v1/projects", json=payload)
    assert res1.status_code == 201

    res2 = client.post("/api/v1/projects", json=payload)
    assert res2.status_code == 409
    assert "already exists" in res2.json()["detail"]


def test_create_project_validation_error(client):
    """Verify POST /api/v1/projects returns 422 if neither topic nor source_content is provided."""
    payload = {
        "request": {
            "audience": "Employees",
        }
    }
    response = client.post("/api/v1/projects", json=payload)
    assert response.status_code == 422


def test_list_and_get_project(client):
    """Verify GET /api/v1/projects and GET /api/v1/projects/{id}."""
    client.post(
        "/api/v1/projects",
        json={"project_id": "proj_list_1", "request": {"topic": "Topic 1"}},
    )
    client.post(
        "/api/v1/projects",
        json={"project_id": "proj_list_2", "request": {"topic": "Topic 2"}},
    )

    # List
    list_res = client.get("/api/v1/projects")
    assert list_res.status_code == 200
    projects = list_res.json()
    assert len(projects) >= 2
    ids = [p["project_id"] for p in projects]
    assert "proj_list_1" in ids
    assert "proj_list_2" in ids

    # Get Single
    get_res = client.get("/api/v1/projects/proj_list_1")
    assert get_res.status_code == 200
    assert get_res.json()["project_id"] == "proj_list_1"

    # Get Non-existent
    not_found_res = client.get("/api/v1/projects/non_existent_id")
    assert not_found_res.status_code == 404


def test_run_project_lifecycle(client):
    """Verify POST /api/v1/projects/{id}/run executes pipeline end-to-end."""
    # Create
    create_res = client.post(
        "/api/v1/projects",
        json={
            "project_id": "proj_run_test",
            "request": {
                "topic": "Incident Response",
                "audience": "All",
                "base_language": "en-US",
                "target_languages": ["ar-SA"],
                "target_duration_seconds": 60,
            },
        },
    )
    assert create_res.status_code == 201

    # Run
    run_res = client.post("/api/v1/projects/proj_run_test/run", json={"force_regenerate": False})
    assert run_res.status_code == 200
    data = run_res.json()
    assert data["status"] == "completed"
    assert data["script_status"] == "completed"
    assert data["composition_status"] == "completed"
    assert "ar-SA" in data["final_videos"]


def test_resume_project_lifecycle(client):
    """Verify POST /api/v1/projects/{id}/resume executes pipeline resume."""
    client.post(
        "/api/v1/projects",
        json={
            "project_id": "proj_resume_test",
            "request": {
                "topic": "Security Guidelines",
                "target_duration_seconds": 60,
            },
        },
    )
    resume_res = client.post("/api/v1/projects/proj_resume_test/resume")
    assert resume_res.status_code == 200
    assert resume_res.json()["status"] == "completed"


def test_get_project_outputs(client):
    """Verify GET /api/v1/projects/{id}/outputs returns structured output summary."""
    client.post(
        "/api/v1/projects",
        json={
            "project_id": "proj_out_test",
            "request": {
                "topic": "Compliance Policy",
                "target_languages": ["ar-SA"],
                "target_duration_seconds": 60,
            },
        },
    )
    client.post("/api/v1/projects/proj_out_test/run")

    out_res = client.get("/api/v1/projects/proj_out_test/outputs")
    assert out_res.status_code == 200
    data = out_res.json()
    assert data["project_id"] == "proj_out_test"
    assert data["status"] == "completed"
    assert data["has_final_script"] is True
    assert "ar-SA" in data["locales"]
    assert "ar-SA" in data["final_videos"]


def test_endpoints_404_on_missing_project(client):
    """Verify 404 responses for run, resume, outputs on unknown project IDs."""
    assert client.post("/api/v1/projects/missing_id/run").status_code == 404
    assert client.post("/api/v1/projects/missing_id/resume").status_code == 404
    assert client.get("/api/v1/projects/missing_id/outputs").status_code == 404


def test_create_project_streamlit_serialized_payload_accepted(client):
    """Verify exact payload produced by Streamlit UI is accepted by POST /api/v1/projects.
    
    Covers:
    - en-US -> ar-SA
    - one target locale (ar-SA)
    - multiple learning objectives
    - optional source_content
    - difficulty_level
    - target duration
    - frontend serialization field names
    """
    from frontend.helpers import serialize_create_project_payload

    payload = serialize_create_project_payload(
        topic="Enterprise Phishing Defense",
        source_content="Detailed employee training on recognizing spear-phishing emails.",
        audience="Corporate Employees",
        base_language="en-US",
        target_languages=["ar-SA"],
        target_duration_seconds=75,
        tone="engaging and professional",
        difficulty_level="beginner",
        learning_objectives=[
            "Identify suspicious sender domains",
            "Report unexpected link clicks",
            "Verify urgent requests via secondary channels",
        ],
        locale=None,
    )

    response = client.post("/api/v1/projects", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["status"] == "pending"
    assert data["project_id"].startswith("proj_")

    src = data["source_request"]
    assert src["topic"] == "Enterprise Phishing Defense"
    assert src["source_content"] == "Detailed employee training on recognizing spear-phishing emails."
    assert src["base_language"] == "en-US"
    assert src["target_languages"] == ["ar-SA"]
    assert src["target_duration_seconds"] == 75
    assert src["tone"] == "engaging and professional"
    assert src["difficulty_level"] == "beginner"
    assert len(src["learning_objectives"]) == 3
    assert src["learning_objectives"][0] == "Identify suspicious sender domains"


def test_create_project_streamlit_payload_optional_source_content(client):
    """Verify Streamlit serialized payload with empty/None source_content is accepted."""
    from frontend.helpers import serialize_create_project_payload

    payload = serialize_create_project_payload(
        topic="Quick Security Brief",
        source_content="",  # empty in UI
        audience="General Staff",
        base_language="en-US",
        target_languages=["ar-SA"],
        target_duration_seconds=60,
        tone="conversational",
        difficulty_level="intermediate",
        learning_objectives=["Stay alert for phishing"],
    )

    response = client.post("/api/v1/projects", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["source_request"]["source_content"] is None
    assert data["source_request"]["topic"] == "Quick Security Brief"


def test_create_project_rejects_unwrapped_flat_payload_with_422(client):
    """Regression test: verify old flat Streamlit payload returns 422 with missing request field."""
    old_unwrapped_payload = {
        "topic": "Cloud Security Training",
        "source_content": None,
        "audience": "Engineers",
        "base_language": "en-US",
        "target_locales": ["ar-SA"],
        "target_duration_seconds": 60,
        "tone": "professional",
        "difficulty": "beginner",
        "learning_objectives": ["Understand IAM", "Apply least privilege"],
    }
    response = client.post("/api/v1/projects", json=old_unwrapped_payload)
    assert response.status_code == 422
    errors = response.json()["detail"]
    assert any("request" in err["loc"] and err["type"] == "missing" for err in errors)


def test_generate_script_endpoint_success(client):
    """Verify POST /api/v1/projects/{id}/generate-script succeeds and returns HTTP 200 with final script."""
    # Create project first
    payload = {
        "project_id": "proj_gen_script_test",
        "request": {
            "topic": "Workplace Phishing Defense Essentials",
            "source_content": "Identify phishing emails, verify sender domains, and report attacks.",
            "audience": "Employees",
            "base_language": "en-US",
            "target_languages": ["ar-SA"],
            "target_duration_seconds": 60,
            "learning_objectives": [
                "Identify spoofed domains",
                "Report suspicious emails",
            ],
        },
    }
    c_res = client.post("/api/v1/projects", json=payload)
    assert c_res.status_code == 201

    # Call generate-script endpoint
    gen_res = client.post("/api/v1/projects/proj_gen_script_test/generate-script?force_regenerate=false")
    assert gen_res.status_code == 200
    manifest = gen_res.json()
    assert manifest["project_id"] == "proj_gen_script_test"
    assert manifest["script_status"] == "completed"
    assert manifest["final_script"] is not None
    assert len(manifest["final_script"]["scenes"]) > 0


def test_generate_script_404_on_unknown_project(client):
    """Verify POST /api/v1/projects/{id}/generate-script returns 404 for unknown project."""
    res = client.post("/api/v1/projects/proj_nonexistent_999/generate-script")
    assert res.status_code == 404
    data = res.json()
    assert data["detail"]["code"] == "PROJECT_NOT_FOUND"


def test_prepare_studio_endpoint_success(client):
    """Verify POST /api/v1/projects/{id}/prepare-studio bootstraps script and storyboard."""
    payload = {
        "project_id": "proj_studio_prep_test",
        "request": {
            "topic": "Workplace Phishing Defense Essentials",
            "source_content": "Identify phishing emails, verify sender domains, and report attacks.",
            "audience": "Facility Personnel",
            "base_language": "en-US",
            "target_languages": ["ar-SA"],
            "target_duration_seconds": 60,
            "learning_objectives": [
                "Identify spoofed domains",
                "Report suspicious emails",
            ],
        },
    }
    client.post("/api/v1/projects", json=payload)

    prep_res = client.post("/api/v1/projects/proj_studio_prep_test/prepare-studio")
    assert prep_res.status_code == 200
    manifest = prep_res.json()
    assert manifest["script_status"] == "completed"
    assert manifest["final_script"] is not None
    assert len(manifest["final_script"]["scenes"]) == 2


