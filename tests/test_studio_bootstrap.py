"""Regression tests for Studio Mode bootstrap orchestration and storyboard planning."""

from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.core.config import settings
from app.api.v1.projects import manifest_manager
from app.models.schemas import TrainingVideoRequest, FinalScript, SceneDraft
from tests.test_orchestrator import UnifiedMockLLMProvider, create_test_orchestrator


@pytest.fixture
def client(tmp_path: Path, monkeypatch):
    """Create test client with isolated temporary storage directory."""
    test_storage = tmp_path / "storage"
    test_storage.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "STORAGE_PATH", test_storage)
    monkeypatch.setattr(manifest_manager, "storage_base_dir", test_storage)

    mock_orch = create_test_orchestrator(tmp_path, llm=UnifiedMockLLMProvider())
    monkeypatch.setattr("app.api.v1.projects.orchestrator", mock_orch)

    app = create_app()
    with TestClient(app) as test_client:
        yield test_client


def test_prepare_studio_auto_generates_script_and_scenes(client):
    """1, 2, 3, 9, 10, 11: Studio bootstrap generates script and storyboard without running TTS, avatar, or composition."""
    create_payload = {
        "project_id": "proj_bootstrap_test",
        "request": {
            "topic": "Saudi Kabsa Preparation Basics",
            "source_content": "Cook chicken with onions, tomatoes, and rice in seasoned broth.",
            "base_language": "en-US",
            "target_languages": ["ar-SA"],
            "target_duration_seconds": 60,
            "video_style": "demonstration_tutorial",
            "avatar_provider": "sadtalker",
        },
    }
    create_res = client.post("/api/v1/projects", json=create_payload)
    assert create_res.status_code == 201
    
    # Verify initially no final_script
    initial_m = manifest_manager.load_manifest("proj_bootstrap_test")
    assert initial_m.final_script is None
    assert initial_m.script_status == "pending"

    # Call POST /api/v1/projects/{project_id}/prepare-studio
    prep_res = client.post("/api/v1/projects/proj_bootstrap_test/prepare-studio")
    assert prep_res.status_code == 200
    prep_data = prep_res.json()

    # 1. Final script generated and persisted
    assert prep_data["script_status"] == "completed"
    assert prep_data["final_script"] is not None
    scenes = prep_data["final_script"]["scenes"]
    assert len(scenes) > 0

    # 2. scripts/source.json was created on disk
    source_json = manifest_manager.get_project_dir("proj_bootstrap_test") / "scripts" / "source.json"
    assert source_json.exists()

    # 3. GET /projects/{id}/scenes returns scenes > 0
    scenes_res = client.get("/api/v1/projects/proj_bootstrap_test/scenes")
    assert scenes_res.status_code == 200
    assert len(scenes_res.json()) == len(scenes)

    # 9, 10, 11. Strictly did NOT execute TTS, avatar, or final composition
    assert prep_data["audio_status"] in ("pending", None)
    assert prep_data["audio_tracks"] == {}
    assert prep_data["avatar_status"] in ("pending", None)
    assert prep_data["avatar_tracks"] == {}
    assert prep_data["composition_status"] in ("pending", None)
    assert prep_data["final_videos"] == {}


def test_plan_storyboard_distinguishes_errors_and_auto_generates(client):
    """5 & 1: Distinguish PROJECT_NOT_FOUND from FINAL_SCRIPT_MISSING, and auto-generate script if enabled."""
    # 5. Non-existent project returns 404 with code PROJECT_NOT_FOUND
    res_404 = client.post("/api/v1/projects/non_existent_project/plan-storyboard")
    assert res_404.status_code == 404
    detail_404 = res_404.json()["detail"]
    assert detail_404["code"] == "PROJECT_NOT_FOUND"

    # Create project without script
    client.post(
        "/api/v1/projects",
        json={
            "project_id": "proj_no_script_yet",
            "request": {
                "topic": "Coffee Brewing Mastery",
                "source_content": "Grind beans and pour hot water over them.",
                "target_duration_seconds": 60,
            },
        },
    )

    # Calling plan-storyboard with auto_generate_script=false returns 400 with FINAL_SCRIPT_MISSING
    res_missing = client.post(
        "/api/v1/projects/proj_no_script_yet/plan-storyboard?auto_generate_script=false"
    )
    assert res_missing.status_code == 400
    detail_missing = res_missing.json()["detail"]
    assert detail_missing["code"] == "FINAL_SCRIPT_MISSING"

    # Calling default plan-storyboard auto-generates script and succeeds with 200
    res_auto = client.post("/api/v1/projects/proj_no_script_yet/plan-storyboard")
    assert res_auto.status_code == 200
    auto_data = res_auto.json()
    assert auto_data["final_script"] is not None
    assert len(auto_data["final_script"]["scenes"]) > 0


def test_generate_script_endpoint(client):
    """2. generate-script endpoint produces and persists final_script without planning media."""
    client.post(
        "/api/v1/projects",
        json={
            "project_id": "proj_script_only",
            "request": {
                "topic": "Workplace Safety Protocols",
                "source_content": "Wear helmets, check equipment, report hazards immediately.",
                "target_duration_seconds": 60,
            },
        },
    )

    res = client.post("/api/v1/projects/proj_script_only/generate-script")
    assert res.status_code == 200
    data = res.json()
    assert data["script_status"] == "completed"
    assert data["final_script"] is not None
    assert len(data["final_script"]["scenes"]) > 0


def test_kabsa_demonstration_storyboard_scenes_avoid_generic_cards(client):
    """11. Verify Kabsa demonstration scenes are planned with broll/media_full and presenter."""
    from app.workflows.storyboard_planner import StoryboardPlanner
    from app.models.schemas import ScriptDraft, SceneDraft, SceneMediaType, SceneLayoutType, VideoStyle

    # 1. Test StoryboardPlanner directly on 4-scene Kabsa tutorial script
    kabsa_script = ScriptDraft(
        title="Saudi Kabsa Preparation Basics",
        language="en-US",
        audience="Beginner home cooks",
        opening_hook="Welcome to traditional Saudi culinary arts.",
        scenes=[
            SceneDraft(
                scene_id="s1",
                order=1,
                title="Introduction",
                purpose="Welcome viewers to Saudi Kabsa",
                narration="Welcome to our Saudi Kabsa tutorial.",
                estimated_duration_seconds=5,
                scene_type="presenter",
            ),
            SceneDraft(
                scene_id="s2",
                order=2,
                title="Chicken Searing with Spices",
                purpose="Cook chicken with onions, tomatoes and spices",
                narration="Sear the chicken pieces with sliced onions and aromatic spices.",
                estimated_duration_seconds=10,
                scene_type="demonstration",
            ),
            SceneDraft(
                scene_id="s3",
                order=3,
                title="Simmering Basmati Rice",
                purpose="Add rice to seasoned broth",
                narration="Pour the seasoned broth and basmati rice into the pot to simmer.",
                estimated_duration_seconds=10,
                scene_type="demonstration",
            ),
            SceneDraft(
                scene_id="s4",
                order=4,
                title="Conclusion & Serving",
                purpose="Serve authentic Kabsa dish",
                narration="Serve hot garnished with toasted almonds and raisins.",
                estimated_duration_seconds=5,
                scene_type="outro",
            ),
        ],
        closing_summary="Enjoy your authentic Saudi Kabsa.",
        total_estimated_duration_seconds=30,
    )

    planned = StoryboardPlanner.plan_storyboard(
        kabsa_script,
        "Saudi Kabsa Preparation Basics",
        video_style=VideoStyle.DEMONSTRATION_TUTORIAL.value,
    )

    # First scene is presenter introduction
    assert planned.scenes[0].media_type == SceneMediaType.PRESENTER.value
    assert planned.scenes[0].avatar_enabled is True

    # Demonstration body scenes are cinematic B-roll / media_full
    assert planned.scenes[1].media_type == SceneMediaType.BROLL.value
    assert planned.scenes[1].layout_type == SceneLayoutType.MEDIA_FULL.value
    assert planned.scenes[1].avatar_enabled is False

    assert planned.scenes[2].media_type == SceneMediaType.BROLL.value
    assert planned.scenes[2].layout_type == SceneLayoutType.MEDIA_FULL.value
    assert planned.scenes[2].avatar_enabled is False

    # Outro is presenter
    assert planned.scenes[3].media_type == SceneMediaType.OUTRO.value
    assert planned.scenes[3].avatar_enabled is True

    # 2. Test via API endpoint
    client.post(
        "/api/v1/projects",
        json={
            "project_id": "proj_kabsa_storyboard",
            "request": {
                "topic": "Saudi Kabsa Preparation Basics",
                "source_content": "Saudi Kabsa is made by cooking chicken with onions, tomatoes, traditional Saudi spices, and basmati rice in the seasoned broth.",
                "target_duration_seconds": 60,
                "video_style": "demonstration_tutorial",
            },
        },
    )

    res = client.post("/api/v1/projects/proj_kabsa_storyboard/prepare-studio")
    assert res.status_code == 200
    scenes = res.json()["final_script"]["scenes"]
    assert len(scenes) > 0


def test_quick_generate_still_executes_complete_pipeline(client):
    """12. Quick Generate (/run) still executes the full multi-stage pipeline."""
    client.post(
        "/api/v1/projects",
        json={
            "project_id": "proj_quick_gen",
            "request": {
                "topic": "Quick Pipeline Test",
                "target_languages": ["ar-SA"],
                "target_duration_seconds": 60,
            },
        },
    )

    run_res = client.post("/api/v1/projects/proj_quick_gen/run", json={"force_regenerate": False})
    assert run_res.status_code == 200
    data = run_res.json()
    assert data["status"] == "completed"
    assert data["script_status"] == "completed"
    assert data["composition_status"] == "completed"
    assert "ar-SA" in data["final_videos"]
