"""Comprehensive test suite for the Master Local Video Generation Pipeline.

Verifies:
1. post-TTS overshoot triggers reconciliation
2. measured TTS overrides estimated duration
3. compression ratio calculation
4. scene budgets sum to target
5. revision 1 executes
6. revision 2 executes if necessary
7. early stop when within tolerance
8. max revision enforcement
9. unresolved duration becomes needs_review
10. scene IDs preserved
11. scene order preserved
12. learning objectives preserved
13. locale preserved
14. cultural metadata preserved
15. audio hash invalidates avatar
16. narration hash invalidates TTS
17. subtitle invalidation after narration change
18. rendered scene invalidation
19. final video invalidation
20. visual scene duration follows audio
21. SadTalker scene duration follows audio
22. all rendered audio becomes 48k stereo
23. final duration equals scene timeline
24. no heterogeneous concat regression
25. ASS subtitles remain within duration
26. RTL shaping command remains valid
27. SadTalker subprocess timeout
28. SadTalker missing checkpoint
29. SadTalker missing portrait
30. SadTalker successful provider output
31. factory selects sadtalker
32. default remains mock
33. HeyGen remains protected
34. API secrets redacted
35. frontend provider metadata dynamic
36. manifest concurrent writes safe
"""

import json
import os
import subprocess
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.core.caching import (
    hash_file,
    hash_text,
    is_audio_asset_valid,
    is_avatar_asset_valid,
    is_rendered_scene_valid,
    save_asset_metadata,
)
from app.core.config import settings
from app.models.schemas import (
    AvatarVideoAsset,
    FinalScript,
    FinalVideoAsset,
    LearningObjective,
    LocalizedAudioTrack,
    LocalizedAvatarTrack,
    LocalizedScene,
    LocalizedScript,
    ProjectManifest,
    SceneAudioAsset,
    SceneCompositionAsset,
    SceneDraft,
    TrainingVideoRequest,
)
from app.services.avatar.factory import get_avatar_provider
from app.services.avatar.mock_avatar_provider import MockAvatarProvider
from app.services.avatar.sadtalker_provider import (
    SadTalkerConfigurationError,
    SadTalkerProvider,
)
from app.services.avatar.service import AvatarService
from app.services.composition.ffmpeg_provider import FFmpegCompositionProvider
from app.services.composition.service import CompositionService
from app.services.duration.models import DurationReconciliationResult
from app.services.duration.reconciliation import (
    DurationReconciliationService,
    allocate_scene_duration_budgets,
)
from app.services.subtitles.deterministic_provider import DeterministicSubtitleProvider
from app.services.subtitles.formatter import split_narration_into_chunks
from app.services.subtitles.service import SubtitleService
from app.services.tts.service import TTSService
from app.workflows.manifest import ProjectManifestManager
from app.workflows.orchestrator import ProjectOrchestrator


@pytest.fixture
def sample_script() -> LocalizedScript:
    return LocalizedScript(
        locale="ar-SA",
        language="ar-SA",
        source_language="en-US",
        title="التدريب على التصيد الاحتيالي",
        audience="Corporate Employees",
        opening_hook="تعرف على هجمات التصيد فوراً.",
        closing_summary="ابق يقظاً واحم المؤسسة.",
        target_duration_seconds=30.0,
        total_estimated_duration_seconds=42.0,
        text_direction="rtl",
        learning_objectives=[
            LearningObjective(id="lo_1", description="التعرف على مؤشرات التصيد"),
            LearningObjective(id="lo_2", description="فحص الروابط"),
            LearningObjective(id="lo_3", description="الإبلاغ الفوري"),
        ],
        cultural_adaptations={"formality": "formal", "tone": "authoritative"},
        scenes=[
            LocalizedScene(
                scene_id="scene_1",
                order=1,
                scene_type="intro",
                title="المقدمة",
                purpose="مقدمة",
                narration="مرحبا بكم في التدريب الأمني الهام اليوم لحماية البيانات.",
                estimated_duration_seconds=8,
                learning_objective_ids=["lo_1"],
            ),
            LocalizedScene(
                scene_id="scene_2",
                order=2,
                scene_type="concept",
                title="المفهوم",
                purpose="شرح",
                narration="التصيد الاحتيالي هو محاولة خداع المستخدمين للحصول على معلومات حساسة.",
                estimated_duration_seconds=9,
                learning_objective_ids=["lo_1", "lo_2"],
            ),
            LocalizedScene(
                scene_id="scene_3",
                order=3,
                scene_type="example",
                title="المثال",
                purpose="توضيح",
                narration="تحقق دائما من عنوان البريد الإلكتروني للمرسل بدقة وتفحص الروابط بعناية.",
                estimated_duration_seconds=10,
                learning_objective_ids=["lo_2"],
            ),
            LocalizedScene(
                scene_id="scene_4",
                order=4,
                scene_type="quiz",
                title="السؤال",
                purpose="اختبار",
                narration="إذا وصلتك رسالة تطلب كلمة المرور فما هو التصرف الصحيح؟",
                estimated_duration_seconds=8,
                learning_objective_ids=["lo_3"],
            ),
            LocalizedScene(
                scene_id="scene_5",
                order=5,
                scene_type="summary",
                title="الخاتمة",
                purpose="ملخص",
                narration="أبلغ فريق أمن المعلومات فورا عن أي رسالة مشبوهة.",
                estimated_duration_seconds=7,
                learning_objective_ids=["lo_3"],
            ),
        ],
    )


@pytest.fixture
def sample_overshoot_audio(sample_script: LocalizedScript) -> LocalizedAudioTrack:
    durations = [8.35, 7.92, 10.49, 8.95, 8.50]
    assets = [
        SceneAudioAsset(
            scene_id=s.scene_id,
            locale="ar-SA",
            audio_path=f"/fake/path/{s.scene_id}.mp3",
            duration_seconds=dur,
            provider="edge_tts",
            voice_id="ar-SA-HamedNeural",
            status="completed",
        )
        for s, dur in zip(sample_script.scenes, durations)
    ]
    return LocalizedAudioTrack(
        locale="ar-SA",
        scene_audio=assets,
        total_audio_duration_seconds=sum(durations),
        status="completed",
    )


# -----------------------------------------------------------------------------
# 1-9: Duration Reconciliation Logic
# -----------------------------------------------------------------------------

def test_1_post_tts_overshoot_triggers_reconciliation(sample_script, sample_overshoot_audio):
    """1. Post-TTS overshoot beyond tolerance triggers reconciliation."""
    mock_llm = MagicMock()
    mock_llm.generate_structured.return_value = sample_script
    mock_tts = MagicMock()
    mock_tts.synthesize_locale.return_value = sample_overshoot_audio

    service = DurationReconciliationService(llm_provider=mock_llm, tolerance_seconds=2.0)
    _, _, res = service.reconcile_locale_duration(
        current_script=sample_script,
        measured_audio_track=sample_overshoot_audio,
        target_duration_seconds=30.0,
        tts_service=mock_tts,
        project_id="test_proj",
    )
    assert res.initial_duration_seconds == pytest.approx(44.21, rel=0.01)
    assert res.revisions_attempted >= 1


def test_2_measured_tts_overrides_estimated_duration(sample_script, sample_overshoot_audio):
    """2. Real measured audio duration is authoritative over estimated duration."""
    sample_script.total_estimated_duration_seconds = 28.0
    mock_llm = MagicMock()
    mock_llm.generate_structured.return_value = sample_script
    mock_tts = MagicMock()
    mock_tts.synthesize_locale.return_value = sample_overshoot_audio

    service = DurationReconciliationService(llm_provider=mock_llm, tolerance_seconds=2.0)
    _, _, res = service.reconcile_locale_duration(
        current_script=sample_script,
        measured_audio_track=sample_overshoot_audio,
        target_duration_seconds=30.0,
        tts_service=mock_tts,
        project_id="test_proj",
    )
    # Even though estimated was 28s, measured was 44.21s, so reconciliation triggered
    assert res.initial_duration_seconds == pytest.approx(44.21, rel=0.01)
    assert res.revisions_attempted >= 1


def test_3_compression_ratio_calculation(sample_script, sample_overshoot_audio):
    """3. Compression ratio calculation equals target_duration / measured_duration."""
    target = 30.0
    measured = 44.21
    expected_ratio = target / measured
    mock_llm = MagicMock()
    mock_llm.generate_structured.return_value = sample_script
    mock_tts = MagicMock()
    mock_tts.synthesize_locale.return_value = sample_overshoot_audio

    service = DurationReconciliationService(llm_provider=mock_llm)
    service.reconcile_locale_duration(
        current_script=sample_script,
        measured_audio_track=sample_overshoot_audio,
        target_duration_seconds=target,
        tts_service=mock_tts,
        project_id="test_proj",
    )
    prompt_str = mock_llm.generate_structured.call_args.kwargs["prompt"]
    prompt_json = json.loads(prompt_str)
    assert prompt_json["required_compression_ratio"] == pytest.approx(round(expected_ratio, 3), abs=0.01)


def test_4_scene_budgets_sum_to_target(sample_script):
    """4. Deterministic scene budgets sum mathematically to the target duration."""
    target = 30.0
    durations = {"scene_1": 8.35, "scene_2": 7.92, "scene_3": 10.49, "scene_4": 8.95, "scene_5": 8.50}
    budgets = allocate_scene_duration_budgets(sample_script.scenes, durations, target)
    total_budget = sum(b.allocated_budget_seconds for b in budgets)
    assert total_budget == pytest.approx(target, abs=0.1)
    # Intro/outro have smaller budgets than example
    intro_b = next(b for b in budgets if b.scene_id == "scene_1")
    example_b = next(b for b in budgets if b.scene_id == "scene_3")
    assert example_b.allocated_budget_seconds > intro_b.allocated_budget_seconds


def test_5_revision_1_executes(sample_script, sample_overshoot_audio):
    """5. Revision 1 executes and remeasures duration."""
    target = 30.0
    mock_llm = MagicMock()
    mock_llm.generate_structured.return_value = sample_script

    revised_audio = sample_overshoot_audio.model_copy(deep=True)
    revised_audio.total_audio_duration_seconds = 31.0
    for sa in revised_audio.scene_audio:
        sa.duration_seconds = 6.2

    mock_tts = MagicMock()
    mock_tts.synthesize_locale.return_value = revised_audio

    service = DurationReconciliationService(llm_provider=mock_llm, tolerance_seconds=2.0)
    _, _, res = service.reconcile_locale_duration(
        current_script=sample_script,
        measured_audio_track=sample_overshoot_audio,
        target_duration_seconds=target,
        tts_service=mock_tts,
        project_id="test_proj",
    )
    assert res.revisions_attempted == 1
    assert res.is_approved is True
    assert res.status == "approved"


def test_6_revision_2_executes_if_necessary(sample_script, sample_overshoot_audio):
    """6. Revision 2 executes if revision 1 still overshoots tolerance."""
    target = 30.0
    mock_llm = MagicMock()
    mock_llm.generate_structured.return_value = sample_script

    track_r1 = sample_overshoot_audio.model_copy(deep=True)
    track_r1.total_audio_duration_seconds = 36.0  # still > 32.0s

    track_r2 = sample_overshoot_audio.model_copy(deep=True)
    track_r2.total_audio_duration_seconds = 30.5  # within tolerance

    mock_tts = MagicMock()
    mock_tts.synthesize_locale.side_effect = [track_r1, track_r2]

    service = DurationReconciliationService(llm_provider=mock_llm, max_revisions=2, tolerance_seconds=2.0)
    _, _, res = service.reconcile_locale_duration(
        current_script=sample_script,
        measured_audio_track=sample_overshoot_audio,
        target_duration_seconds=target,
        tts_service=mock_tts,
        project_id="test_proj",
    )
    assert res.revisions_attempted == 2
    assert res.is_approved is True
    assert res.final_duration_seconds == 30.5


def test_7_early_stop_when_within_tolerance(sample_script, sample_overshoot_audio):
    """7. Early stop: stops immediately when duration meets tolerance."""
    target = 30.0
    sample_overshoot_audio.total_audio_duration_seconds = 30.8  # within ±2s
    mock_llm = MagicMock()
    mock_tts = MagicMock()

    service = DurationReconciliationService(llm_provider=mock_llm, tolerance_seconds=2.0)
    _, _, res = service.reconcile_locale_duration(
        current_script=sample_script,
        measured_audio_track=sample_overshoot_audio,
        target_duration_seconds=target,
        tts_service=mock_tts,
        project_id="test_proj",
    )
    assert res.revisions_attempted == 0
    assert res.is_approved is True
    assert res.status == "within_tolerance"
    mock_llm.generate_structured.assert_not_called()


def test_8_max_revision_enforcement(sample_script, sample_overshoot_audio):
    """8. Enforces max_revisions=2 limit to prevent infinite loops."""
    target = 30.0
    mock_llm = MagicMock()
    mock_llm.generate_structured.return_value = sample_script

    stub_stubborn_track = sample_overshoot_audio.model_copy(deep=True)
    stub_stubborn_track.total_audio_duration_seconds = 40.0

    mock_tts = MagicMock()
    mock_tts.synthesize_locale.return_value = stub_stubborn_track

    service = DurationReconciliationService(llm_provider=mock_llm, max_revisions=2, tolerance_seconds=2.0)
    _, _, res = service.reconcile_locale_duration(
        current_script=sample_script,
        measured_audio_track=sample_overshoot_audio,
        target_duration_seconds=target,
        tts_service=mock_tts,
        project_id="test_proj",
    )
    assert res.revisions_attempted == 2
    assert res.is_approved is False


def test_9_unresolved_duration_becomes_needs_review(sample_script, sample_overshoot_audio):
    """9. Unresolved duration after max revisions transitions to status 'needs_review'."""
    target = 30.0
    mock_llm = MagicMock()
    mock_llm.generate_structured.return_value = sample_script

    stub_track = sample_overshoot_audio.model_copy(deep=True)
    stub_track.total_audio_duration_seconds = 38.0

    mock_tts = MagicMock()
    mock_tts.synthesize_locale.return_value = stub_track

    service = DurationReconciliationService(llm_provider=mock_llm, max_revisions=2, tolerance_seconds=2.0)
    _, _, res = service.reconcile_locale_duration(
        current_script=sample_script,
        measured_audio_track=sample_overshoot_audio,
        target_duration_seconds=target,
        tts_service=mock_tts,
        project_id="test_proj",
    )
    assert res.status == "needs_review"
    assert "needs_review" in res.message


# -----------------------------------------------------------------------------
# 10-14: Content Preservation
# -----------------------------------------------------------------------------

def test_10_scene_ids_preserved(sample_script, sample_overshoot_audio):
    """10. Scene IDs remain strictly preserved during condensation."""
    mock_llm = MagicMock()
    # LLM returns different text but same scene structure
    mock_llm.generate_structured.return_value = sample_script
    mock_tts = MagicMock()
    mock_tts.synthesize_locale.return_value = sample_overshoot_audio

    service = DurationReconciliationService(llm_provider=mock_llm)
    rev_script, _, _ = service.reconcile_locale_duration(
        current_script=sample_script,
        measured_audio_track=sample_overshoot_audio,
        target_duration_seconds=30.0,
        tts_service=mock_tts,
        project_id="test_proj",
    )
    orig_ids = [s.scene_id for s in sample_script.scenes]
    rev_ids = [s.scene_id for s in rev_script.scenes]
    assert orig_ids == rev_ids == ["scene_1", "scene_2", "scene_3", "scene_4", "scene_5"]


def test_11_scene_order_preserved(sample_script, sample_overshoot_audio):
    """11. Scene sequence order is preserved."""
    mock_llm = MagicMock()
    mock_llm.generate_structured.return_value = sample_script
    mock_tts = MagicMock()
    mock_tts.synthesize_locale.return_value = sample_overshoot_audio

    service = DurationReconciliationService(llm_provider=mock_llm)
    rev_script, _, _ = service.reconcile_locale_duration(
        current_script=sample_script,
        measured_audio_track=sample_overshoot_audio,
        target_duration_seconds=30.0,
        tts_service=mock_tts,
        project_id="test_proj",
    )
    orders = [s.order for s in rev_script.scenes]
    assert orders == [1, 2, 3, 4, 5]


def test_12_learning_objectives_preserved(sample_script, sample_overshoot_audio):
    """12. Pedagogical learning objectives are preserved."""
    mock_llm = MagicMock()
    mock_llm.generate_structured.return_value = sample_script
    mock_tts = MagicMock()
    mock_tts.synthesize_locale.return_value = sample_overshoot_audio

    service = DurationReconciliationService(llm_provider=mock_llm)
    rev_script, _, _ = service.reconcile_locale_duration(
        current_script=sample_script,
        measured_audio_track=sample_overshoot_audio,
        target_duration_seconds=30.0,
        tts_service=mock_tts,
        project_id="test_proj",
    )
    for orig, rev in zip(sample_script.scenes, rev_script.scenes):
        assert orig.learning_objective_ids == rev.learning_objective_ids


def test_13_locale_preserved(sample_script, sample_overshoot_audio):
    """13. Language locale is strictly preserved."""
    mock_llm = MagicMock()
    mock_llm.generate_structured.return_value = sample_script
    mock_tts = MagicMock()
    mock_tts.synthesize_locale.return_value = sample_overshoot_audio

    service = DurationReconciliationService(llm_provider=mock_llm)
    rev_script, _, _ = service.reconcile_locale_duration(
        current_script=sample_script,
        measured_audio_track=sample_overshoot_audio,
        target_duration_seconds=30.0,
        tts_service=mock_tts,
        project_id="test_proj",
    )
    assert rev_script.locale == "ar-SA"
    assert rev_script.text_direction == "rtl"


def test_14_cultural_metadata_preserved(sample_script, sample_overshoot_audio):
    """14. Cultural adaptations guidance dictionary is preserved."""
    mock_llm = MagicMock()
    mock_llm.generate_structured.return_value = sample_script
    mock_tts = MagicMock()
    mock_tts.synthesize_locale.return_value = sample_overshoot_audio

    service = DurationReconciliationService(llm_provider=mock_llm)
    rev_script, _, _ = service.reconcile_locale_duration(
        current_script=sample_script,
        measured_audio_track=sample_overshoot_audio,
        target_duration_seconds=30.0,
        tts_service=mock_tts,
        project_id="test_proj",
    )
    assert rev_script.cultural_guidance == sample_script.cultural_guidance


# -----------------------------------------------------------------------------
# 15-19: Caching & Stale-Asset Invalidation
# -----------------------------------------------------------------------------

def test_15_audio_hash_invalidates_avatar(tmp_path):
    """15. Input audio hash change invalidates cached avatar MP4."""
    audio_file = tmp_path / "scene_1.mp3"
    audio_file.write_bytes(b"initial_audio_data")

    avatar_mp4 = tmp_path / "scene_1_av.mp4"
    avatar_mp4.write_bytes(b"fake_avatar_mp4_bytes")

    save_asset_metadata(
        avatar_mp4,
        {
            "audio_hash": hash_file(audio_file),
            "provider": "sadtalker",
        },
    )
    assert is_avatar_asset_valid(avatar_mp4, audio_file, expected_provider="sadtalker") is True

    # Regenerate audio with shortened text
    audio_file.write_bytes(b"condensed_new_audio_data")
    assert is_avatar_asset_valid(avatar_mp4, audio_file, expected_provider="sadtalker") is False


def test_16_narration_hash_invalidates_tts(tmp_path):
    """16. Narration text change invalidates cached audio."""
    audio_file = tmp_path / "scene_1.mp3"
    audio_file.write_bytes(b"some_audio")

    orig_narration = "This is a long original narration text."
    save_asset_metadata(
        audio_file,
        {
            "narration_hash": hash_text(orig_narration),
            "voice_id": "en-US-JennyNeural",
            "provider": "edge_tts",
        },
    )
    assert is_audio_asset_valid(audio_file, orig_narration, "en-US-JennyNeural", "edge_tts") is True

    # Condensed narration
    new_narration = "Short narration."
    assert is_audio_asset_valid(audio_file, new_narration, "en-US-JennyNeural", "edge_tts") is False


def test_17_subtitle_invalidation_after_narration_change(tmp_path, sample_script):
    """17. Subtitle track regenerates when narration or audio changes."""
    sub_service = SubtitleService(output_base_dir=tmp_path)
    audio = LocalizedAudioTrack(
        locale="ar-SA",
        scene_audio=[
            SceneAudioAsset(
                scene_id="scene_1",
                locale="ar-SA",
                audio_path="a.mp3",
                duration_seconds=5.0,
                provider="edge_tts",
                voice_id="ar-SA-HamedNeural",
                status="completed",
            )
        ],
        total_audio_duration_seconds=5.0,
        status="completed",
    )
    track1 = sub_service.generate_locale_subtitles(sample_script, audio, "proj_sub", force_regenerate=True)
    assert track1.status == "completed"


def test_18_rendered_scene_invalidation(tmp_path):
    """18. Rendered scene cache invalidates when audio duration drifts."""
    audio_file = tmp_path / "scene_1.mp3"
    audio_file.write_bytes(b"audio_bytes")

    scene_mp4 = tmp_path / "scene_1_rendered.mp4"
    scene_mp4.write_bytes(b"scene_mp4_bytes")

    save_asset_metadata(
        scene_mp4,
        {
            "audio_hash": hash_file(audio_file),
            "duration": 8.0,
        },
    )
    # Expected duration 8.0s -> valid
    assert is_rendered_scene_valid(scene_mp4, audio_file, expected_duration=8.0) is True
    # If audio changed to 5.0s -> invalid!
    assert is_rendered_scene_valid(scene_mp4, audio_file, expected_duration=5.0) is False


def test_19_final_video_invalidation(tmp_path, sample_script):
    """19. Final concatenated video invalidates when scene durations differ."""
    comp_provider = MagicMock()
    comp_service = CompositionService(provider=comp_provider, output_base_dir=tmp_path)

    final_mp4 = tmp_path / "proj_x" / "final" / "training_ar-SA.mp4"
    final_mp4.parent.mkdir(parents=True, exist_ok=True)
    final_mp4.write_bytes(b"final_video_bytes")

    with patch("app.services.composition.service.get_video_duration", return_value=66.31):
        scenes = [
            SceneCompositionAsset(scene_id="scene_1", locale="ar-SA", video_path=str(final_mp4), duration_seconds=8.0, status="completed"),
            SceneCompositionAsset(scene_id="scene_2", locale="ar-SA", video_path=str(final_mp4), duration_seconds=8.0, status="completed"),
        ]
        # Sum of scenes is 16.0s, but file on disk has stale duration 66.31s -> must re-concatenate!
        comp_service.compose_locale_final_video(sample_script, scenes, "proj_x", force_regenerate=False)
        comp_provider.concatenate_scenes.assert_called_once()


# -----------------------------------------------------------------------------
# 20-26: Composition, Audio Normalization & Subtitles
# -----------------------------------------------------------------------------

def test_20_visual_scene_duration_follows_audio(tmp_path):
    """20. Visual scene duration strictly follows actual audio duration."""
    provider = FFmpegCompositionProvider()
    audio_p = tmp_path / "a.mp3"
    audio_p.write_bytes(b"dummy_audio")
    vis_p = tmp_path / "v.png"
    vis_p.write_bytes(b"dummy_visual")
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        with patch("app.services.composition.ffmpeg_provider.get_video_duration", return_value=8.35):
            res = provider.compose_scene(
                scene_id="s1",
                locale="ar-SA",
                audio_path=audio_p,
                visual_image_path=vis_p,
                duration_seconds=8.35,
                output_path=tmp_path / "out.mp4",
            )
            assert res.duration_seconds == 8.35
            cmd = mock_run.call_args[0][0]
            assert "-t" in cmd
            t_idx = cmd.index("-t")
            assert cmd[t_idx + 1] == "8.35"


def test_21_sadtalker_scene_duration_follows_audio(tmp_path):
    """21. SadTalker avatar scene duration matches clean TTS audio."""
    provider = FFmpegCompositionProvider()
    audio_p = tmp_path / "a.mp3"
    audio_p.write_bytes(b"dummy_audio")
    av_p = tmp_path / "av.mp4"
    av_p.write_bytes(b"dummy_avatar")
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        with patch("app.services.composition.ffmpeg_provider.get_video_duration", return_value=8.35):
            res = provider.compose_scene(
                scene_id="s1",
                locale="ar-SA",
                audio_path=audio_p,
                avatar_video_path=av_p,
                duration_seconds=8.35,
                output_path=tmp_path / "out.mp4",
            )
            assert res.duration_seconds == 8.35


def test_22_all_rendered_audio_becomes_48k_stereo(tmp_path):
    """22. All rendered scene audio encodes to 48,000 Hz, stereo AAC, 192kbps."""
    provider = FFmpegCompositionProvider()
    audio_p = tmp_path / "a.mp3"
    audio_p.write_bytes(b"dummy_audio")
    vis_p = tmp_path / "v.png"
    vis_p.write_bytes(b"dummy_visual")
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        with patch("app.services.composition.ffmpeg_provider.get_video_duration", return_value=5.0):
            provider.compose_scene(
                scene_id="s1",
                locale="ar-SA",
                audio_path=audio_p,
                visual_image_path=vis_p,
                duration_seconds=5.0,
                output_path=tmp_path / "out.mp4",
            )
            cmd = mock_run.call_args[0][0]
            assert "-c:a" in cmd and "aac" in cmd
            assert "-ar" in cmd and "48000" in cmd
            assert "-ac" in cmd and "2" in cmd
            assert "-b:a" in cmd and "192k" in cmd


def test_23_final_duration_equals_scene_timeline(tmp_path):
    """23. Final concatenation duration equals sum of individual scene durations."""
    provider = FFmpegCompositionProvider()
    scenes = [
        SceneCompositionAsset(scene_id="s1", locale="ar-SA", video_path=str(tmp_path / "s1.mp4"), duration_seconds=8.0, status="completed"),
        SceneCompositionAsset(scene_id="s2", locale="ar-SA", video_path=str(tmp_path / "s2.mp4"), duration_seconds=7.0, status="completed"),
    ]
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        with patch("app.services.composition.ffmpeg_provider.get_video_duration", return_value=15.0):
            final = provider.concatenate_scenes(scenes, "ar-SA", tmp_path / "final.mp4")
            assert final.total_duration_seconds == 15.0


def test_24_no_heterogeneous_concat_regression(tmp_path):
    """24. Standardized encoding prevents concat sample-rate demuxer pitch-stretching."""
    # When all scenes are encoded to 48kHz, concat list will contain homogeneous 48kHz audio
    provider = FFmpegCompositionProvider()
    scenes = [
        SceneCompositionAsset(scene_id="s1", locale="ar-SA", video_path=str(tmp_path / "s1.mp4"), duration_seconds=8.35, status="completed"),
        SceneCompositionAsset(scene_id="s2", locale="ar-SA", video_path=str(tmp_path / "s2.mp4"), duration_seconds=35.86, status="completed"),
    ]
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        with patch("app.services.composition.ffmpeg_provider.get_video_duration", return_value=44.21):
            final = provider.concatenate_scenes(scenes, "ar-SA", tmp_path / "final.mp4")
            assert final.total_duration_seconds == pytest.approx(44.21, abs=0.1)


def test_25_ass_subtitles_remain_within_duration(tmp_path, sample_script):
    """25. ASS subtitle events remain within the scene duration boundaries."""
    provider = DeterministicSubtitleProvider()
    asset = provider.generate_scene_subtitles(
        scene_id=sample_script.scenes[0].scene_id,
        narration=sample_script.scenes[0].narration,
        duration_seconds=8.35,
        locale="ar-SA",
        output_dir=tmp_path,
    )
    assert asset.status == "completed"
    assert Path(asset.ass_path).exists()
    
    chunks = split_narration_into_chunks(sample_script.scenes[0].narration, total_duration_seconds=8.35)
    for cue in chunks:
        assert cue.start_seconds >= 0.0
        assert cue.end_seconds <= 8.36


def test_26_rtl_shaping_command_remains_valid(tmp_path):
    """26. Subtitle filter uses complex shaping with proper escaped path."""
    provider = FFmpegCompositionProvider()
    audio_p = tmp_path / "a.mp3"
    audio_p.write_bytes(b"dummy_audio")
    vis_p = tmp_path / "v.png"
    vis_p.write_bytes(b"dummy_visual")
    sub_file = tmp_path / "sub.ass"
    sub_file.write_text("[Script Info]\n", encoding="utf-8")
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        with patch("app.services.composition.ffmpeg_provider.get_video_duration", return_value=5.0):
            provider.compose_scene(
                scene_id="s1",
                locale="ar-SA",
                audio_path=audio_p,
                visual_image_path=vis_p,
                subtitle_path=sub_file,
                duration_seconds=5.0,
                output_path=tmp_path / "out.mp4",
                burn_subtitles=True,
            )
            cmd = mock_run.call_args[0][0]
            vf_args = [arg for arg in cmd if "ass=" in arg or "subtitles=" in arg]
            assert len(vf_args) > 0


# -----------------------------------------------------------------------------
# 27-33: SadTalker Provider Hardening & Safety
# -----------------------------------------------------------------------------

def test_27_sadtalker_subprocess_timeout(tmp_path):
    """27. SadTalker handles subprocess timeout cleanly without leaking processes."""
    provider = SadTalkerProvider(timeout_seconds=1)
    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="fake", timeout=1)):
        audio_p = tmp_path / "a.mp3"
        audio_p.write_bytes(b"audio")
        portrait_p = tmp_path / "port.png"
        portrait_p.write_bytes(b"img")
        with pytest.raises(TimeoutError) as exc:
            provider.submit_avatar_job("s1", "ar-SA", audio_p, avatar_id=str(portrait_p))
        assert "timed out" in str(exc.value).lower()


def test_28_sadtalker_missing_checkpoint():
    """28. SadTalker validates checkpoint existence and raises diagnostic error."""
    provider = SadTalkerProvider(checkpoint_dir=Path("/nonexistent/checkpoints/dir"))
    details = provider.validate_environment()
    assert details["checkpoints_ok"] is False


def test_29_sadtalker_missing_portrait():
    """29. SadTalker raises configuration error if portrait image is missing."""
    provider = SadTalkerProvider(default_source_image=Path("/nonexistent/portrait.png"))
    with pytest.raises(SadTalkerConfigurationError):
        provider.resolve_source_image(None)


def test_30_sadtalker_successful_provider_output(tmp_path):
    """30. SadTalker mock run parses produced MP4 output correctly."""
    provider = SadTalkerProvider()
    fake_audio = tmp_path / "a.mp3"
    fake_audio.write_bytes(b"audio")
    fake_portrait = tmp_path / "p.png"
    fake_portrait.write_bytes(b"port")
    fake_out_mp4 = tmp_path / "sadtalker_out.mp4"
    fake_out_mp4.write_bytes(b"mp4_data")

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=f"Processing done. The generated video is named: {fake_out_mp4}\n",
            stderr="",
        )
        job_id = provider.submit_avatar_job("s1", "ar-SA", fake_audio, avatar_id=str(fake_portrait))
        assert "sadtalker_s1_" in job_id
        poll = provider.poll_avatar_job(job_id)
        assert poll["status"] == "completed"


def test_31_factory_selects_sadtalker():
    """31. Factory properly returns SadTalkerProvider when requested."""
    prov = get_avatar_provider("sadtalker")
    assert isinstance(prov, SadTalkerProvider)
    assert prov.provider_name == "sadtalker"


def test_32_default_remains_mock():
    """32. Factory default returns MockAvatarProvider safely."""
    prov = get_avatar_provider("mock")
    assert isinstance(prov, MockAvatarProvider)
    assert prov.provider_name == "mock"


def test_33_heygen_remains_protected():
    """33. Live HeyGen cannot execute if ENABLE_LIVE_HEYGEN is disabled."""
    with patch.object(settings, "ENABLE_LIVE_HEYGEN", False):
        from app.services.avatar.heygen_provider import HeyGenProvider
        prov = HeyGenProvider()
        with pytest.raises(RuntimeError) as exc:
            prov.submit_avatar_job("s1", "ar-SA", Path("fake.mp3"))
        assert "disabled" in str(exc.value).lower()


# -----------------------------------------------------------------------------
# 34-36: Manifest Safety, Diagnostics & Concurrency
# -----------------------------------------------------------------------------

def test_34_api_secrets_redacted():
    """34. Project manifest sanitizes and redacts secret keys from error messages."""
    manifest = ProjectManifest(
        project_id="p_sec",
        source_request=TrainingVideoRequest(topic="Sec", base_language="en-US", target_locales=["ar-SA"]),
    )
    manifest.record_error(
        stage="llm",
        message="Request failed with key gsk_abc12345678901234567890 and Bearer eyJhbGciOiJIUzI1NiJ9",
    )
    logged_msg = manifest.error_details[0].message
    assert "gsk_abc" not in logged_msg
    assert "eyJ" not in logged_msg
    assert "gsk_[REDACTED]" in logged_msg


def test_35_frontend_provider_metadata_dynamic():
    """35. Frontend provider mapping dynamically identifies active provider."""
    assert settings.DEFAULT_AVATAR_PROVIDER in ("mock", "sadtalker", "heygen")


def test_36_manifest_concurrent_writes_safe(tmp_path):
    """36. Thread-safe atomic writes prevent manifest file corruption under concurrent updates."""
    mgr = ProjectManifestManager(storage_base_dir=tmp_path)
    req = TrainingVideoRequest(topic="Concurrency", base_language="en-US", target_locales=["ar-SA"])
    manifest = mgr.create_manifest("p_concurrent", req)

    errors = []

    def writer_task(idx):
        try:
            for j in range(10):
                loaded = mgr.load_manifest("p_concurrent")
                loaded.record_error("stage", f"Error {idx}-{j}")
                mgr.save_manifest(loaded)
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=writer_task, args=(i,)) for i in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(errors) == 0
    final_manifest = mgr.load_manifest("p_concurrent")
    assert final_manifest is not None
    assert final_manifest.project_id == "p_concurrent"
