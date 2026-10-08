"""Regression tests for V2 API contracts and project summary serialization."""

from pathlib import Path
import json
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.core.config import settings
from app.api.v1.projects import manifest_manager
from app.models.schemas import (
    LocalizedVisualTrack,
    SceneVisualAsset,
    LocalizedAudioTrack,
    SceneAudioAsset,
)


@pytest.fixture
def client(tmp_path: Path, monkeypatch):
    """Create test client with isolated temporary storage directory."""
    test_storage = tmp_path / "storage"
    test_storage.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "STORAGE_PATH", test_storage)
    monkeypatch.setattr(manifest_manager, "storage_base_dir", test_storage)

    app = create_app()
    with TestClient(app) as test_client:
        yield test_client


def test_list_project_summaries_with_scene_visuals(client, tmp_path):
    """1. list_project_summaries works with visual_tracks.scene_visuals without AttributeError."""
    # Create project with visual track
    create_payload = {
        "project_id": "proj_with_visuals",
        "request": {
            "topic": "Saudi Kabsa Preparation Basics",
            "source_content": "Cooking chicken with rice and spices.",
            "base_language": "en-US",
            "target_languages": ["ar-SA"],
            "target_duration_seconds": 30,
            "video_style": "demonstration_tutorial",
            "avatar_provider": "sadtalker",
        },
    }
    res = client.post("/api/v1/projects", json=create_payload)
    assert res.status_code == 201

    # Attach a LocalizedVisualTrack using canonical scene_visuals
    manifest = manifest_manager.load_manifest("proj_with_visuals")
    test_img = tmp_path / "test_thumb.png"
    test_img.write_text("fake image")

    visual_track = LocalizedVisualTrack(
        locale="ar-SA",
        scene_visuals=[
            SceneVisualAsset(
                scene_id="scene_1",
                locale="ar-SA",
                image_path=str(test_img),
                width=1920,
                height=1080,
                visual_type="concept_slide",
                provider="local",
            )
        ],
        status="completed",
    )
    manifest.visual_tracks["ar-SA"] = visual_track
    manifest_manager.save_manifest(manifest)

    # Call /projects/summaries
    sum_res = client.get("/api/v1/projects/summaries")
    assert sum_res.status_code == 200
    summaries = sum_res.json()
    assert len(summaries) == 1
    item = summaries[0]
    assert item["project_id"] == "proj_with_visuals"
    assert item["topic"] == "Saudi Kabsa Preparation Basics"
    assert item["title"] == "Saudi Kabsa Preparation Basics"
    assert item["thumbnail_path"] == str(test_img)
    assert item["thumbnail_url"] == str(test_img)


def test_project_with_no_visual_track_still_summarizes(client):
    """2. project with no visual track still summarizes with default thumbnail."""
    create_payload = {
        "project_id": "proj_no_visuals",
        "request": {
            "topic": "Basic Cybersecurity Awareness",
            "source_content": "Password safety and MFA tips.",
            "base_language": "en-US",
            "target_languages": ["ar-SA"],
            "target_duration_seconds": 30,
        },
    }
    res = client.post("/api/v1/projects", json=create_payload)
    assert res.status_code == 201

    sum_res = client.get("/api/v1/projects/summaries")
    assert sum_res.status_code == 200
    summaries = sum_res.json()
    assert len(summaries) == 1
    assert summaries[0]["project_id"] == "proj_no_visuals"
    assert summaries[0]["thumbnail_path"] is None


def test_legacy_project_summary_does_not_crash(client, tmp_path):
    """3. legacy project summary missing V2 fields or partially corrupted does not crash catalog."""
    proj_dir = tmp_path / "storage" / "proj_legacy_test"
    proj_dir.mkdir(parents=True, exist_ok=True)
    manifest_file = proj_dir / "project.json"

    # Write a bare-bones legacy manifest dictionary
    legacy_data = {
        "project_id": "proj_legacy_test",
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
        "status": "completed",
        "source_request": {
            "topic": "Historical Training Video",
            "base_language": "en-US",
            "target_languages": ["en-US"],
            "target_duration_seconds": 45,
            # Missing V2 fields like video_style
        },
        # Empty or missing tracks
        "visual_tracks": {},
        "audio_tracks": {},
    }
    manifest_file.write_text(json.dumps(legacy_data), encoding="utf-8")

    sum_res = client.get("/api/v1/projects/summaries")
    assert sum_res.status_code == 200
    summaries = sum_res.json()
    legacy_item = next((s for s in summaries if s["project_id"] == "proj_legacy_test"), None)
    assert legacy_item is not None
    assert legacy_item["topic"] == "Historical Training Video"
    assert legacy_item["duration_seconds"] == 45.0


def test_exact_kabsa_create_payload_returns_201(client):
    """4. exact Kabsa create payload returns 201."""
    payload = {
        "project_id": None,
        "request": {
            "topic": "Saudi Kabsa Preparation Basics",
            "source_content": (
                "Saudi Kabsa is made by cooking chicken with onions, tomatoes, "
                "traditional Saudi spices, and basmati rice in the seasoned broth."
            ),
            "audience": "Beginner home cooks",
            "base_language": "en-US",
            "target_languages": ["ar-SA"],
            "target_duration_seconds": 30,
            "tone": "engaging and professional",
            "difficulty_level": "beginner",
            "learning_objectives": ["Cook rice in broth", "Brown the chicken"],
            "video_style": "demonstration_tutorial",
            "avatar_provider": "sadtalker",
        },
    }
    res = client.post("/api/v1/projects", json=payload)
    assert res.status_code == 201
    data = res.json()
    assert data["source_request"]["topic"] == "Saudi Kabsa Preparation Basics"
    assert data["source_request"]["target_languages"] == ["ar-SA"]
    assert data["source_request"]["target_duration_seconds"] == 30
    assert data["avatar_provider"] == "sadtalker"


def test_invalid_create_payload_returns_useful_422(client):
    """5. invalid create payload returns useful 422 with actionable detail."""
    # Invalid target_languages type (number instead of list)
    invalid_payload = {
        "project_id": None,
        "request": {
            "topic": "Testing Bad Types",
            "target_languages": 12345,
        },
    }
    res = client.post("/api/v1/projects", json=invalid_payload)
    assert res.status_code == 422
    err_body = res.json()
    assert "detail" in err_body
    assert isinstance(err_body["detail"], list)
    locs = [d["loc"] for d in err_body["detail"]]
    assert any("target_languages" in loc for loc in locs)


def test_flat_create_payload_rejected_with_422(client):
    """Verify backend enforces canonical request wrapper and rejects flat payloads with 422."""
    flat_payload = {
        "topic": "Flat Payload Test",
        "source_content": "Content provided at root.",
        "audience": "Staff",
        "base_language": "en-US",
        "target_languages": ["ar-SA"],
        "target_duration_seconds": 30,
        "video_style": "hybrid_presenter_broll",
        "avatar_provider": "sadtalker",
    }
    res = client.post("/api/v1/projects", json=flat_payload)
    assert res.status_code == 422
    err_body = res.json()
    assert "detail" in err_body
    locs = [d["loc"] for d in err_body["detail"]]
    assert any("request" in loc for loc in locs)
