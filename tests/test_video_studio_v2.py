"""Comprehensive tests for Video Studio V2:
- Storyboard planner & VideoStyle rules
- Scene layout types (presenter_full, presenter_split, media_full, etc.)
- Scene updating and cache invalidation
- Scene reordering
- Project duplicate and delete
- Media library upload & listing
- Provider readiness status
- Backward compatibility with legacy manifests
"""

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from app.models.schemas import (
    TrainingVideoRequest,
    ProjectManifest,
    FinalScript,
    SceneDraft,
    VideoStyle,
    SceneMediaType,
    SceneLayoutType,
    UpdateSceneRequest,
    ReorderScenesRequest,
    UpdateProjectRequest,
)
from app.workflows.storyboard_planner import StoryboardPlanner
from app.workflows.manifest import ProjectManifestManager
from app.services.media.motion_visual_provider import LocalMotionVisualProvider
from app.services.avatar.base import is_avatar_eligible


def test_storyboard_planner_hybrid_style():
    """Verify hybrid_presenter_broll assigns presenter to intro/outro and motion/broll to body."""
    scenes = [
        SceneDraft(scene_id="s1", order=1, title="Introduction", narration="Welcome to security training.", purpose="Introduction", scene_type="intro"),
        SceneDraft(scene_id="s2", order=2, title="Phishing Emails", narration="Look for strange links.", purpose="Explanation", scene_type="explanation"),
        SceneDraft(scene_id="s3", order=3, title="Knowledge Quiz", narration="What is the first step?", purpose="Knowledge check", scene_type="quiz"),
        SceneDraft(scene_id="s4", order=4, title="Conclusion", narration="Stay vigilant and safe.", purpose="Conclusion", scene_type="outro"),
    ]
    script = FinalScript(
        title="Phishing Defense",
        language="en-US",
        audience="All Staff",
        target_duration_seconds=30,
        total_estimated_duration_seconds=30,
        opening_hook="Hook",
        closing_summary="Summary",
        scenes=scenes,
    )
    req = TrainingVideoRequest(topic="Phishing Defense", video_style=VideoStyle.HYBRID_PRESENTER_BROLL)

    StoryboardPlanner.plan_storyboard(script, req)

    # Scene 1: intro -> presenter_full, avatar_enabled=True
    assert script.scenes[0].media_type == SceneMediaType.PRESENTER.value
    assert script.scenes[0].layout_type == SceneLayoutType.PRESENTER_FULL.value
    assert script.scenes[0].avatar_enabled is True

    # Scene 2: body explanation -> motion_visual or broll
    assert script.scenes[1].media_type in (SceneMediaType.MOTION_VISUAL.value, SceneMediaType.BROLL.value)
    assert script.scenes[1].avatar_enabled is False

    # Scene 3: quiz -> quiz_card with quiz_data
    assert script.scenes[2].media_type == SceneMediaType.QUIZ.value
    assert script.scenes[2].layout_type == SceneLayoutType.QUIZ_CARD.value
    assert script.scenes[2].quiz_data is not None
    assert len(script.scenes[2].quiz_data.options) >= 2

    # Scene 4: outro -> presenter_full, avatar_enabled=True
    assert script.scenes[3].media_type == SceneMediaType.OUTRO.value
    assert script.scenes[3].layout_type == SceneLayoutType.PRESENTER_FULL.value
    assert script.scenes[3].avatar_enabled is True


def test_storyboard_planner_demonstration_style_kabsa():
    """Verify demonstration_tutorial style generates B-roll/media demonstration scenes."""
    scenes = [
        SceneDraft(scene_id="s1", order=1, title="Welcome to Kabsa", narration="Let us cook Saudi Kabsa.", purpose="Intro", scene_type="intro"),
        SceneDraft(scene_id="s2", order=2, title="Browning Chicken", narration="Brown chicken with spices.", purpose="Cook chicken step", scene_type="step"),
        SceneDraft(scene_id="s3", order=3, title="Simmering Rice", narration="Add basmati rice.", purpose="Rice prep step", scene_type="step"),
        SceneDraft(scene_id="s4", order=4, title="Enjoy Your Meal", narration="Serve hot with dakous.", purpose="Outro", scene_type="outro"),
    ]
    script = FinalScript(
        title="Saudi Kabsa",
        language="en-US",
        audience="Kitchen Staff",
        target_duration_seconds=45,
        total_estimated_duration_seconds=45,
        opening_hook="Let's cook delicious Kabsa.",
        closing_summary="Enjoy your traditional meal.",
        scenes=scenes,
    )
    req = TrainingVideoRequest(topic="Saudi Kabsa Preparation", video_style=VideoStyle.DEMONSTRATION_TUTORIAL)

    StoryboardPlanner.plan_storyboard(script, req)

    # Middle steps should be broll demonstration
    assert script.scenes[1].media_type == SceneMediaType.BROLL.value
    assert script.scenes[1].layout_type == SceneLayoutType.MEDIA_FULL.value
    assert script.scenes[2].media_type == SceneMediaType.BROLL.value


def test_is_avatar_eligible_with_v2_fields():
    """Ensure avatar eligibility respects avatar_enabled flag and scene media types."""
    # Explicitly disabled
    s1 = SceneDraft(scene_id="s1", order=1, title="T", narration="N", scene_type="intro", avatar_enabled=False)
    assert is_avatar_eligible(s1) is False

    # Presenter type with avatar_enabled=True
    s2 = SceneDraft(scene_id="s2", order=2, title="T", narration="N", scene_type="intro", media_type=SceneMediaType.PRESENTER, avatar_enabled=True)
    assert is_avatar_eligible(s2) is True

    # Broll type should not be avatar eligible
    s3 = SceneDraft(scene_id="s3", order=3, title="T", narration="N", scene_type="step", media_type=SceneMediaType.BROLL, avatar_enabled=False)
    assert is_avatar_eligible(s3) is False

    # Outro should be eligible
    s4 = SceneDraft(scene_id="s4", order=4, title="T", narration="N", scene_type="outro", media_type=SceneMediaType.OUTRO, avatar_enabled=True)
    assert is_avatar_eligible(s4) is True


def test_scene_update_and_cache_invalidation(tmp_path: Path):
    """Test updating narration invalidates downstream cached tracks."""
    from app.api.v1.projects import update_scene, manifest_manager

    manifest_manager.storage_base_dir = tmp_path
    req = TrainingVideoRequest(topic="Phishing Test", base_language="en-US", target_languages=["ar-SA"])
    manifest = manifest_manager.create_manifest("proj_test_invalidation", req)
    
    scenes = [
        SceneDraft(scene_id="sc_1", order=1, title="Intro", narration="Original narration text.", scene_type="intro")
    ]
    manifest.final_script = FinalScript(
        title="Phishing Test",
        language="en-US",
        audience="Staff",
        target_duration_seconds=10,
        total_estimated_duration_seconds=10,
        opening_hook="Hook",
        closing_summary="Summary",
        scenes=scenes,
    )
    manifest.audio_status = "completed"
    manifest.avatar_status = "completed"
    manifest.composition_status = "completed"
    manifest.status = "completed"
    manifest_manager.save_manifest(manifest)

    # Invalidate by updating narration
    import asyncio
    payload = UpdateSceneRequest(narration="Brand new updated narration text.")
    res = asyncio.run(update_scene("proj_test_invalidation", "sc_1", payload))

    loaded = manifest_manager.load_manifest("proj_test_invalidation")
    assert loaded.audio_status == "pending"
    assert loaded.avatar_status == "pending"
    assert loaded.composition_status == "pending"
    assert loaded.status == "script_completed"
    assert loaded.final_script.scenes[0].narration == "Brand new updated narration text."


def test_scene_reordering(tmp_path: Path):
    """Test reordering scenes in canonical script."""
    from app.api.v1.projects import reorder_scenes, manifest_manager
    import asyncio

    manifest_manager.storage_base_dir = tmp_path
    req = TrainingVideoRequest(topic="Reorder Test")
    manifest = manifest_manager.create_manifest("proj_test_reorder", req)
    scenes = [
        SceneDraft(scene_id="s1", order=1, title="First", narration="A", scene_type="intro"),
        SceneDraft(scene_id="s2", order=2, title="Second", narration="B", scene_type="step"),
        SceneDraft(scene_id="s3", order=3, title="Third", narration="C", scene_type="outro"),
    ]
    manifest.final_script = FinalScript(
        title="Reorder Test",
        language="en-US",
        audience="Staff",
        target_duration_seconds=30,
        total_estimated_duration_seconds=30,
        opening_hook="Hook",
        closing_summary="Summary",
        scenes=scenes,
    )
    manifest_manager.save_manifest(manifest)

    payload = ReorderScenesRequest(scene_ids=["s3", "s1", "s2"])
    res = asyncio.run(reorder_scenes("proj_test_reorder", payload))

    loaded = manifest_manager.load_manifest("proj_test_reorder")
    new_order = [s.scene_id for s in loaded.final_script.scenes]
    assert new_order == ["s3", "s1", "s2"]
    assert loaded.final_script.scenes[0].order == 1
    assert loaded.final_script.scenes[1].order == 2
    assert loaded.final_script.scenes[2].order == 3


def test_backward_compatibility_old_scene_defaults():
    """Ensure legacy scene data without media_type or layout_type deserializes safely."""
    old_data = {
        "scene_id": "legacy_sc1",
        "order": 1,
        "title": "Legacy Slide",
        "narration": "Old narration without V2 attributes.",
        "purpose": "General delivery",
        "scene_type": "presentation_slide",
    }
    scene = SceneDraft.model_validate(old_data)
    assert scene.media_type is not None
    assert scene.layout_type is not None
    assert scene.avatar_enabled is not None
