"""Regression tests for rendering pipeline resilience and zero-division prevention.

Verifies:
1. Normal scene rendering.
2. Zero or missing audio duration.
3. Invalid scene duration.
4. Missing media assets.
5. Empty frame count or invalid FPS.
6. Progress calculations with zero denominators.
7. Full rendering workflow with 4 scenes, 30s target configuration.
"""

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.core.config import settings
from app.models.schemas import (
    FinalScript,
    SceneDraft,
    LocalizedScript,
    LocalizationBundle,
    LocalizedScene,
    LearningObjective,
    LocalizedAudioTrack,
    SceneAudioAsset,
    LocalizedVisualTrack,
    SceneVisualAsset,
    SceneCompositionAsset,
    FinalVideoAsset,
    ProjectManifest,
    TrainingVideoRequest,
)
from app.services.duration.reconciliation import (
    DurationReconciliationService,
    allocate_scene_duration_budgets,
    build_duration_condensation_prompt,
)
from app.services.localization.prompts import build_post_tts_duration_revision_prompt
from app.services.composition.service import CompositionService
from app.services.composition.ffmpeg_provider import FFmpegCompositionProvider
from app.services.media.motion_visual_provider import LocalMotionVisualProvider
from app.services.subtitles.formatter import split_narration_into_chunks
from app.core.language import detect_primary_script
from app.workflows.manifest import ProjectManifestManager
from app.workflows.orchestrator import ProjectOrchestrator


@pytest.fixture
def four_scene_30s_script() -> LocalizedScript:
    """Fixture providing a 4-scene, 30-second localized script matching user configuration."""
    return LocalizedScript(
        locale="en-US",
        source_language="en-US",
        language="English",
        title="Workplace Phishing Defense Essentials",
        audience="Corporate Employees & Staff",
        opening_hook="Can you spot a dangerous threat in your inbox before clicking?",
        closing_summary="Remember: recognize cues, verify senders, handle attachments safely, and report threats promptly.",
        target_duration_seconds=30,
        total_estimated_duration_seconds=30,
        learning_objectives=[
            LearningObjective(id="LO1", description="Recognize email indicators"),
            LearningObjective(id="LO2", description="Inspect sender domain"),
            LearningObjective(id="LO3", description="Avoid suspicious attachments"),
            LearningObjective(id="LO4", description="Report threat to security"),
        ],
        scenes=[
            LocalizedScene(
                scene_id="scene_1",
                order=1,
                title="Introduction to Phishing",
                purpose="Intro",
                narration="Phishing emails often impersonate trusted brands or colleagues to steal credentials.",
                estimated_duration_seconds=7,
                scene_type="intro",
                media_type="motion_visual",
                layout_type="presenter_split",
                avatar_enabled=True,
                presenter_position="right",
                learning_objective_ids=["LO1"],
            ),
            LocalizedScene(
                scene_id="scene_2",
                order=2,
                title="Checking Sender Addresses",
                purpose="Core Concept",
                narration="Always inspect the sender address closely. Attackers use lookalike domains to deceive you.",
                estimated_duration_seconds=8,
                scene_type="core_concept",
                media_type="motion_visual",
                layout_type="presenter_split",
                avatar_enabled=True,
                presenter_position="right",
                learning_objective_ids=["LO2"],
            ),
            LocalizedScene(
                scene_id="scene_3",
                order=3,
                title="Attachments and Links Caution",
                purpose="Practical Step",
                narration="Never open unexpected attachments or click urgent links without verifying with the sender.",
                estimated_duration_seconds=8,
                scene_type="practical_step",
                media_type="broll",
                layout_type="media_full",
                avatar_enabled=False,
                presenter_position="center",
                learning_objective_ids=["LO3"],
            ),
            LocalizedScene(
                scene_id="scene_4",
                order=4,
                title="Reporting the Threat",
                purpose="Outro",
                narration="If you suspect phishing, report it immediately to your cybersecurity operations team.",
                estimated_duration_seconds=7,
                scene_type="outro",
                media_type="motion_visual",
                layout_type="presenter_split",
                avatar_enabled=True,
                presenter_position="right",
                learning_objective_ids=["LO4"],
            ),
        ],
    )


# =========================================================================
# 1. Normal Scene Rendering
# =========================================================================

def test_normal_scene_rendering(tmp_path, four_scene_30s_script):
    """Test 1: Normal scene rendering produces valid completed composition asset."""
    comp_service = CompositionService(output_base_dir=tmp_path)
    project_id = "proj_test_normal_render"
    locale = "en-US"

    scene = four_scene_30s_script.scenes[0]
    rendered_dir = tmp_path / project_id / "rendered" / locale
    rendered_dir.mkdir(parents=True, exist_ok=True)
    out_file = rendered_dir / f"{scene.scene_id}.mp4"

    # Create dummy audio file
    audio_file = tmp_path / project_id / "audio" / locale / f"{scene.scene_id}.mp3"
    audio_file.parent.mkdir(parents=True, exist_ok=True)
    audio_file.write_bytes(b"dummy audio data")

    audio_asset = SceneAudioAsset(
        scene_id=scene.scene_id,
        locale=locale,
        audio_path=str(audio_file),
        duration_seconds=7.0,
        provider="edge_tts",
        voice_id="en-US-ChristopherNeural",
        status="completed",
    )
    audio_track = LocalizedAudioTrack(
        locale=locale,
        total_audio_duration_seconds=7.0,
        status="completed",
        scene_audio=[audio_asset],
    )

    with patch.object(comp_service.provider, "compose_scene") as mock_compose:
        mock_compose.return_value = SceneCompositionAsset(
            scene_id=scene.scene_id,
            locale=locale,
            video_path=str(out_file),
            duration_seconds=7.0,
            has_avatar=False,
            has_subtitles=True,
            status="completed",
        )

        assets = comp_service.compose_locale_scenes(
            script=LocalizedScript(
                locale=locale,
                source_language="en-US",
                language="English",
                title="Normal",
                audience="General",
                opening_hook="Hook",
                closing_summary="Summary",
                target_duration_seconds=7,
                scenes=[scene],
            ),
            audio_track=audio_track,
            project_id=project_id,
        )

        assert len(assets) == 1
        assert assets[0].status == "completed"
        assert assets[0].duration_seconds == 7.0
        mock_compose.assert_called_once()


# =========================================================================
# 2. Zero or Missing Audio Duration
# =========================================================================

def test_zero_or_missing_audio_duration_in_reconciliation(four_scene_30s_script):
    """Test 2A: Duration reconciliation handles 0.0s measured audio duration without ZeroDivisionError."""
    track = LocalizedAudioTrack(
        locale="en-US",
        status="failed",
        total_audio_duration_seconds=0.0,
        scene_audio=[
            SceneAudioAsset(
                scene_id=s.scene_id,
                locale="en-US",
                audio_path="",
                duration_seconds=0.0,
                provider="edge_tts",
                voice_id="en-US-ChristopherNeural",
                status="failed",
            )
            for s in four_scene_30s_script.scenes
        ],
    )

    service = DurationReconciliationService(llm_provider=MagicMock())
    revised_script, new_track, result = service.reconcile_locale_duration(
        current_script=four_scene_30s_script,
        measured_audio_track=track,
        target_duration_seconds=30.0,
        tts_service=None,
        project_id="test_zero_dur_proj",
    )

    assert result.status == "needs_review"
    assert result.is_approved is False
    assert result.revisions_attempted == 0
    assert "0.00s" in result.message or "0.0s" in result.message
    # Ensures narration was not corrupted or wiped
    assert len(revised_script.scenes) == 4


def test_zero_or_missing_audio_duration_in_composition(tmp_path, four_scene_30s_script):
    """Test 2B: Scene composition handles 0.0s audio asset duration by applying safe fallback without ZeroDivisionError."""
    comp_service = CompositionService(output_base_dir=tmp_path)
    project_id = "proj_test_zero_audio"
    locale = "en-US"

    scene = four_scene_30s_script.scenes[0]
    audio_file = tmp_path / project_id / "audio" / locale / f"{scene.scene_id}.mp3"
    audio_file.parent.mkdir(parents=True, exist_ok=True)
    audio_file.write_bytes(b"dummy audio")

    # Audio reports 0.0 duration
    audio_asset = SceneAudioAsset(
        scene_id=scene.scene_id,
        locale=locale,
        audio_path=str(audio_file),
        duration_seconds=0.0,
        provider="edge_tts",
        voice_id="en-US-ChristopherNeural",
        status="completed",
    )
    audio_track = LocalizedAudioTrack(
        locale=locale,
        total_audio_duration_seconds=0.0,
        status="completed",
        scene_audio=[audio_asset],
    )

    with patch.object(comp_service.provider, "compose_scene") as mock_compose:
        mock_compose.return_value = SceneCompositionAsset(
            scene_id=scene.scene_id,
            locale=locale,
            video_path=str(tmp_path / "rendered.mp4"),
            duration_seconds=7.0,
            status="completed",
        )

        assets = comp_service.compose_locale_scenes(
            script=LocalizedScript(
                locale=locale,
                source_language="en-US",
                language="English",
                title="Zero Audio",
                audience="General",
                opening_hook="Hook",
                closing_summary="Summary",
                target_duration_seconds=7,
                scenes=[scene],
            ),
            audio_track=audio_track,
            project_id=project_id,
        )

        # Fallback to scene.estimated_duration_seconds (7.0)
        assert len(assets) == 1
        mock_compose.assert_called_once()
        call_kwargs = mock_compose.call_args.kwargs
        assert call_kwargs["duration_seconds"] == 7.0


# =========================================================================
# 3. Invalid Scene Duration
# =========================================================================

def test_invalid_scene_duration_in_reconciliation(four_scene_30s_script):
    """Test 3A: Reconciliation handles negative or zero target duration safely."""
    track = LocalizedAudioTrack(
        locale="en-US",
        status="completed",
        total_audio_duration_seconds=30.0,
        scene_audio=[],
    )

    service = DurationReconciliationService(llm_provider=MagicMock())
    # target_duration_seconds is 0.0 or negative
    for invalid_target in [0.0, -10.0]:
        _, _, result = service.reconcile_locale_duration(
            current_script=four_scene_30s_script,
            measured_audio_track=track,
            target_duration_seconds=invalid_target,
            tts_service=None,
            project_id="test_invalid_dur",
        )
        assert result.status == "needs_review"
        assert result.is_approved is False


def test_invalid_scene_duration_in_prompt_building(four_scene_30s_script):
    """Test 3B: build_post_tts_duration_revision_prompt does not divide by zero when target duration is 0."""
    prompt = build_post_tts_duration_revision_prompt(
        current_script=four_scene_30s_script,
        measured_total_seconds=30.0,
        target_duration_seconds=0.0,
        scene_durations={},
    )
    assert "POST-TTS DURATION RECONCILIATION" in prompt
    assert "0.0% over target" in prompt


# =========================================================================
# 4. Missing Media Assets
# =========================================================================

def test_missing_media_assets_in_motion_provider(tmp_path, four_scene_30s_script):
    """Test 4: Motion provider handles missing media assets safely with animated or fallback output."""
    provider = LocalMotionVisualProvider()
    scene = four_scene_30s_script.scenes[0]
    out_dir = tmp_path / "motion_test"
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1. Primary path: generate with missing background and custom media
    res_path = provider.generate_scene_media(
        scene=scene,
        locale="en-US",
        output_dir=out_dir,
        duration_seconds=2.0,
        background_image_path=None,
        custom_media_path=None,
    )

    assert res_path.exists()
    assert res_path.stat().st_size > 0

    # 2. Fallback path: if animated motion generation fails, ambient fallback kicks in
    out_dir_fallback = tmp_path / "motion_fallback_test"
    out_dir_fallback.mkdir(parents=True, exist_ok=True)
    with patch("app.services.media.motion_visual_provider.generate_animated_motion_video", side_effect=RuntimeError("Simulated engine failure")):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            fallback_video = out_dir_fallback / f"{scene.scene_id}_motion.mp4"
            fallback_video.write_bytes(b"dummy fallback mp4")

            res_fallback = provider.generate_scene_media(
                scene=scene,
                locale="en-US",
                output_dir=out_dir_fallback,
                duration_seconds=2.0,
                background_image_path=None,
                custom_media_path=None,
            )
            assert res_fallback.exists()
            ambient_file = out_dir_fallback / f"{scene.scene_id}_ambient.png"
            assert ambient_file.exists()


# =========================================================================
# 5. Empty Frame Count or Invalid FPS
# =========================================================================

def test_empty_frame_count_or_invalid_fps(tmp_path, four_scene_30s_script, monkeypatch):
    """Test 5: Zero or negative duration or FPS does not result in 0 total_frames or ZeroDivisionError."""
    provider = LocalMotionVisualProvider()
    scene = four_scene_30s_script.scenes[0]
    out_dir = tmp_path / "fps_test"
    out_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(settings, "VIDEO_FPS", 0)  # Invalid zero FPS in settings

    # Pass duration_seconds=0.0 - should clamp to safe positive duration & FPS without ZeroDivisionError
    res_path = provider.generate_scene_media(
        scene=scene,
        locale="en-US",
        output_dir=out_dir,
        duration_seconds=0.0,
    )

    assert res_path.exists()
    assert res_path.stat().st_size > 0


# =========================================================================
# 6. Progress Calculations with Zero Denominators
# =========================================================================

def test_progress_calculations_with_zero_denominators(four_scene_30s_script):
    """Test 6: Progress and proportion calculations handle zero denominators safely."""
    # 6A: allocate_scene_duration_budgets with all zero durations
    zero_durations = {s.scene_id: 0.0 for s in four_scene_30s_script.scenes}
    budgets = allocate_scene_duration_budgets(
        scenes=four_scene_30s_script.scenes,
        scene_durations=zero_durations,
        target_total_seconds=30.0,
    )
    assert len(budgets) == 4
    for b in budgets:
        assert b.allocated_budget_seconds > 0

    # 6B: build_duration_condensation_prompt with empty scenes list
    empty_script = LocalizedScript.model_construct(
        locale="en-US",
        source_language="en-US",
        language="English",
        title="Empty",
        audience="General",
        opening_hook="Hook",
        closing_summary="Summary",
        target_duration_seconds=30,
        scenes=[],
    )
    prompt = build_duration_condensation_prompt(
        current_script=empty_script,
        measured_total_seconds=30.0,
        target_duration_seconds=30.0,
        compression_ratio=1.0,
        scene_budgets=[],
    )
    assert "target_total_duration_seconds" in prompt

    # 6C: split_narration_into_chunks with 0 duration or empty text
    assert split_narration_into_chunks("", total_duration_seconds=0.0) == []
    assert split_narration_into_chunks("Hello world", total_duration_seconds=0.0) == []
    assert split_narration_into_chunks("", total_duration_seconds=10.0) == []

    # 6D: detect_primary_script with empty counts
    assert detect_primary_script("") is None


# =========================================================================
# 7. Full Rendering Workflow with 4-Scene, 30-Second Configuration
# =========================================================================

def test_full_rendering_workflow_four_scene_30s_config(tmp_path, four_scene_30s_script, monkeypatch):
    """Test 7: Full rendering workflow succeeds without ZeroDivisionError and produces completed manifest."""
    manifest_mgr = ProjectManifestManager(storage_base_dir=tmp_path)
    project_id = "proj_test_4scenes_30s"

    req = TrainingVideoRequest(
        topic=four_scene_30s_script.title,
        base_language="en-US",
        target_languages=["en-US"],
        target_duration_seconds=30,
        video_style="hybrid_presenter_broll",
    )
    manifest = manifest_mgr.create_manifest(project_id, req)
    manifest.final_script = FinalScript(
        title=four_scene_30s_script.title,
        target_duration_seconds=30,
        total_estimated_duration_seconds=30,
        language="en-US",
        audience="Corporate Employees",
        opening_hook=four_scene_30s_script.opening_hook,
        closing_summary=four_scene_30s_script.closing_summary,
        learning_objectives=four_scene_30s_script.learning_objectives,
        scenes=[
            SceneDraft(
                scene_id=s.scene_id,
                order=s.order,
                title=s.title,
                purpose=s.purpose,
                narration=s.narration,
                estimated_duration_seconds=s.estimated_duration_seconds,
                scene_type=s.scene_type,
                media_type=s.media_type,
                layout_type=s.layout_type,
                avatar_enabled=s.avatar_enabled,
                presenter_position=s.presenter_position,
                learning_objective_ids=s.learning_objective_ids,
            )
            for s in four_scene_30s_script.scenes
        ],
    )
    manifest.script_status = "completed"
    manifest.localization_bundle = LocalizationBundle(
        source_script=manifest.final_script,
        target_locales=["en-US"],
        localized_scripts={"en-US": four_scene_30s_script},
    )
    manifest.localization_status = "completed"
    manifest_mgr.save_manifest(manifest)

    orch = ProjectOrchestrator(manifest_manager=manifest_mgr)

    # Mock TTS to return completed 4-scene audio totaling 30s
    audio_items = [
        SceneAudioAsset(
            scene_id=s.scene_id,
            locale="en-US",
            audio_path=str(tmp_path / project_id / "audio" / "en-US" / f"{s.scene_id}.mp3"),
            duration_seconds=float(s.estimated_duration_seconds),
            provider="edge_tts",
            voice_id="en-US-ChristopherNeural",
            status="completed",
        )
        for s in four_scene_30s_script.scenes
    ]
    for a in audio_items:
        p = Path(a.audio_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"dummy audio")

    mock_audio_track = LocalizedAudioTrack(
        locale="en-US",
        total_audio_duration_seconds=30.0,
        status="completed",
        scene_audio=audio_items,
    )

    with patch.object(orch.tts_service, "synthesize_bundle", return_value={"en-US": mock_audio_track}):
        with patch.object(orch.visual_service, "generate_bundle_visuals") as mock_vis:
            mock_vis.return_value = {
                "en-US": LocalizedVisualTrack(
                    locale="en-US",
                    scene_visuals=[
                        SceneVisualAsset(
                            scene_id=s.scene_id,
                            locale="en-US",
                            image_path=str(tmp_path / f"{s.scene_id}.png"),
                            status="completed",
                        )
                        for s in four_scene_30s_script.scenes
                    ],
                )
            }
            with patch.object(orch.subtitle_service, "generate_bundle_subtitles", return_value={}):
                with patch.object(orch.composition_service, "compose_bundle_videos") as mock_comp:
                    final_path = tmp_path / project_id / "final" / "training_en-US.mp4"
                    final_path.parent.mkdir(parents=True, exist_ok=True)
                    final_path.write_bytes(b"dummy mp4")

                    mock_comp.return_value = {
                        "en-US": FinalVideoAsset(
                            locale="en-US",
                            video_path=str(final_path),
                            total_duration_seconds=30.0,
                            scene_count=4,
                            status="completed",
                        )
                    }

                    updated = orch.run_project(project_id, force_regenerate=False)

                    assert updated.status == "completed"
                    assert updated.audio_status == "completed"
                    assert updated.composition_status == "completed"
                    assert "Unexpected error: float division by zero" not in updated.errors
                    assert len(updated.errors) == 0
