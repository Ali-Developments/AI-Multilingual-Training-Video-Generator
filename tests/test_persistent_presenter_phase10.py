"""Comprehensive test suite for Phase 10: Persistent Presenter Architecture.

Tests:
1. StoryboardPlanner in persistent mode sets avatar_enabled=True across all spoken scenes.
2. B-roll and Motion Visual scenes become supporting visual layers rather than standalone slides.
3. Dynamic persistent layouts:
   - presenter_left_visual_right
   - presenter_right_visual_left
   - presenter_picture_in_picture
   - presenter_center_with_overlays
4. Eligibility rules classify persistent presenter layouts as eligible.
5. FFmpeg composition renders all persistent layouts at 1080p.
"""

from pathlib import Path
import pytest
from unittest.mock import MagicMock, patch

from app.models.schemas import (
    SceneDraft,
    ScriptDraft,
    SceneMediaType,
    SceneLayoutType,
    VideoStyle,
    TrainingVideoRequest,
    LocalizedScene,
)
from app.workflows.storyboard_planner import StoryboardPlanner
from app.services.avatar.base import is_avatar_eligible, PRESENTER_ACTIVE_LAYOUTS
from app.services.composition.ffmpeg_provider import FFmpegCompositionProvider


def test_storyboard_planner_persistent_presenter_all_scenes():
    """Verify that in persistent presenter mode, all spoken scenes maintain avatar_enabled=True."""
    scenes = [
        SceneDraft(
            scene_id="scene_1",
            order=1,
            title="Introduction",
            purpose="Welcome learners and outline goals",
            narration="Welcome to cybersecurity essentials training.",
            estimated_duration_seconds=10,
            scene_type="intro",
        ),
        SceneDraft(
            scene_id="scene_2",
            order=2,
            title="Email Header Verification",
            purpose="Demonstrate checking sender domain",
            narration="Always hover over the sender domain to inspect for spoofing.",
            estimated_duration_seconds=8,
            scene_type="visual_demo",
        ),
        SceneDraft(
            scene_id="scene_3",
            order=3,
            title="Incident Reporting",
            purpose="Explain reporting protocol",
            narration="Immediately flag suspicious messages using the report button.",
            estimated_duration_seconds=9,
            scene_type="explanation",
        ),
        SceneDraft(
            scene_id="scene_4",
            order=4,
            title="Closing Protocol",
            purpose="Summary and recommendations",
            narration="Stay vigilant and protect the corporate perimeter.",
            estimated_duration_seconds=7,
            scene_type="outro",
        ),
    ]

    script = ScriptDraft(
        title="Cybersecurity Essentials",
        language="ar-SA",
        scenes=scenes,
        opening_hook="Can you spot a phishing attempt?",
        closing_summary="Vigilance is safety.",
        total_estimated_duration_seconds=34,
    )

    req = TrainingVideoRequest(
        topic="Cybersecurity Essentials",
        audience="Corporate Staff",
        avatar_provider="sadtalker",
        video_style=VideoStyle.HYBRID_PRESENTER_BROLL.value,
        persistent_presenter=True,
    )

    planned = StoryboardPlanner.plan_storyboard(script, request_or_topic=req, persistent_presenter=True)

    # 1. Intro Scene: Presenter Left + Visual Right
    s1 = planned.scenes[0]
    assert s1.avatar_enabled is True
    assert s1.layout_type == SceneLayoutType.PRESENTER_LEFT_VISUAL_RIGHT.value
    assert s1.presenter_position == "left"
    assert is_avatar_eligible(s1) is True

    # 2. Scene 2 (B-Roll): Persistent Presenter with Supporting Visual
    s2 = planned.scenes[1]
    assert s2.avatar_enabled is True
    assert s2.media_type == SceneMediaType.BROLL.value
    assert s2.layout_type in (
        SceneLayoutType.PRESENTER_LEFT_VISUAL_RIGHT.value,
        SceneLayoutType.PRESENTER_PICTURE_IN_PICTURE.value,
    )
    assert is_avatar_eligible(s2) is True

    # 3. Scene 3 (Motion Visual): Persistent Presenter with Motion Graphics
    s3 = planned.scenes[2]
    assert s3.avatar_enabled is True
    assert s3.media_type == SceneMediaType.MOTION_VISUAL.value
    assert s3.layout_type in (
        SceneLayoutType.PRESENTER_RIGHT_VISUAL_LEFT.value,
        SceneLayoutType.PRESENTER_LEFT_VISUAL_RIGHT.value,
    )
    assert is_avatar_eligible(s3) is True

    # 4. Outro Scene: Centered Presenter Studio
    s4 = planned.scenes[3]
    assert s4.avatar_enabled is True
    assert s4.layout_type == SceneLayoutType.PRESENTER_CENTER_WITH_OVERLAYS.value
    assert is_avatar_eligible(s4) is True


def test_persistent_layout_types_eligibility():
    """Verify that all persistent layout types are in PRESENTER_ACTIVE_LAYOUTS."""
    required_layouts = {
        "presenter_left_visual_right",
        "presenter_right_visual_left",
        "presenter_picture_in_picture",
        "presenter_center_with_overlays",
    }
    for lt in required_layouts:
        assert lt in PRESENTER_ACTIVE_LAYOUTS
        scene = LocalizedScene(
            scene_id="test_sc",
            order=1,
            title="Test",
            narration="Testing persistent layouts",
            layout_type=lt,
            avatar_enabled=True,
        )
        assert is_avatar_eligible(scene) is True


def test_ffmpeg_composition_persistent_layouts(tmp_path):
    """Verify FFmpegCompositionProvider executes commands for persistent layouts."""
    composer = FFmpegCompositionProvider()

    dummy_audio = tmp_path / "audio.wav"
    dummy_audio.write_bytes(b"RIFF" + b"\x00" * 4096)
    dummy_avatar = tmp_path / "avatar.mp4"
    dummy_avatar.write_bytes(b"MOCK_AVATAR" + b"\x00" * 4096)
    dummy_motion = tmp_path / "motion.mp4"
    dummy_motion.write_bytes(b"MOCK_MOTION" + b"\x00" * 4096)

    captured_cmds = []

    def mock_ffmpeg_run(cmd, **kwargs):
        captured_cmds.append(cmd)
        out_path = Path(cmd[-1])
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"MOCK_RENDERED_MP4" + b"\x00" * 4096)
        m = MagicMock()
        m.returncode = 0
        m.stdout = ""
        m.stderr = ""
        return m

    layouts_to_test = [
        "presenter_left_visual_right",
        "presenter_right_visual_left",
        "presenter_picture_in_picture",
        "presenter_center_with_overlays",
    ]

    with patch("subprocess.run", side_effect=mock_ffmpeg_run):
        with patch("app.services.composition.ffmpeg_provider.get_video_duration", return_value=5.0):
            with patch("app.services.composition.ffmpeg_utils.probe_video_file", return_value={
                "duration": 5.0, "width": 1920, "height": 1080, "has_video": True, "has_audio": True,
                "video_codec": "h264", "audio_codec": "aac", "fps": 25.0, "bitrate": 1000000, "size_bytes": 4096
            }):
                for idx, lt in enumerate(layouts_to_test):
                    out_f = tmp_path / f"test_{lt}.mp4"
                    asset = composer.compose_scene(
                        scene_id=f"scene_{idx + 1}",
                        locale="ar-SA",
                        audio_path=dummy_audio,
                        avatar_video_path=dummy_avatar,
                        motion_video_path=dummy_motion,
                        duration_seconds=5.0,
                        output_path=out_f,
                        layout_type=lt,
                        burn_subtitles=False,
                    )
                    assert asset.status == "completed"
                    assert out_f.exists()

    assert len(captured_cmds) == 4

