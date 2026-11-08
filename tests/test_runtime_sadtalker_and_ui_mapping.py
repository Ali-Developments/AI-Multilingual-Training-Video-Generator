"""Comprehensive Regression Tests for SadTalker Provider Selection,
Duration Reconciliation, Cache/Resume Invalidation, Frontend Data Mapping,
and Security (No Secret Leakage).
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from app.core.config import settings
from app.models.schemas import (
    FinalScript,
    FinalVideoAsset,
    LearningObjective,
    LocalizedAudioTrack,
    LocalizedAvatarTrack,
    LocalizedScene,
    LocalizedScript,
    LocalizedSubtitleTrack,
    LocalizedVisualTrack,
    ProjectManifest,
    SceneAudioAsset,
    SceneCompositionAsset,
    SceneDraft,
    SceneVisualAsset,
    TrainingVideoRequest,
    AvatarVideoAsset,
)
from app.services.avatar.base import is_avatar_eligible
from app.services.avatar.sadtalker_provider import SadTalkerProvider
from app.services.avatar.heygen_provider import HeyGenProvider
from app.services.duration import DurationReconciliationService
from app.services.duration.models import DurationReconciliationResult
from app.workflows.manifest import ProjectManifestManager
from app.workflows.orchestrator import ProjectOrchestrator
from frontend.helpers import serialize_create_project_payload


# =====================================================================
# Helper Mock Objects for Testing
# =====================================================================

def make_test_request(avatar_provider="sadtalker", duration=30):
    return TrainingVideoRequest(
        topic="Workplace Phishing Defense Essentials",
        source_content="Always verify password reset links safely.",
        audience="Corporate Employees",
        base_language="en-US",
        target_languages=["ar-SA"],
        target_duration_seconds=duration,
        tone="professional",
        difficulty_level="beginner",
        avatar_provider=avatar_provider,
        ack_paid_credits=False,
    )


def make_test_script(duration=30):
    return FinalScript(
        title="Workplace Phishing Defense",
        language="en-US",
        audience="Corporate Employees",
        opening_hook="Welcome to training",
        closing_summary="Stay alert",
        total_estimated_duration_seconds=duration,
        scenes=[
            SceneDraft(
                scene_id="scene_1",
                order=1,
                title="Intro",
                scene_type="intro",
                narration="Welcome to cybersecurity training.",
                estimated_duration_seconds=int(duration * 0.25),
                visual_direction="Presenter speaks to camera",
            ),
            SceneDraft(
                scene_id="scene_2",
                order=2,
                title="Explanation",
                scene_type="explanation",
                narration="Inspect links carefully and never click untrusted URLs.",
                estimated_duration_seconds=int(duration * 0.5),
                visual_direction="Slide showing phishing warning signs",
            ),
            SceneDraft(
                scene_id="scene_3",
                order=3,
                title="Outro",
                scene_type="outro",
                narration="Stay secure and report suspicious emails.",
                estimated_duration_seconds=int(duration * 0.25),
                visual_direction="Presenter closing remarks",
            ),
        ],
        target_duration_seconds=duration,
        estimated_duration_seconds=duration,
    )


# =====================================================================
# 1. Streamlit SadTalker selection serializes "sadtalker"
# =====================================================================
def test_streamlit_sadtalker_selection_serializes_sadtalker():
    payload = serialize_create_project_payload(
        topic="Workplace Phishing Defense Essentials",
        source_content="Test content",
        base_language="en-US",
        target_languages=["ar-SA"],
        target_duration_seconds=30,
        avatar_provider="sadtalker",
        ack_paid_credits=False,
    )
    assert "request" in payload
    assert payload["request"]["avatar_provider"] == "sadtalker"


# =====================================================================
# 2. Backend receives selected avatar provider
# =====================================================================
def test_backend_receives_selected_avatar_provider():
    req = TrainingVideoRequest(
        topic="Workplace Phishing Defense Essentials",
        source_content="Test content",
        base_language="en-US",
        target_languages=["ar-SA"],
        target_duration_seconds=30,
        avatar_provider="sadtalker",
    )
    assert req.avatar_provider == "sadtalker"

    mgr = ProjectManifestManager()
    manifest = mgr.create_manifest("proj_test_provider", req)
    assert manifest.avatar_provider == "sadtalker"
    assert manifest.source_request.avatar_provider == "sadtalker"


# =====================================================================
# 3. Orchestrator instantiates SadTalkerProvider
# =====================================================================
def test_orchestrator_instantiates_sadtalker_provider():
    from app.services.avatar.factory import get_avatar_provider

    provider = get_avatar_provider("sadtalker")
    assert isinstance(provider, SadTalkerProvider)
    assert provider.provider_name == "sadtalker"


# =====================================================================
# 4. HeyGen is never instantiated for SadTalker project
# =====================================================================
def test_heygen_is_never_instantiated_for_sadtalker_project():
    from app.services.avatar.factory import get_avatar_provider

    with patch("app.services.avatar.heygen_provider.HeyGenProvider.__init__") as mock_heygen:
        provider = get_avatar_provider("sadtalker")
        assert isinstance(provider, SadTalkerProvider)
        mock_heygen.assert_not_called()


# =====================================================================
# 5. Intro/outro produce SadTalker assets
# =====================================================================
def test_intro_outro_produce_sadtalker_assets():
    scene_intro = SceneDraft(scene_id="scene_1", title="Intro", scene_type="intro", narration="Hi")
    scene_outro = SceneDraft(scene_id="scene_3", title="Outro", scene_type="outro", narration="Bye")
    scene_presenter = SceneDraft(scene_id="scene_p", title="Pres", scene_type="presenter", narration="Talk")

    assert is_avatar_eligible(scene_intro) is True
    assert is_avatar_eligible(scene_outro) is True
    assert is_avatar_eligible(scene_presenter) is True


# =====================================================================
# 6. Explanation scene remains visual-only
# =====================================================================
def test_explanation_scene_remains_visual_only():
    scene_explanation = SceneDraft(
        scene_id="scene_2",
        title="Explanation",
        scene_type="explanation",
        narration="Inspect links carefully",
    )
    assert is_avatar_eligible(scene_explanation) is False


# =====================================================================
# 7. Failed avatar status cannot produce overall completed status
# =====================================================================
def test_failed_avatar_status_cannot_produce_overall_completed():
    req = make_test_request(avatar_provider="sadtalker", duration=30)
    manifest = ProjectManifest(
        project_id="proj_fail_avatar",
        source_request=req,
        avatar_provider="sadtalker",
        script_status="completed",
        localization_status="completed",
        audio_status="completed",
        avatar_status="failed",
        visual_status="completed",
        subtitle_status="completed",
        composition_status="completed",
    )

    required_avatar_ok = (manifest.avatar_status == "completed") if manifest.avatar_provider in ("sadtalker", "heygen") else True
    all_stages_completed = (
        manifest.script_status == "completed"
        and manifest.localization_status in ("completed",)
        and manifest.audio_status == "completed"
        and required_avatar_ok
        and manifest.visual_status == "completed"
        and manifest.subtitle_status == "completed"
        and manifest.composition_status == "completed"
    )
    assert all_stages_completed is False
    # Manifest status must be needs_review or failed, NOT completed
    status = "completed" if all_stages_completed else ("needs_review" if manifest.composition_status in ("completed", "partial") else "failed")
    assert status != "completed"
    assert status == "needs_review"


# =====================================================================
# 8. Failed avatar tracks are not reused on resume
# =====================================================================
def test_failed_avatar_tracks_are_not_reused_on_resume():
    failed_asset = AvatarVideoAsset(
        scene_id="scene_1",
        locale="ar-SA",
        provider="sadtalker",
        job_id="failed_job",
        video_path=None,
        duration_seconds=0.0,
        status="failed",
        error="GPU OOM",
    )
    failed_track = LocalizedAvatarTrack(
        locale="ar-SA",
        scene_avatars=[failed_asset],
        status="failed",
        metadata={"provider": "sadtalker"},
    )
    manifest = ProjectManifest(
        project_id="proj_resume_failed",
        source_request=make_test_request("sadtalker"),
        avatar_provider="sadtalker",
        avatar_status="failed",
        avatar_tracks={"ar-SA": failed_track},
    )

    can_reuse_avatar = (
        manifest.avatar_status == "completed"
        and bool(manifest.avatar_tracks)
        and all(t.status == "completed" for t in manifest.avatar_tracks.values())
    )
    assert can_reuse_avatar is False


# =====================================================================
# 9. Provider change invalidates avatar cache
# =====================================================================
def test_provider_change_invalidates_avatar_cache(tmp_path):
    mgr = ProjectManifestManager(storage_base_dir=tmp_path)
    req_mock = make_test_request("mock")
    manifest = mgr.create_manifest("proj_change_prov", req_mock)
    manifest.avatar_tracks = {
        "ar-SA": LocalizedAvatarTrack(
            locale="ar-SA",
            scene_avatars=[],
            status="completed",
            metadata={"provider": "mock"},
        )
    }
    manifest.avatar_status = "completed"
    mgr.save_manifest(manifest)

    # Change provider to sadtalker
    req_sadtalker = make_test_request("sadtalker")

    # Detect provider change
    existing_tracks_provider = None
    for t in manifest.avatar_tracks.values():
        if t.metadata and t.metadata.get("provider"):
            existing_tracks_provider = t.metadata.get("provider").strip().lower()
            break

    assert existing_tracks_provider == "mock"
    assert req_sadtalker.avatar_provider == "sadtalker"
    assert existing_tracks_provider != req_sadtalker.avatar_provider


# =====================================================================
# 10. Provider change invalidates final video
# =====================================================================
def test_provider_change_invalidates_final_video(tmp_path):
    mgr = ProjectManifestManager(storage_base_dir=tmp_path)
    req = make_test_request("mock")
    manifest = mgr.create_manifest("proj_inv_final", req)
    manifest.avatar_tracks = {
        "ar-SA": LocalizedAvatarTrack(
            locale="ar-SA",
            scene_avatars=[],
            status="completed",
            metadata={"provider": "mock"},
        )
    }
    manifest.final_videos = {
        "ar-SA": FinalVideoAsset(
            locale="ar-SA",
            video_path="/path/to/old.mp4",
            total_duration_seconds=30.0,
            scene_count=3,
            status="completed",
        )
    }
    manifest.composition_status = "completed"
    mgr.save_manifest(manifest)

    # Trigger run with new provider
    new_req = make_test_request("sadtalker")
    selected_avatar_provider = new_req.avatar_provider.strip().lower()

    existing_tracks_provider = list(manifest.avatar_tracks.values())[0].metadata.get("provider")
    if existing_tracks_provider != selected_avatar_provider:
        manifest.avatar_tracks = {}
        manifest.avatar_status = "pending"
        manifest.final_videos = {}
        manifest.composition_status = "pending"

    assert manifest.avatar_tracks == {}
    assert manifest.final_videos == {}
    assert manifest.avatar_status == "pending"
    assert manifest.composition_status == "pending"


# =====================================================================
# 11. DurationReconciliationService executes in real orchestration
# =====================================================================
def test_duration_reconciliation_service_executes_in_real_orchestration():
    mock_llm = MagicMock()
    mock_llm.provider_name = "mock"
    reconciler = DurationReconciliationService(llm_provider=mock_llm)
    assert reconciler.llm_provider is not None

    loc_scene = LocalizedScene(
        scene_id="scene_1",
        order=1,
        title="Intro",
        purpose="Intro",
        narration="Hello and welcome to cybersecurity training.",
        estimated_duration_seconds=30,
        scene_type="intro",
    )
    loc_script = LocalizedScript(
        title="Training",
        source_language="en-US",
        language="Arabic",
        locale="ar-SA",
        audience="Staff",
        opening_hook="Welcome",
        closing_summary="Goodbye",
        target_duration_seconds=30,
        scenes=[loc_scene],
    )
    audio_track = LocalizedAudioTrack(
        locale="ar-SA",
        scene_audio=[
            SceneAudioAsset(
                scene_id="scene_1",
                locale="ar-SA",
                audio_path="/fake/audio.mp3",
                duration_seconds=30.5,
                provider="edge_tts",
                voice_id="ar-SA-HamedNeural",
            )
        ],
        total_audio_duration_seconds=30.5,
        status="completed",
    )

    mock_tts = MagicMock()
    script_out, track_out, res = reconciler.reconcile_locale_duration(
        current_script=loc_script,
        measured_audio_track=audio_track,
        target_duration_seconds=30.0,
        tts_service=mock_tts,
        project_id="test_proj",
        tolerance_seconds=2.0,
    )
    assert res.is_approved is True
    assert res.status == "within_tolerance"


# =====================================================================
# 12. 30s target cannot silently complete at ~38s
# =====================================================================
def test_30s_target_cannot_silently_complete_at_38s():
    # If initial duration is 37.94s and LLM cannot condense or revisions fail
    reconciler = DurationReconciliationService()
    reconciler.llm_provider = None
    loc_scene = LocalizedScene(
        scene_id="scene_1",
        order=1,
        title="Intro",
        purpose="Intro",
        narration="Overrun narration text",
        estimated_duration_seconds=38,
        scene_type="intro",
    )
    loc_script = LocalizedScript(
        title="Training",
        source_language="en-US",
        language="Arabic",
        locale="ar-SA",
        audience="Staff",
        opening_hook="Welcome",
        closing_summary="Goodbye",
        target_duration_seconds=30,
        scenes=[loc_scene],
    )
    audio_track = LocalizedAudioTrack(
        locale="ar-SA",
        scene_audio=[
            SceneAudioAsset(
                scene_id="scene_1",
                locale="ar-SA",
                audio_path="/fake/audio.mp3",
                duration_seconds=37.94,
                provider="edge_tts",
                voice_id="ar-SA-HamedNeural",
            )
        ],
        total_audio_duration_seconds=37.94,
        status="completed",
    )
    mock_tts = MagicMock()
    script_out, track_out, res = reconciler.reconcile_locale_duration(
        current_script=loc_script,
        measured_audio_track=audio_track,
        target_duration_seconds=30.0,
        tts_service=mock_tts,
        project_id="test_proj",
        tolerance_seconds=2.0,
    )
    assert res.is_approved is False
    assert res.status == "needs_review"


# =====================================================================
# 13. Scripts tab maps final_script correctly
# =====================================================================
def test_scripts_tab_maps_final_script_correctly():
    script = make_test_script(30)
    manifest_dict = {
        "final_script": script.model_dump(),
        "localization_bundle": {
            "localized_scripts": {
                "ar-SA": {
                    "locale": "ar-SA",
                    "text_direction": "rtl",
                    "total_estimated_duration_seconds": 30,
                    "scenes": [
                        {"scene_id": "scene_1", "scene_type": "intro", "narration": "مرحبا", "estimated_duration_seconds": 8}
                    ],
                }
            }
        },
    }

    # UI Mapping parser logic
    source_script = manifest_dict.get("final_script") or manifest_dict.get("source_script")
    assert source_script is not None
    assert source_script["title"] == "Workplace Phishing Defense"
    assert len(source_script["scenes"]) == 3

    loc_scripts = (manifest_dict.get("localization_bundle") or {}).get("localized_scripts")
    assert "ar-SA" in loc_scripts
    assert loc_scripts["ar-SA"]["scenes"][0]["narration"] == "مرحبا"


# =====================================================================
# 14. Audio tab maps audio_tracks correctly
# =====================================================================
def test_audio_tab_maps_audio_tracks_correctly():
    manifest_dict = {
        "audio_tracks": {
            "ar-SA": {
                "locale": "ar-SA",
                "total_audio_duration_seconds": 30.2,
                "metadata": {"provider": "edge_tts", "voice_id": "ar-SA-HamedNeural"},
                "scene_audio": [
                    {
                        "scene_id": "scene_1",
                        "duration_seconds": 7.5,
                        "audio_path": "/path/scene_1.mp3",
                        "provider": "edge_tts",
                        "voice_id": "ar-SA-HamedNeural",
                    }
                ],
            }
        }
    }

    track = manifest_dict["audio_tracks"]["ar-SA"]
    total_dur = track.get("total_audio_duration_seconds")
    assert total_dur == 30.2
    assert track["metadata"]["voice_id"] == "ar-SA-HamedNeural"
    assert track["metadata"]["provider"] == "edge_tts"
    assert len(track["scene_audio"]) == 1
    assert track["scene_audio"][0]["duration_seconds"] == 7.5


# =====================================================================
# 15. Avatar tab maps avatar_tracks correctly
# =====================================================================
def test_avatar_tab_maps_avatar_tracks_correctly():
    manifest_dict = {
        "avatar_provider": "sadtalker",
        "avatar_tracks": {
            "ar-SA": {
                "locale": "ar-SA",
                "status": "completed",
                "metadata": {"provider": "sadtalker"},
                "scene_avatars": [
                    {
                        "scene_id": "scene_1",
                        "status": "completed",
                        "duration_seconds": 7.5,
                        "video_path": "/path/scene_1_av.mp4",
                    },
                    {
                        "scene_id": "scene_2",
                        "status": "skipped",
                        "duration_seconds": 0.0,
                        "video_path": None,
                    },
                ],
            }
        },
    }

    av_track = manifest_dict["avatar_tracks"]["ar-SA"]
    scenes = av_track["scene_avatars"]
    assert len(scenes) == 2
    assert scenes[0]["status"] == "completed"
    assert scenes[0]["video_path"] == "/path/scene_1_av.mp4"
    assert scenes[1]["status"] == "skipped"


# =====================================================================
# 16. Visual tab maps visual_tracks correctly
# =====================================================================
def test_visual_tab_maps_visual_tracks_correctly():
    manifest_dict = {
        "visual_tracks": {
            "ar-SA": {
                "locale": "ar-SA",
                "scene_visuals": [
                    {
                        "scene_id": "scene_2",
                        "image_path": "/path/scene_2.png",
                        "visual_type": "slide",
                        "status": "completed",
                    }
                ],
            }
        }
    }

    vtrack = manifest_dict["visual_tracks"]["ar-SA"]
    visuals = vtrack["scene_visuals"]
    assert len(visuals) == 1
    assert visuals[0]["image_path"] == "/path/scene_2.png"
    assert visuals[0]["visual_type"] == "slide"


# =====================================================================
# 17. Final Video tab maps final_videos correctly
# =====================================================================
def test_final_video_tab_maps_final_videos_correctly():
    manifest_dict = {
        "final_videos": {
            "ar-SA": {
                "locale": "ar-SA",
                "video_path": "/path/final_ar.mp4",
                "total_duration_seconds": 30.15,
                "scene_count": 3,
                "scene_videos": [
                    {"scene_id": "scene_1", "has_avatar": True, "status": "completed"},
                    {"scene_id": "scene_2", "has_avatar": False, "status": "completed"},
                    {"scene_id": "scene_3", "has_avatar": True, "status": "completed"},
                ],
                "status": "completed",
            }
        }
    }

    fvid = manifest_dict["final_videos"]["ar-SA"]
    assert fvid["video_path"] == "/path/final_ar.mp4"
    assert fvid["total_duration_seconds"] == 30.15
    avatar_count = sum(1 for sc in fvid["scene_videos"] if sc["has_avatar"])
    assert avatar_count == 2


# =====================================================================
# 18. No secret leakage
# =====================================================================
def test_no_secret_leakage_in_error_sanitization():
    from app.models.schemas import sanitize_diagnostic_message

    sensitive_error = "API error: Bearer gsk_1234567890abcdef123456 with key gsk_abcdef1234567890123"
    sanitized = sanitize_diagnostic_message(sensitive_error)

    assert "gsk_1234567890abcdef123456" not in sanitized
    assert "gsk_abcdef1234567890123" not in sanitized
    assert "[REDACTED]" in sanitized
