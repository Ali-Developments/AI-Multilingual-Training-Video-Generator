"""Test suite for Phase 3: Scene Planning & Storyboard Upgrade.

Verifies:
1. SceneMediaPlan schema structure and serialization.
2. SceneDraft & LocalizedScene media plan synchronization.
3. StoryboardPlanner scene categorization:
   - Presenter (heygen / sadtalker)
   - Animated B-Roll (veo)
   - Infographic / Motion Graphics (motion_visual / local_motion)
   - Quiz (quiz)
   - Outro (outro)
4. Dynamic, topic-agnostic fallback quiz generation without hardcoded domain leaks.
5. End-to-end synchronization of media plans into localized scripts.
"""

from pathlib import Path
import pytest

from app.models.schemas import (
    SceneDraft,
    ScriptDraft,
    FinalScript,
    LocalizedScript,
    LocalizedScene,
    SceneMediaPlan,
    SceneMediaType,
    SceneLayoutType,
    VideoStyle,
    TrainingVideoRequest,
    LearningObjective,
)
from app.workflows.storyboard_planner import StoryboardPlanner


def test_scene_media_plan_schema_validation():
    """Verify SceneMediaPlan supports all required production fields."""
    plan = SceneMediaPlan(
        scene_id="scene_1",
        purpose="Introduction to Topic",
        narration="Welcome to our comprehensive course.",
        visual_description="Modern studio presenter with branded backdrop.",
        motion_description="Natural presenter gestures and lip-sync alignment.",
        camera_movement="static",
        reference_image_requirements="Clean corporate office setting",
        preferred_provider="heygen",
        target_duration=15.0,
        aspect_ratio="16:9",
    )
    assert plan.scene_id == "scene_1"
    assert plan.purpose == "Introduction to Topic"
    assert plan.preferred_provider == "heygen"
    assert plan.target_duration == 15.0
    assert plan.aspect_ratio == "16:9"

    dump = plan.model_dump()
    assert dump["camera_movement"] == "static"
    assert dump["preferred_provider"] == "heygen"


def test_scene_draft_auto_constructs_media_plan():
    """Verify SceneDraft automatically creates and synchronizes SceneMediaPlan."""
    scene = SceneDraft(
        scene_id="scene_demo",
        order=2,
        title="Inspection Step",
        purpose="Demonstrate equipment inspection",
        narration="Carefully examine the pressure valves before startup.",
        estimated_duration_seconds=20,
        visual_direction="Close-up of industrial pressure valve indicator gauge.",
        motion_description="Slow camera push toward the pressure needle.",
        camera_movement="slow zoom-in",
        preferred_provider="veo",
    )
    assert scene.media_plan is not None
    assert isinstance(scene.media_plan, SceneMediaPlan)
    assert scene.media_plan.scene_id == "scene_demo"
    assert scene.media_plan.purpose == "Demonstrate equipment inspection"
    assert scene.media_plan.preferred_provider == "veo"
    assert scene.media_plan.camera_movement == "slow zoom-in"
    assert scene.media_plan.target_duration == 20.0
    assert scene.media_plan.aspect_ratio == "16:9"


def test_storyboard_planner_categorization_and_provider_dispatch(monkeypatch):
    """Verify StoryboardPlanner accurately categorizes scenes and assigns appropriate providers."""
    from app.core.config import settings
    monkeypatch.setattr(settings, "ENABLE_LIVE_HEYGEN", True)

    scenes = [
        SceneDraft(
            scene_id="scene_1",
            order=1,
            title="Introduction",
            purpose="Welcome learners and outline goals",
            narration="Welcome to industrial robotics safety training.",
            estimated_duration_seconds=15,
            scene_type="intro",
        ),
        SceneDraft(
            scene_id="scene_2",
            order=2,
            title="Emergency Stop Procedure",
            purpose="Demonstrate pressing emergency shutoff button",
            narration="When an anomaly occurs, immediately depress the red emergency button.",
            estimated_duration_seconds=20,
            scene_type="visual_demo",
        ),
        SceneDraft(
            scene_id="scene_3",
            order=3,
            title="Safety Protocols Overview",
            purpose="Explain safety perimeter zones",
            narration="Robotic arms operate within a designated three-meter safety perimeter.",
            estimated_duration_seconds=25,
            scene_type="explanation",
        ),
        SceneDraft(
            scene_id="scene_4",
            order=4,
            title="Quick Knowledge Check",
            purpose="Test emergency stop response time",
            narration="Let us test your understanding of emergency shutoff.",
            estimated_duration_seconds=15,
            scene_type="quiz",
        ),
        SceneDraft(
            scene_id="scene_5",
            order=5,
            title="Conclusion and Summary",
            purpose="Summarize safety rules and sign off",
            narration="Remember, safety is everyone's responsibility. Stay vigilant.",
            estimated_duration_seconds=15,
            scene_type="outro",
        ),
    ]

    script = ScriptDraft(
        title="Industrial Robotics Safety",
        language="en-US",
        audience="Plant Operators",
        scenes=scenes,
        opening_hook="Can you shut down an errant robotic cell in time?",
        closing_summary="Always maintain situational awareness.",
        total_estimated_duration_seconds=90,
    )

    req = TrainingVideoRequest(
        topic="Industrial Robotics Safety",
        audience="Plant Operators",
        avatar_provider="heygen",
        ack_paid_credits=True,
        video_style=VideoStyle.HYBRID_PRESENTER_BROLL.value,
        target_duration_seconds=90,
    )

    planned = StoryboardPlanner.plan_storyboard(script, request_or_topic=req)

    # 1. Scene 1: Presenter Intro
    s1 = planned.scenes[0]
    assert s1.media_type == SceneMediaType.PRESENTER.value
    assert s1.avatar_enabled is True
    assert s1.preferred_provider == "heygen"
    assert s1.media_plan.preferred_provider == "heygen"
    assert "presenter" in s1.media_plan.motion_description.lower()

    # 2. Scene 2: Animated B-Roll (Veo)
    s2 = planned.scenes[1]
    assert s2.media_type == SceneMediaType.BROLL.value
    assert s2.layout_type == SceneLayoutType.MEDIA_FULL.value
    assert s2.avatar_enabled is False
    assert s2.preferred_provider == "veo"
    assert s2.media_plan.preferred_provider == "veo"
    assert s2.camera_movement == "slow pan"
    assert "b-roll" in s2.media_plan.motion_description.lower()

    # 3. Scene 3: Infographic / Motion Visual (local_motion)
    s3 = planned.scenes[2]
    assert s3.media_type == SceneMediaType.MOTION_VISUAL.value
    assert s3.layout_type == SceneLayoutType.MEDIA_WITH_OVERLAY.value
    assert s3.avatar_enabled is False
    assert s3.preferred_provider == "local_motion"
    assert s3.media_plan.preferred_provider == "local_motion"

    # 4. Scene 4: Quiz
    s4 = planned.scenes[3]
    assert s4.media_type == SceneMediaType.QUIZ.value
    assert s4.layout_type == SceneLayoutType.QUIZ_CARD.value
    assert s4.avatar_enabled is False
    assert s4.preferred_provider == "quiz"
    assert s4.quiz_data is not None
    assert len(s4.quiz_data.options) >= 3

    # 5. Scene 5: Outro
    s5 = planned.scenes[4]
    assert s5.media_type == SceneMediaType.OUTRO.value
    assert s5.avatar_enabled is True
    assert s5.preferred_provider == "heygen"
    assert s5.media_plan.preferred_provider == "heygen"


def test_dynamic_fallback_quiz_no_cybersecurity_leak():
    """Verify fallback quiz generation is derived dynamically without hardcoded cybersecurity terms."""
    culinary_scene = SceneDraft(
        scene_id="scene_quiz",
        order=3,
        title="Fermentation Temperature Monitoring",
        purpose="Ensure sourdough starter ferments at exactly twenty-six degrees Celsius",
        narration="Proper ambient temperature determines crumb structure and lactic acidity.",
        estimated_duration_seconds=15,
        scene_type="quiz",
    )

    quiz = StoryboardPlanner._generate_fallback_quiz(culinary_scene, "Artisan Bread Baking")
    assert quiz.question is not None
    assert "Fermentation Temperature Monitoring" in quiz.question or "Artisan Bread" in quiz.question
    
    # Check that cybersecurity terms are NOT present
    for opt in quiz.options:
        opt_low = opt.lower()
        assert "phishing" not in opt_low
        assert "sender" not in opt_low
        assert "external contacts" not in opt_low
        assert "spoof" not in opt_low
        assert "email" not in opt_low

    assert quiz.correct_index == 0
    assert "Fermentation Temperature Monitoring" in quiz.options[0] or "ferment" in quiz.options[0].lower()


def test_localized_scene_synchronization_and_media_plan_preservation():
    """Verify that LocalizedScene synchronizes media plan and preserves all storyboard attributes."""
    source_scene = SceneDraft(
        scene_id="scene_2",
        order=2,
        title="Factory Inspection",
        purpose="Demonstrate safety gear check",
        narration="Inspect safety helmets and high-visibility vests.",
        estimated_duration_seconds=20,
        media_type="broll",
        layout_type="media_full",
        avatar_enabled=False,
        preferred_provider="veo",
        camera_movement="slow pan",
        motion_description="Cinematic slow panning B-roll across safety gear racks.",
    )

    loc_scene = LocalizedScene(
        scene_id="scene_2",
        order=2,
        title="فحص المصنع",
        purpose="إظهار التحقق من معدات السلامة",
        narration="افحص خوذات السلامة والسترات العاكسة بعناية فائقة.",
        estimated_duration_seconds=20,
        media_type=source_scene.media_type,
        layout_type=source_scene.layout_type,
        avatar_enabled=source_scene.avatar_enabled,
        preferred_provider=source_scene.preferred_provider,
        camera_movement=source_scene.camera_movement,
        motion_description=source_scene.motion_description,
    )

    assert loc_scene.media_plan is not None
    assert loc_scene.media_plan.scene_id == "scene_2"
    assert loc_scene.media_plan.preferred_provider == "veo"
    assert loc_scene.media_plan.camera_movement == "slow pan"
    assert loc_scene.media_plan.target_duration == 20.0
    assert loc_scene.media_plan.aspect_ratio == "16:9"
    assert "فحص المصنع" in loc_scene.media_plan.visual_description or loc_scene.title in loc_scene.media_plan.visual_description


def test_storyboard_planner_all_video_styles():
    """Verify StoryboardPlanner categorizes correctly across all VideoStyle modes."""
    scenes = [
        SceneDraft(scene_id="s1", order=1, title="Intro", purpose="Intro", narration="Intro", scene_type="intro"),
        SceneDraft(scene_id="s2", order=2, title="Step 1 Action", purpose="Demonstrate step", narration="Action step", scene_type="visual_demo"),
        SceneDraft(scene_id="s3", order=3, title="Core Principle", purpose="Explain principle", narration="Theory", scene_type="explanation"),
        SceneDraft(scene_id="s4", order=4, title="Summary", purpose="Outro", narration="Outro", scene_type="outro"),
    ]
    script = ScriptDraft(
        title="Operations Workflow",
        language="en-US",
        scenes=scenes,
        opening_hook="Hook",
        closing_summary="Summary",
        total_estimated_duration_seconds=60,
    )

    # 1. VISUAL_EXPLAINER
    req_ve = TrainingVideoRequest(
        topic="Operations Workflow",
        avatar_provider="mock",
        video_style=VideoStyle.VISUAL_EXPLAINER.value,
        target_duration_seconds=60,
    )
    p_ve = StoryboardPlanner.plan_storyboard(script, request_or_topic=req_ve)
    assert p_ve.scenes[1].media_type == SceneMediaType.BROLL.value
    assert p_ve.scenes[1].preferred_provider == "veo"
    assert p_ve.scenes[2].media_type == SceneMediaType.MOTION_VISUAL.value
    assert p_ve.scenes[2].preferred_provider == "local_motion"

    # 2. DEMONSTRATION_TUTORIAL
    req_dt = TrainingVideoRequest(
        topic="Hands-on Machinery Operations",
        avatar_provider="sadtalker",
        video_style=VideoStyle.DEMONSTRATION_TUTORIAL.value,
        target_duration_seconds=60,
    )
    p_dt = StoryboardPlanner.plan_storyboard(script, request_or_topic=req_dt)
    assert p_dt.scenes[0].preferred_provider == "sadtalker"
    assert p_dt.scenes[1].preferred_provider == "veo"
    assert p_dt.scenes[1].media_type == SceneMediaType.BROLL.value

    # 3. PRESENTER_LED
    req_pl = TrainingVideoRequest(
        topic="Executive Briefing",
        avatar_provider="mock",
        video_style=VideoStyle.PRESENTER_LED.value,
        target_duration_seconds=60,
    )
    p_pl = StoryboardPlanner.plan_storyboard(script, request_or_topic=req_pl)
    assert p_pl.scenes[0].preferred_provider == "mock"
    assert p_pl.scenes[1].preferred_provider == "mock"
    assert p_pl.scenes[1].media_type == SceneMediaType.PRESENTER.value
    assert p_pl.scenes[2].preferred_provider == "local_motion"
    assert p_pl.scenes[2].media_type == SceneMediaType.MOTION_VISUAL.value

