"""Tests for V2 Render Action, storyboard reuse, and pre-render asset metadata."""

import pytest
from pathlib import Path
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock

from app.main import create_app
from app.models.schemas import (
    ProjectManifest,
    TrainingVideoRequest,
    ScriptDraft,
    FinalScript,
    SceneDraft,
    LearningObjective,
    FinalVideoAsset,
    SceneCompositionAsset,
)
from app.workflows.manifest import ProjectManifestManager
from app.workflows.orchestrator import ProjectOrchestrator


@pytest.fixture
def client():
    app = create_app()
    return TestClient(app)


def test_unrendered_scene_asset_state(client, tmp_path, monkeypatch):
    """Test 1 & 7: Unrendered scenes expose render_status='unrendered', has_rendered_asset=False, rendered_video_url=None."""
    mgr = ProjectManifestManager(storage_base_dir=tmp_path)
    monkeypatch.setattr("app.api.v1.projects.manifest_manager", mgr)

    project_id = "proj_test_unrendered"
    req = TrainingVideoRequest(
        topic="Test Unrendered Topic",
        base_language="en-US",
        target_languages=["ar-SA"],
        target_duration_seconds=30,
    )
    manifest = mgr.create_manifest(project_id, req)
    manifest.final_script = FinalScript(
        title="Test Unrendered Script",
        language="en-US",
        audience="General",
        target_duration_seconds=30,
        total_estimated_duration_seconds=30,
        opening_hook="Hook",
        closing_summary="Summary",
        scenes=[
            SceneDraft(
                scene_id="scene_1",
                order=1,
                title="Scene 1",
                narration="Narration 1",
                estimated_duration_seconds=15,
                media_type="presenter",
                layout_type="presenter_full",
                avatar_enabled=True,
            ),
            SceneDraft(
                scene_id="scene_2",
                order=2,
                title="Scene 2",
                narration="Narration 2",
                estimated_duration_seconds=15,
                media_type="broll",
                layout_type="media_full",
                avatar_enabled=False,
            ),
        ],
    )
    manifest.script_status = "completed"
    mgr.save_manifest(manifest)

    # Fetch scenes via API
    res = client.get(f"/api/v1/projects/{project_id}/scenes?locale=ar-SA")
    assert res.status_code == 200
    scenes = res.json()
    assert len(scenes) == 2

    # Verify scene 1 & 2 are unrendered and expose no video URL before render
    for s in scenes:
        assert s["render_status"] == "unrendered"
        assert s["has_rendered_asset"] is False
        assert s["rendered_video_url"] is None


def test_completed_scene_exposes_rendered_video_url(client, tmp_path, monkeypatch):
    """Test 7 & 8: Completed scene exposes rendered_video_url and has_rendered_asset=True."""
    mgr = ProjectManifestManager(storage_base_dir=tmp_path)
    monkeypatch.setattr("app.api.v1.projects.manifest_manager", mgr)

    project_id = "proj_test_rendered"
    req = TrainingVideoRequest(
        topic="Test Rendered Topic",
        base_language="en-US",
        target_languages=["ar-SA"],
        target_duration_seconds=30,
    )
    manifest = mgr.create_manifest(project_id, req)
    manifest.final_script = FinalScript(
        title="Test Rendered Script",
        language="en-US",
        audience="General",
        target_duration_seconds=30,
        total_estimated_duration_seconds=30,
        opening_hook="Hook",
        closing_summary="Summary",
        scenes=[
            SceneDraft(
                scene_id="scene_1",
                order=1,
                title="Scene 1",
                narration="Narration 1",
                estimated_duration_seconds=15,
                media_type="presenter",
                layout_type="presenter_full",
                avatar_enabled=True,
            ),
        ],
    )
    manifest.script_status = "completed"

    # Simulate completed rendered file on disk
    rendered_dir = tmp_path / project_id / "rendered" / "ar-SA"
    rendered_dir.mkdir(parents=True, exist_ok=True)
    sc1_mp4 = rendered_dir / "scene_1.mp4"
    sc1_mp4.write_bytes(b"dummy mp4 video bytes")

    # Add FinalVideoAsset to manifest
    manifest.final_videos["ar-SA"] = FinalVideoAsset(
        locale="ar-SA",
        video_path=str((tmp_path / project_id / "final" / "training_ar-SA.mp4").resolve()),
        total_duration_seconds=15.0,
        scene_count=1,
        scene_videos=[
            SceneCompositionAsset(
                scene_id="scene_1",
                locale="ar-SA",
                video_path=str(sc1_mp4.resolve()),
                duration_seconds=15.0,
                status="completed",
            )
        ],
        status="completed",
    )
    manifest.composition_status = "completed"
    mgr.save_manifest(manifest)

    # Fetch scenes
    res = client.get(f"/api/v1/projects/{project_id}/scenes?locale=ar-SA")
    assert res.status_code == 200
    scenes = res.json()
    assert len(scenes) == 1
    sc = scenes[0]
    assert sc["render_status"] == "completed"
    assert sc["has_rendered_asset"] is True
    assert sc["rendered_video_url"] == f"/storage/{project_id}/rendered/ar-SA/scene_1.mp4"


def test_render_endpoint_exists_and_calls_orchestrator(client, tmp_path, monkeypatch):
    """Test 3: POST /api/v1/projects/{project_id}/render triggers orchestrator."""
    mgr = ProjectManifestManager(storage_base_dir=tmp_path)
    orch = ProjectOrchestrator(manifest_manager=mgr)
    monkeypatch.setattr("app.api.v1.projects.manifest_manager", mgr)
    monkeypatch.setattr("app.api.v1.projects.orchestrator", orch)

    project_id = "proj_test_render_api"
    req = TrainingVideoRequest(
        topic="Test Render API",
        base_language="en-US",
        target_languages=["ar-SA"],
        target_duration_seconds=30,
    )
    mgr.create_manifest(project_id, req)

    with patch.object(orch, "run_project") as mock_run:
        mock_manifest = mgr.load_manifest(project_id)
        mock_manifest.status = "completed"
        mock_run.return_value = mock_manifest

        res = client.post(f"/api/v1/projects/{project_id}/render", json={"force_regenerate": False})
        assert res.status_code == 200
        mock_run.assert_called_once_with(
            project_id=project_id,
            request=mock_manifest.source_request,
            force_regenerate=False,
        )


def test_storyboard_is_reused_during_run_project(tmp_path):
    """Test 4: Approved storyboard is reused and not overwritten during run_project."""
    mgr = ProjectManifestManager(storage_base_dir=tmp_path)
    orch = ProjectOrchestrator(manifest_manager=mgr)

    project_id = "proj_test_reuse_storyboard"
    req = TrainingVideoRequest(
        topic="Saudi Kabsa Preparation Basics",
        base_language="en-US",
        target_languages=["ar-SA"],
        target_duration_seconds=30,
        video_style="demonstration_tutorial",
    )
    manifest = mgr.create_manifest(project_id, req)
    # Pre-plan custom scenes
    manifest.final_script = FinalScript(
        title="Custom Approved Kabsa",
        language="en-US",
        audience="Trainees",
        target_duration_seconds=30,
        total_estimated_duration_seconds=30,
        opening_hook="Hook",
        closing_summary="Summary",
        scenes=[
            SceneDraft(
                scene_id="scene_1",
                order=1,
                title="Custom Approved Intro",
                narration="Welcome to our special kitchen.",
                estimated_duration_seconds=15,
                media_type="presenter",
                layout_type="presenter_split",
                avatar_enabled=True,
                visual_prompt="CUSTOM_APPROVED_PROMPT_1",
            ),
            SceneDraft(
                scene_id="scene_2",
                order=2,
                title="Custom Approved B-roll",
                narration="Watch the chicken simmer.",
                estimated_duration_seconds=15,
                media_type="broll",
                layout_type="media_full",
                avatar_enabled=False,
                visual_prompt="CUSTOM_APPROVED_PROMPT_2",
            ),
        ],
    )
    manifest.script_status = "completed"
    mgr.save_manifest(manifest)

    from app.models.schemas import LocalizationBundle

    with patch("app.workflows.orchestrator.StoryboardPlanner.plan_storyboard") as mock_plan:
        with patch.object(orch.localization_service, "localize_bundle") as mock_loc:
            mock_bundle = LocalizationBundle(
                source_script=manifest.final_script,
                localized_scripts={},
                failed_locales={},
            )
            mock_loc.return_value = mock_bundle

            orch.run_project(project_id=project_id, force_regenerate=False)
            # StoryboardPlanner.plan_storyboard must NOT have been called because storyboard is already approved
            mock_plan.assert_not_called()

    # Verify visual prompts were preserved
    loaded = mgr.load_manifest(project_id)
    assert loaded.final_script.scenes[0].visual_prompt == "CUSTOM_APPROVED_PROMPT_1"
    assert loaded.final_script.scenes[1].visual_prompt == "CUSTOM_APPROVED_PROMPT_2"


def test_failed_render_surfaces_error(client, tmp_path, monkeypatch):
    """Test 9: Failed render surfaces exact error and does not report completed."""
    mgr = ProjectManifestManager(storage_base_dir=tmp_path)
    orch = ProjectOrchestrator(manifest_manager=mgr)
    monkeypatch.setattr("app.api.v1.projects.manifest_manager", mgr)
    monkeypatch.setattr("app.api.v1.projects.orchestrator", orch)

    project_id = "proj_test_fail_render"
    req = TrainingVideoRequest(
        topic="Failing Pipeline",
        base_language="en-US",
        target_languages=["ar-SA"],
        target_duration_seconds=30,
    )
    mgr.create_manifest(project_id, req)

    with patch.object(orch, "run_project", side_effect=RuntimeError("FFmpeg encoding failed: invalid audio stream")):
        res = client.post(f"/api/v1/projects/{project_id}/render", json={"force_regenerate": False})
        assert res.status_code == 500
        data = res.json()
        assert "FFmpeg encoding failed: invalid audio stream" in data["detail"]


def test_presenter_scene_invokes_sadtalker(tmp_path):
    """Test 5: Presenter scene invokes SadTalker provider when avatar_provider is sadtalker."""
    mgr = ProjectManifestManager(storage_base_dir=tmp_path)
    orch = ProjectOrchestrator(manifest_manager=mgr)

    project_id = "proj_test_sadtalker_invoked"
    req = TrainingVideoRequest(
        topic="SadTalker Presenter Scene Test",
        base_language="en-US",
        target_languages=["ar-SA"],
        target_duration_seconds=15,
        avatar_provider="sadtalker",
    )
    manifest = mgr.create_manifest(project_id, req)
    manifest.final_script = FinalScript(
        title="SadTalker Presenter",
        language="en-US",
        audience="General",
        target_duration_seconds=30,
        total_estimated_duration_seconds=30,
        opening_hook="Hook",
        closing_summary="Summary",
        scenes=[
            SceneDraft(
                scene_id="scene_1",
                order=1,
                title="Scene 1",
                narration="Welcome to our lesson.",
                estimated_duration_seconds=15,
                media_type="presenter",
                layout_type="presenter_full",
                avatar_enabled=True,
            ),
        ],
    )
    manifest.script_status = "completed"
    manifest.localization_status = "completed"
    from app.models.schemas import LocalizationBundle, LocalizedScript, LocalizedScene, LocalizedAudioTrack, SceneAudioAsset
    loc_scene = LocalizedScene(
        scene_id="scene_1",
        order=1,
        title="Scene 1",
        narration="أهلا بكم",
        estimated_duration_seconds=15,
        media_type="presenter",
        layout_type="presenter_full",
        avatar_enabled=True,
    )
    loc_script = LocalizedScript(
        locale="ar-SA",
        source_language="en-US",
        language="ar-SA",
        title="SadTalker Presenter Ar",
        audience="General",
        opening_hook="Hook",
        closing_summary="Summary",
        target_duration_seconds=15,
        scenes=[loc_scene],
    )
    manifest.localization_bundle = LocalizationBundle(
        source_script=manifest.final_script,
        localized_scripts={"ar-SA": loc_script},
    )
    audio_file = tmp_path / project_id / "audio" / "ar-SA" / "scene_1.mp3"
    audio_file.parent.mkdir(parents=True, exist_ok=True)
    audio_file.write_bytes(b"dummy audio")
    manifest.audio_tracks = {
        "ar-SA": LocalizedAudioTrack(
            locale="ar-SA",
            total_audio_duration_seconds=15.0,
            status="completed",
            scene_audio=[
                SceneAudioAsset(
                    scene_id="scene_1",
                    locale="ar-SA",
                    audio_path=str(audio_file),
                    duration_seconds=15.0,
                    provider="edge_tts",
                    voice_id="ar-SA-HamedNeural",
                    status="completed",
                )
            ],
        )
    }
    manifest.audio_status = "completed"
    manifest.metadata = {"duration_reconciliation": {"ar-SA": {"is_approved": True}}}
    mgr.save_manifest(manifest)

    with patch.object(orch.avatar_service, "generate_bundle_avatars") as mock_av:
        from app.models.schemas import LocalizedAvatarTrack
        mock_av.return_value = {
            "ar-SA": LocalizedAvatarTrack(
                locale="ar-SA",
                video_path="",
                total_duration_seconds=15.0,
                status="completed",
                scenes=[],
                metadata={"provider": "sadtalker"},
            )
        }
        with patch.object(orch.visual_service, "generate_bundle_visuals", return_value={}):
            with patch.object(orch.subtitle_service, "generate_bundle_subtitles", return_value={}):
                with patch.object(orch.composition_service, "compose_bundle_videos", return_value={}):
                    orch.run_project(project_id=project_id, force_regenerate=False)

        mock_av.assert_called_once()
        assert orch.avatar_service.provider.provider_name == "sadtalker"


def test_broll_scene_invokes_local_media_motion_provider(tmp_path):
    """Test 6: B-roll scene invokes local media motion provider."""
    from app.services.composition.service import CompositionService
    from app.models.schemas import LocalizedScript, LocalizedScene, LocalizedAudioTrack, SceneAudioAsset

    comp_service = CompositionService(output_base_dir=tmp_path)
    project_id = "proj_test_broll_motion"

    scene = LocalizedScene(
        scene_id="scene_2",
        order=2,
        title="Cooking Chicken",
        narration="Cook the chicken slowly.",
        estimated_duration_seconds=10.0,
        media_type="broll",
        layout_type="media_full",
        avatar_enabled=False,
    )
    script = LocalizedScript(
        locale="ar-SA",
        source_language="en-US",
        language="ar-SA",
        title="Kabsa Broll",
        audience="General",
        opening_hook="Hook",
        closing_summary="Summary",
        target_duration_seconds=10,
        scenes=[scene],
    )
    audio_file = tmp_path / project_id / "audio" / "ar-SA" / "scene_2.mp3"
    audio_file.parent.mkdir(parents=True, exist_ok=True)
    audio_file.write_bytes(b"dummy audio")
    audio_track = LocalizedAudioTrack(
        locale="ar-SA",
        total_audio_duration_seconds=10.0,
        status="completed",
        scene_audio=[
            SceneAudioAsset(
                scene_id="scene_2",
                locale="ar-SA",
                audio_path=str(audio_file),
                duration_seconds=10.0,
                provider="edge_tts",
                voice_id="ar-SA-HamedNeural",
                status="completed",
            )
        ],
    )

    with patch.object(comp_service.media_service, "generate_scene_media") as mock_media:
        mock_media.return_value = tmp_path / "dummy_motion.mp4"
        with patch.object(comp_service.provider, "compose_scene") as mock_compose:
            from app.models.schemas import SceneCompositionAsset
            mock_compose.return_value = SceneCompositionAsset(
                scene_id="scene_2",
                locale="ar-SA",
                video_path=str(tmp_path / "dummy_scene_2.mp4"),
                duration_seconds=10.0,
                status="completed",
            )

            comp_service.compose_locale_scenes(
                script=script,
                audio_track=audio_track,
                project_id=project_id,
            )

            mock_media.assert_called_once()
            call_kwargs = mock_media.call_args.kwargs
            assert call_kwargs["scene"].scene_id == "scene_2"
            assert call_kwargs["scene"].media_type == "broll"
            assert call_kwargs["duration_seconds"] == 10.0
