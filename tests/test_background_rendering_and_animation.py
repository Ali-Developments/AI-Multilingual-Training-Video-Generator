"""Offline unit and API tests for non-blocking background rendering and narration-synchronized visual demonstrations.

Strictly offline: uses mocked orchestrator, TTS, avatar, and media providers.
Does not make external API calls or invoke live SadTalker/Veo/LLM providers.
"""

import threading
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.schemas import (
    TrainingVideoRequest,
    FinalScript,
    SceneDraft,
    LocalizedScene,
    LocalizedScript,
    LocalizedAudioTrack,
    SceneAudioAsset,
    SceneMediaPlan,
    AnimationStep,
)
from app.workflows.manifest import ProjectManifestManager
from app.workflows.orchestrator import ProjectOrchestrator
from app.workflows.storyboard_planner import StoryboardPlanner
from app.services.media.motion_animator import (
    detect_motion_archetype,
    _render_process_demonstration_frame,
)
from app.services.composition.service import CompositionService
from app.services.composition.mock_provider import MockCompositionProvider


@pytest.fixture
def client():
    return TestClient(app)


# =========================================================================
# Part 5 / Part 7A: Non-Blocking Background Rendering Tests
# =========================================================================


def test_render_returns_202_immediately_and_keeps_event_loop_responsive(client, tmp_path, monkeypatch):
    """HTTP 202 is returned immediately, event loop remains responsive, and polling works during rendering."""
    mgr = ProjectManifestManager(storage_base_dir=tmp_path)
    orch = ProjectOrchestrator(manifest_manager=mgr)
    monkeypatch.setattr("app.api.v1.projects.manifest_manager", mgr)
    monkeypatch.setattr("app.api.v1.projects.orchestrator", orch)

    project_id = "proj_async_render_202"
    req = TrainingVideoRequest(
        topic="Async Background Render Test",
        base_language="en-US",
        target_languages=["en-US"],
        target_duration_seconds=30,
    )
    mgr.create_manifest(project_id, req)

    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()

    def _slow_render(**kwargs):
        m = mgr.load_manifest(project_id)
        m.audio_status = "running"
        mgr.save_manifest(m)
        started.set()
        release.wait(timeout=5.0)
        m = mgr.load_manifest(project_id)
        m.audio_status = "completed"
        m.composition_status = "completed"
        m.status = "completed"
        mgr.save_manifest(m)
        finished.set()
        return m

    with patch.object(orch, "run_project", side_effect=_slow_render):
        t0 = time.monotonic()
        res = client.post(f"/api/v1/projects/{project_id}/render", json={"force_regenerate": False})
        elapsed = time.monotonic() - t0

        assert res.status_code == 202
        assert elapsed < 1.5, f"POST /render should return immediately, took {elapsed:.2f}s"
        assert res.json()["status"] == "rendering"

        assert started.wait(timeout=3.0), "Background worker did not start"

        # Event loop & status polling must respond while render is actively running
        poll_res = client.get(f"/api/v1/projects/{project_id}")
        assert poll_res.status_code == 200
        poll_data = poll_res.json()
        assert poll_data["status"] == "rendering"
        assert poll_data["audio_status"] == "running"

        # Duplicate render request must be prevented with HTTP 409 Conflict
        dup_res = client.post(f"/api/v1/projects/{project_id}/render", json={"force_regenerate": False})
        assert dup_res.status_code == 409
        assert "already in progress" in dup_res.json()["detail"].lower()

        # Release worker and verify persisted completion
        release.set()
        assert finished.wait(timeout=3.0), "Background worker did not complete"

        final_res = client.get(f"/api/v1/projects/{project_id}")
        assert final_res.status_code == 200
        assert final_res.json()["status"] == "completed"
        assert final_res.json()["composition_status"] == "completed"


def test_background_render_failure_is_persisted_and_reported(client, tmp_path, monkeypatch):
    """Background worker exceptions persist status='failed' and surface the real error via GET /projects/{id}."""
    mgr = ProjectManifestManager(storage_base_dir=tmp_path)
    orch = ProjectOrchestrator(manifest_manager=mgr)
    monkeypatch.setattr("app.api.v1.projects.manifest_manager", mgr)
    monkeypatch.setattr("app.api.v1.projects.orchestrator", orch)

    project_id = "proj_async_render_fail"
    req = TrainingVideoRequest(
        topic="Failing Background Render",
        base_language="en-US",
        target_languages=["en-US"],
        target_duration_seconds=30,
    )
    mgr.create_manifest(project_id, req)

    with patch.object(orch, "run_project", side_effect=RuntimeError("Simulated FFmpeg mux failure")):
        res = client.post(f"/api/v1/projects/{project_id}/render", json={"force_regenerate": False})
        assert res.status_code == 202

        deadline = time.time() + 5.0
        polled = None
        while time.time() < deadline:
            polled = client.get(f"/api/v1/projects/{project_id}").json()
            if polled["status"] == "failed":
                break
            time.sleep(0.05)

        assert polled is not None
        assert polled["status"] == "failed"
        assert any("Simulated FFmpeg mux failure" in e for e in polled["errors"])


def test_studio_frontend_supports_202_polling_and_refresh_resumption():
    """Verify Studio frontend page implements 2.5s polling and browser-refresh resumption for rendering jobs."""
    studio_tsx = Path("web/src/app/studio/[id]/page.tsx").read_text(encoding="utf-8")
    assert "startRenderPolling" in studio_tsx
    assert "2500" in studio_tsx
    assert "proj.status === 'rendering' || proj.status === 'running'" in studio_tsx
    assert "msg.includes('409')" in studio_tsx


# =========================================================================
# Part 4 / Part 7B: Visual Demonstration & Animation Synchronization Tests
# =========================================================================


def test_demonstration_scenes_preserve_layout_and_are_not_downgraded():
    """Demonstration scenes keep demonstration layout and are not downgraded to static presenter cards."""
    script = FinalScript(
        title="Laboratory Acid-Base Titration",
        language="en-US",
        audience="Chemistry Students",
        target_duration_seconds=60,
        total_estimated_duration_seconds=60,
        opening_hook="Welcome to titration.",
        closing_summary="Great job.",
        scenes=[
            SceneDraft(
                scene_id="scene_1",
                order=1,
                title="Introduction to Titration",
                purpose="Introduce equipment and goal",
                narration="Welcome. Today we will measure acid concentration using a burette and indicator.",
                estimated_duration_seconds=12,
                scene_type="intro",
            ),
            SceneDraft(
                scene_id="scene_2",
                order=2,
                title="Preparing and Pouring the Solution",
                purpose="Demonstrate pouring and mixing",
                narration="First, pour the titrant into the burette. Next, swirl the flask and observe the color change.",
                estimated_duration_seconds=18,
                visual_direction="Close-up pouring titrant into burette and swirling Erlenmeyer flask",
                scene_type="visual_demo",
            ),
            SceneDraft(
                scene_id="scene_3",
                order=3,
                title="Heating and Stirring the Mixture",
                purpose="Demonstrate thermal control",
                narration="Heat the beaker gently, then stir continuously until the crystals dissolve completely.",
                estimated_duration_seconds=18,
                visual_direction="Heating beaker on hot plate while stirring dissolved solution",
                scene_type="visual_demo",
            ),
            SceneDraft(
                scene_id="scene_4",
                order=4,
                title="Conclusion and Summary",
                purpose="Wrap up takeaways",
                narration="You have completed the titration accurately.",
                estimated_duration_seconds=12,
                scene_type="outro",
            ),
        ],
    )
    req = TrainingVideoRequest(
        topic="Laboratory Acid-Base Titration",
        base_language="en-US",
        target_languages=["en-US"],
        target_duration_seconds=60,
        video_style="demonstration_tutorial",
        persistent_presenter=False,
    )

    planned = StoryboardPlanner.plan_storyboard(script, req)
    demo_s2 = planned.scenes[1]
    demo_s3 = planned.scenes[2]

    assert demo_s2.media_type == "broll"
    assert demo_s2.layout_type == "media_full"
    assert demo_s2.avatar_enabled is False
    assert demo_s2.media_plan is not None
    assert demo_s2.media_plan.is_animated_demonstration is True
    assert len(demo_s2.media_plan.animation_sequence) >= 2
    assert demo_s2.media_plan.animation_sequence[0].start_ratio == 0.0
    assert demo_s2.media_plan.animation_sequence[-1].end_ratio == 1.0

    assert demo_s3.media_plan is not None
    assert demo_s3.media_plan.is_animated_demonstration is True
    assert any(st.action_verb in ("heat", "mix") for st in demo_s3.media_plan.animation_sequence)


def test_generic_multilingual_action_assignment_and_no_cybersecurity_hijack():
    """Cooking/science/Arabic scenes get process_demonstration (never hijacked by cybersecurity cards)."""
    ar_cooking_scene = LocalizedScene(
        scene_id="scene_3",
        order=3,
        title="طهي اللحم المفروم وتجهيز الحشوة",
        purpose="Demonstrate safe cooking workflow step by step",
        narration="نسخن المقلاة ثم نضيف البصل المفروم. نقلب البصل مع اللحم المفروم والتوابل حتى ينضج تماماً.",
        estimated_duration_seconds=14,
        visual_direction="Heating pan, adding chopped onions, stirring minced meat safely",
        scene_type="visual_demo",
        media_type="broll",
        layout_type="media_full",
        avatar_enabled=False,
    )
    ar_cooking_scene.media_plan = StoryboardPlanner.build_demonstration_plan(ar_cooking_scene, topic="Cooking")

    # Even though 'safe' and 'workflow' appear in purpose/visual_direction, it must NOT be hijacked by cybersecurity!
    archetype = detect_motion_archetype(ar_cooking_scene)
    assert archetype == "process_demonstration"
    assert ar_cooking_scene.media_plan.is_animated_demonstration is True
    assert len(ar_cooking_scene.media_plan.animation_sequence) >= 2
    assert any(st.movement in ("heat_pulse", "stir_circular", "pour_stream", "chop_rhythm") for st in ar_cooking_scene.media_plan.animation_sequence)

    # Verify early vs late frames actually change visually (true continuous animation, not a static freeze)
    frame_early = _render_process_demonstration_frame(640, 360, sec=1.0, dur=14.0, scene=ar_cooking_scene)
    frame_late = _render_process_demonstration_frame(640, 360, sec=11.0, dur=14.0, scene=ar_cooking_scene)
    assert frame_early.tobytes() != frame_late.tobytes(), "Animated demonstration frames must evolve over scene duration"


def test_static_quiz_and_animated_demo_are_accurately_distinguished():
    """Quiz/title cards are marked static (is_animated_demonstration=False) while demonstrations are True."""
    quiz_scene = SceneDraft(
        scene_id="scene_q",
        order=2,
        title="Quick Safety Check",
        purpose="Knowledge check",
        narration="Which voltage setting should be verified first?",
        estimated_duration_seconds=10,
        scene_type="quiz",
        media_type="quiz",
        layout_type="quiz_card",
        avatar_enabled=False,
    )
    quiz_plan = StoryboardPlanner.build_demonstration_plan(quiz_scene, topic="Electronics")
    quiz_scene.media_plan = quiz_plan

    assert quiz_plan.is_animated_demonstration is False
    assert detect_motion_archetype(quiz_scene) == "general_concept"


def test_scene_animation_survives_composition_and_matches_audio_duration(tmp_path):
    """CompositionService passes generated motion_video_path and exact audio duration into composition provider."""
    audio_file = tmp_path / "scene_2.mp3"
    audio_file.write_bytes(b"fake-audio-bytes")
    motion_file = tmp_path / "scene_2_motion.mp4"
    motion_file.write_bytes(b"fake-motion-video-bytes")

    scene = LocalizedScene(
        scene_id="scene_2",
        order=1,
        title="Assembling the Circuit",
        purpose="Connect components in sequence",
        narration="Connect the resistor to pin one, then wire the LED to ground.",
        estimated_duration_seconds=12,
        visual_direction="Breadboard wiring sequence",
        scene_type="visual_demo",
        media_type="broll",
        layout_type="media_full",
        avatar_enabled=False,
    )
    scene.media_plan = StoryboardPlanner.build_demonstration_plan(scene, topic="Electronics")

    loc_script = LocalizedScript(
        locale="en-US",
        source_language="en-US",
        language="en-US",
        title="Electronics Lab",
        audience="Students",
        target_duration_seconds=12,
        opening_hook="Hook",
        closing_summary="Summary",
        scenes=[scene],
    )
    audio_track = LocalizedAudioTrack(
        locale="en-US",
        scene_audio=[
            SceneAudioAsset(
                scene_id="scene_2",
                locale="en-US",
                voice_id="mock_en_voice",
                audio_path=str(audio_file),
                duration_seconds=11.4,
                provider="mock",
                status="completed",
            )
        ],
        total_duration_seconds=11.4,
        status="completed",
    )

    mock_comp_provider = MagicMock(wraps=MockCompositionProvider())
    comp_service = CompositionService(provider=mock_comp_provider, output_base_dir=tmp_path)

    with patch.object(comp_service.media_service, "generate_scene_media", return_value=motion_file) as mock_gen_media:
        results = comp_service.compose_locale_scenes(
            script=loc_script,
            audio_track=audio_track,
            project_id="proj_comp_anim_test",
            force_regenerate=True,
        )

    assert len(results) == 1
    assert results[0].status == "completed"
    # Verify media generator received exact measured audio duration (11.4s)
    mock_gen_media.assert_called_once()
    assert mock_gen_media.call_args.kwargs["duration_seconds"] == pytest.approx(11.4)
    # Verify composition provider received the animated motion_video_path and exact duration
    mock_comp_provider.compose_scene.assert_called_once()
    comp_kwargs = mock_comp_provider.compose_scene.call_args.kwargs
    assert comp_kwargs["motion_video_path"] == motion_file
    assert comp_kwargs["duration_seconds"] == pytest.approx(11.4)
    assert comp_kwargs["layout_type"] == "media_full"
