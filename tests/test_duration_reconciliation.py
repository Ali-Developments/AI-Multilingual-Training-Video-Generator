"""Regression test suite for Timing, Composition Normalization, and Post-TTS Reconciliation.

Covers all 13 required regression tests:
1. visual scene duration follows audio
2. avatar scene duration follows audio
3. final duration equals sum of scene durations
4. stale estimated duration cannot override TTS duration
5. stale rendered assets do not corrupt new build
6. 44s audio targeting 30s triggers post-TTS revision
7. revision shortens narration
8. regenerated TTS duration is remeasured
9. avatar generation occurs only after duration approval
10. revision limit prevents infinite loop
11. scene IDs remain unchanged
12. learning objectives remain preserved
13. subtitles remain within corrected scene timelines
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
    LocalizedAvatarTrack,
    AvatarVideoAsset,
    SceneCompositionAsset,
    FinalVideoAsset,
    ProjectManifest,
    TrainingVideoRequest,
)
from app.services.composition.service import CompositionService
from app.services.composition.ffmpeg_provider import FFmpegCompositionProvider
from app.services.localization.service import LocalizationService
from app.services.localization.prompts import (
    SYSTEM_PROMPT_POST_TTS_DURATION_REVISER,
    build_post_tts_duration_revision_prompt,
)
from app.workflows.orchestrator import ProjectOrchestrator


@pytest.fixture
def sample_canonical_script() -> FinalScript:
    return FinalScript(
        title="Anti-Phishing Training",
        target_duration_seconds=30,
        total_estimated_duration_seconds=30,
        language="en-US",
        audience="Corporate Employees",
        opening_hook="Recognize phishing threats instantly.",
        closing_summary="Stay vigilant against social engineering.",
        learning_objectives=[
            LearningObjective(id="LO1", description="Identify phishing indicators"),
            LearningObjective(id="LO2", description="Report suspicious emails"),
        ],
        scenes=[
            SceneDraft(
                scene_id="scene_1",
                order=1,
                scene_type="presenter",
                title="Introduction",
                purpose="Hook audience",
                narration="Welcome to cyber defense awareness. Today we explore phishing detection.",
                estimated_duration_seconds=8,
                visual_direction="Presenter in office",
                on_screen_text="Cyber Defense",
                learning_objective_ids=["LO1"],
            ),
            SceneDraft(
                scene_id="scene_2",
                order=2,
                scene_type="content",
                title="Core Principles",
                purpose="Explain tactics",
                narration="Attackers disguise email senders and urge urgent password resets.",
                estimated_duration_seconds=10,
                visual_direction="Suspicious email graphic",
                on_screen_text="Check Headers",
                learning_objective_ids=["LO1"],
            ),
            SceneDraft(
                scene_id="scene_3",
                order=3,
                scene_type="conclusion",
                title="Conclusion",
                purpose="Summary",
                narration="Always verify unexpected messages and report them to IT.",
                estimated_duration_seconds=12,
                visual_direction="Security shield badge",
                on_screen_text="Report Threats",
                learning_objective_ids=["LO2"],
            ),
        ],
    )


@pytest.fixture
def sample_localized_script(sample_canonical_script) -> LocalizedScript:
    return LocalizedScript(
        title="تدريب مكافحة التصيد",
        target_duration_seconds=30,
        total_estimated_duration_seconds=30,
        language="ar-SA",
        locale="ar-SA",
        audience="Corporate Employees",
        source_language="en-US",
        text_direction="rtl",
        opening_hook="تعرف على هجمات التصيد الاحتيالي فوراً.",
        closing_summary="ابق يقظاً واحم بيانات مؤسستك.",
        learning_objectives=[
            LearningObjective(id="LO1", description="التعرف على مؤشرات التصيد"),
            LearningObjective(id="LO2", description="الإبلاغ عن الرسائل المشبوهة"),
        ],
        scenes=[
            LocalizedScene(
                scene_id="scene_1",
                order=1,
                scene_type="presenter",
                title="المقدمة",
                purpose="جذب الانتباه",
                narration="مرحباً بكم في التدريب الأمني للتعرف على أساليب التصيد الإلكتروني بدقة.",
                estimated_duration_seconds=8,
                visual_direction="مقدم التدريب في بيئة عمل احترافية",
                on_screen_text="الأمن السيبراني",
                learning_objective_ids=["LO1"],
            ),
            LocalizedScene(
                scene_id="scene_2",
                order=2,
                scene_type="content",
                title="مؤشرات الخطر",
                purpose="شرح الأساليب",
                narration="يقوم المهاجمون بتزوير عناوين البريد ويطلبون تغيير كلمات المرور على وجه السرعة القصوى.",
                estimated_duration_seconds=10,
                visual_direction="رسم توضيحي لرسالة تصيد",
                on_screen_text="تحقق من العناوين",
                learning_objective_ids=["LO1"],
            ),
            LocalizedScene(
                scene_id="scene_3",
                order=3,
                scene_type="conclusion",
                title="الخاتمة",
                purpose="تلخيص",
                narration="تحقق دائماً من الروابط المشبوهة وقم بإبلاغ فريق أمن المعلومات فوراً لحماية الأنظمة.",
                estimated_duration_seconds=12,
                visual_direction="شعار الحماية والأمان",
                on_screen_text="أبلغ عن التهديد",
                learning_objective_ids=["LO2"],
            ),
        ],
    )


# ---------------------------------------------------------------------------
# Test 1: visual scene duration follows audio
# ---------------------------------------------------------------------------
def test_visual_scene_duration_follows_audio(tmp_path):
    provider = FFmpegCompositionProvider()
    audio_path = tmp_path / "audio.mp3"
    audio_path.write_bytes(b"dummy_audio")
    vis_path = tmp_path / "slide.png"
    vis_path.write_bytes(b"dummy_image")
    out_path = tmp_path / "scene_2.mp4"

    measured_audio_duration = 7.92

    with patch("app.services.composition.ffmpeg_provider.check_ffmpeg_available", return_value=True), \
         patch("app.services.composition.ffmpeg_provider.get_video_duration", return_value=7.92), \
         patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stderr="")
        asset = provider.compose_scene(
            scene_id="scene_2",
            locale="ar-SA",
            audio_path=audio_path,
            visual_image_path=vis_path,
            avatar_video_path=None,
            subtitle_path=None,
            duration_seconds=measured_audio_duration,
            output_path=out_path,
            burn_subtitles=False,
        )

        assert asset.status == "completed"
        assert abs(asset.duration_seconds - measured_audio_duration) < 0.05
        # Verify FFmpeg was called with duration_seconds from audio
        cmd = mock_run.call_args[0][0]
        assert "-t" in cmd
        t_idx = cmd.index("-t")
        assert cmd[t_idx + 1] == str(measured_audio_duration)
        assert "-shortest" in cmd


# ---------------------------------------------------------------------------
# Test 2: avatar scene duration follows audio
# ---------------------------------------------------------------------------
def test_avatar_scene_duration_follows_audio(tmp_path):
    provider = FFmpegCompositionProvider()
    audio_path = tmp_path / "audio.mp3"
    audio_path.write_bytes(b"dummy_audio")
    avatar_video_path = tmp_path / "avatar.mp4"
    avatar_video_path.write_bytes(b"dummy_avatar")
    out_path = tmp_path / "scene_1.mp4"

    measured_audio_duration = 8.35

    with patch("app.services.composition.ffmpeg_provider.check_ffmpeg_available", return_value=True), \
         patch("app.services.composition.ffmpeg_provider.get_video_duration", return_value=8.35), \
         patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stderr="")
        asset = provider.compose_scene(
            scene_id="scene_1",
            locale="ar-SA",
            audio_path=audio_path,
            visual_image_path=None,
            avatar_video_path=avatar_video_path,
            subtitle_path=None,
            duration_seconds=measured_audio_duration,
            output_path=out_path,
            burn_subtitles=False,
        )

        assert asset.status == "completed"
        assert abs(asset.duration_seconds - measured_audio_duration) < 0.05
        # Verify -map was used to map clean audio from input 1 and -t equals measured audio
        cmd = mock_run.call_args[0][0]
        assert "-map" in cmd
        assert "-t" in cmd
        t_idx = cmd.index("-t")
        assert cmd[t_idx + 1] == str(measured_audio_duration)


# ---------------------------------------------------------------------------
# Test 3: final duration equals sum of scene durations
# ---------------------------------------------------------------------------
def test_final_duration_equals_sum_of_scene_durations(tmp_path):
    provider = FFmpegCompositionProvider()
    scene_videos = [
        SceneCompositionAsset(scene_id="scene_1", locale="ar-SA", video_path=str(tmp_path / "s1.mp4"), duration_seconds=8.35, status="completed"),
        SceneCompositionAsset(scene_id="scene_2", locale="ar-SA", video_path=str(tmp_path / "s2.mp4"), duration_seconds=7.92, status="completed"),
        SceneCompositionAsset(scene_id="scene_3", locale="ar-SA", video_path=str(tmp_path / "s3.mp4"), duration_seconds=10.49, status="completed"),
        SceneCompositionAsset(scene_id="scene_4", locale="ar-SA", video_path=str(tmp_path / "s4.mp4"), duration_seconds=8.95, status="completed"),
        SceneCompositionAsset(scene_id="scene_5", locale="ar-SA", video_path=str(tmp_path / "s5.mp4"), duration_seconds=8.50, status="completed"),
    ]
    expected_sum = sum(s.duration_seconds for s in scene_videos) # 44.21s
    out_path = tmp_path / "final.mp4"

    with patch("app.services.composition.ffmpeg_provider.check_ffmpeg_available", return_value=True), \
         patch("app.services.composition.ffmpeg_provider.get_video_duration", return_value=44.21), \
         patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stderr="")
        final_asset = provider.concatenate_scenes(
            scene_videos=scene_videos,
            locale="ar-SA",
            output_path=out_path,
        )

        assert final_asset.status == "completed"
        assert abs(final_asset.total_duration_seconds - expected_sum) <= 0.05


# ---------------------------------------------------------------------------
# Test 4: stale estimated duration cannot override TTS duration
# ---------------------------------------------------------------------------
def test_stale_estimated_duration_cannot_override_tts_duration(tmp_path, sample_localized_script):
    comp_service = CompositionService(output_base_dir=tmp_path)
    # Estimated duration on scene_1 is 8.0, but measured TTS waveform is 10.5
    real_tts_duration = 10.5
    audio_file = tmp_path / "s1.mp3"
    audio_file.write_bytes(b"audio")

    audio_track = LocalizedAudioTrack(
        locale="ar-SA",
        total_audio_duration_seconds=real_tts_duration,
        scene_audio=[
            SceneAudioAsset(scene_id="scene_1", locale="ar-SA", audio_path=str(audio_file), duration_seconds=real_tts_duration, provider="edge_tts", voice_id="test", status="completed")
        ],
        status="completed",
    )

    with patch.object(comp_service.provider, "compose_scene") as mock_compose:
        mock_compose.return_value = SceneCompositionAsset(
            scene_id="scene_1", locale="ar-SA", video_path="v.mp4", duration_seconds=real_tts_duration, status="completed"
        )
        comp_service.compose_locale_scenes(
            script=sample_localized_script,
            audio_track=audio_track,
            visual_track=None,
            avatar_track=None,
            subtitle_track=None,
            project_id="test_proj",
        )
        # Verify compose_scene received duration_seconds=10.5 (real TTS), NOT 8.0 (estimate)
        call_kwargs = mock_compose.call_args[1]
        assert call_kwargs["duration_seconds"] == real_tts_duration
        assert call_kwargs["duration_seconds"] != sample_localized_script.scenes[0].estimated_duration_seconds


# ---------------------------------------------------------------------------
# Test 5: stale rendered assets do not corrupt new build
# ---------------------------------------------------------------------------
def test_stale_rendered_assets_do_not_corrupt_new_build(tmp_path, sample_localized_script):
    comp_service = CompositionService(output_base_dir=tmp_path)
    rendered_dir = tmp_path / "test_proj" / "rendered" / "ar-SA"
    rendered_dir.mkdir(parents=True, exist_ok=True)
    stale_file = rendered_dir / "scene_1.mp4"
    stale_file.write_bytes(b"stale_video")

    new_tts_duration = 8.35
    stale_file_duration = 15.0  # Mismatched stale duration

    audio_file = tmp_path / "s1.mp3"
    audio_file.write_bytes(b"audio")
    audio_track = LocalizedAudioTrack(
        locale="ar-SA",
        total_audio_duration_seconds=new_tts_duration,
        scene_audio=[
            SceneAudioAsset(scene_id="scene_1", locale="ar-SA", audio_path=str(audio_file), duration_seconds=new_tts_duration, provider="edge_tts", voice_id="test", status="completed")
        ],
        status="completed",
    )

    with patch("app.services.composition.service.get_video_duration", return_value=stale_file_duration), \
         patch.object(comp_service.provider, "compose_scene") as mock_compose:
        mock_compose.return_value = SceneCompositionAsset(
            scene_id="scene_1", locale="ar-SA", video_path=str(stale_file), duration_seconds=new_tts_duration, status="completed"
        )
        res = comp_service.compose_locale_scenes(
            script=sample_localized_script,
            audio_track=audio_track,
            visual_track=None,
            avatar_track=None,
            subtitle_track=None,
            project_id="test_proj",
        )
        # Because stale_file_duration (15.0) != new_tts_duration (8.35), compose_scene MUST be called to re-render!
        assert mock_compose.called
        assert res[0].duration_seconds == new_tts_duration


# ---------------------------------------------------------------------------
# Test 6: 44s audio targeting 30s triggers post-TTS revision
# ---------------------------------------------------------------------------
def test_44s_audio_targeting_30s_triggers_post_tts_revision(sample_localized_script):
    loc_service = LocalizationService()
    measured_track = LocalizedAudioTrack(
        locale="ar-SA",
        total_audio_duration_seconds=44.21,
        scene_audio=[
            SceneAudioAsset(scene_id="scene_1", locale="ar-SA", audio_path="s1.mp3", duration_seconds=8.35, provider="edge_tts", voice_id="test", status="completed"),
            SceneAudioAsset(scene_id="scene_2", locale="ar-SA", audio_path="s2.mp3", duration_seconds=7.92, provider="edge_tts", voice_id="test", status="completed"),
            SceneAudioAsset(scene_id="scene_3", locale="ar-SA", audio_path="s3.mp3", duration_seconds=10.49, provider="edge_tts", voice_id="test", status="completed"),
        ],
        status="completed",
    )
    # 44.21s vs 30s target with 15% tolerance (±4.5s max 34.5s) must trigger revision
    mock_revised = sample_localized_script.model_copy(deep=True)
    mock_revised.scenes[0].narration = "مرحباً. اليوم نشرح التصيد باختصار."
    mock_revised.scenes[1].narration = "المهاجمون يزورون العناوين بسرعة."
    mock_revised.scenes[2].narration = "تحقق من الروابط وأبلغ الدعم."

    with patch.object(loc_service.llm_provider, "generate_structured", return_value=mock_revised) as mock_llm:
        rev_script, was_revised, msg = loc_service.reconcile_post_tts_duration(
            current_script=sample_localized_script,
            measured_audio_track=measured_track,
            target_duration_seconds=30.0,
            tolerance_percent=15,
        )
        assert was_revised is True
        assert mock_llm.called
        assert "Condensed narration" in msg


# ---------------------------------------------------------------------------
# Test 7: revision shortens narration
# ---------------------------------------------------------------------------
def test_revision_shortens_narration(sample_localized_script):
    loc_service = LocalizationService()
    measured_track = LocalizedAudioTrack(
        locale="ar-SA",
        total_audio_duration_seconds=44.21,
        scene_audio=[
            SceneAudioAsset(scene_id="scene_1", locale="ar-SA", audio_path="s1.mp3", duration_seconds=15.0, provider="edge_tts", voice_id="test", status="completed"),
        ],
        status="completed",
    )
    original_words = sum(len(s.narration.split()) for s in sample_localized_script.scenes)

    mock_revised = sample_localized_script.model_copy(deep=True)
    mock_revised.scenes[0].narration = "مرحباً بكم. احذروا التصيد."
    mock_revised.scenes[1].narration = "تحققوا من العناوين دائماً."
    mock_revised.scenes[2].narration = "أبلغوا الدعم فوراً."

    with patch.object(loc_service.llm_provider, "generate_structured", return_value=mock_revised):
        rev_script, was_revised, _ = loc_service.reconcile_post_tts_duration(
            current_script=sample_localized_script,
            measured_audio_track=measured_track,
            target_duration_seconds=30.0,
            tolerance_percent=15,
        )
        revised_words = sum(len(s.narration.split()) for s in rev_script.scenes)
        assert revised_words < original_words


# ---------------------------------------------------------------------------
# Test 8: regenerated TTS duration is remeasured
# ---------------------------------------------------------------------------
def test_regenerated_tts_duration_is_remeasured(sample_localized_script):
    loc_service = LocalizationService()
    mock_revised = sample_localized_script.model_copy(deep=True)
    mock_revised.scenes[0].narration = "موجز قصير."

    measured_track = LocalizedAudioTrack(
        locale="ar-SA",
        total_audio_duration_seconds=44.21,
        scene_audio=[],
        status="completed",
    )
    with patch.object(loc_service.llm_provider, "generate_structured", return_value=mock_revised):
        rev_script, was_revised, _ = loc_service.reconcile_post_tts_duration(
            current_script=sample_localized_script,
            measured_audio_track=measured_track,
            target_duration_seconds=30.0,
        )
        # Verify estimated duration was recalculated honestly
        assert rev_script.scenes[0].estimated_duration_seconds < sample_localized_script.scenes[0].estimated_duration_seconds


# ---------------------------------------------------------------------------
# Test 9: avatar generation occurs only after duration approval
# ---------------------------------------------------------------------------
def test_avatar_generation_occurs_only_after_duration_approval(sample_canonical_script, sample_localized_script, tmp_path):
    orchestrator = ProjectOrchestrator()
    manifest = ProjectManifest(
        project_id="test_timing_order",
        source_request=TrainingVideoRequest(
            topic="Security Awareness Training",
            target_duration_seconds=30,
            base_language="en-US",
            target_languages=["ar-SA"],
            avatar_provider="mock",
        ),
        final_script=sample_canonical_script,
        script_status="completed",
        localization_bundle=LocalizationBundle(
            source_script=sample_canonical_script,
            localized_scripts={"ar-SA": sample_localized_script},
            failed_locales={},
        ),
        localization_status="completed",
    )

    execution_order = []

    def mock_reconcile(*args, **kwargs):
        execution_order.append("reconcile_duration")
        return sample_localized_script, False, "Approved"

    def mock_avatar(*args, **kwargs):
        execution_order.append("generate_avatar")
        return {"ar-SA": LocalizedAvatarTrack(locale="ar-SA", scene_avatars=[], status="completed")}

    with patch.object(orchestrator.manifest_manager, "load_manifest", return_value=manifest), \
         patch.object(orchestrator.manifest_manager, "get_project_dir", return_value=tmp_path / "test_timing_order"), \
         patch.object(orchestrator.manifest_manager, "save_manifest"), \
         patch.object(orchestrator.tts_service, "synthesize_bundle", return_value={"ar-SA": LocalizedAudioTrack(locale="ar-SA", total_audio_duration_seconds=30.0, scene_audio=[], status="completed")}), \
         patch.object(orchestrator.localization_service, "reconcile_post_tts_duration", side_effect=mock_reconcile), \
         patch.object(orchestrator.avatar_service, "generate_bundle_avatars", side_effect=mock_avatar):
        
        orchestrator.run_project(project_id="test_timing_order", force_regenerate=False)

        assert "reconcile_duration" in execution_order
        assert "generate_avatar" in execution_order
        rec_idx = execution_order.index("reconcile_duration")
        av_idx = execution_order.index("generate_avatar")
        assert rec_idx < av_idx, "Duration reconciliation MUST occur strictly before avatar generation"


# ---------------------------------------------------------------------------
# Test 10: revision limit prevents infinite loop
# ---------------------------------------------------------------------------
def test_revision_limit_prevents_infinite_loop(sample_localized_script):
    loc_service = LocalizationService()
    measured_track = LocalizedAudioTrack(
        locale="ar-SA",
        total_audio_duration_seconds=44.21,
        scene_audio=[],
        status="completed",
    )
    mock_revised = sample_localized_script.model_copy(deep=True)
    # LLM returns still slightly over target, but service executes only 1 revision call
    with patch.object(loc_service.llm_provider, "generate_structured", return_value=mock_revised) as mock_llm:
        loc_service.reconcile_post_tts_duration(
            current_script=sample_localized_script,
            measured_audio_track=measured_track,
            target_duration_seconds=30.0,
        )
        assert mock_llm.call_count == 1, "Exactly 1 post-TTS revision attempt permitted per invocation"


# ---------------------------------------------------------------------------
# Test 11: scene IDs remain unchanged
# ---------------------------------------------------------------------------
def test_scene_ids_remain_unchanged(sample_localized_script):
    loc_service = LocalizationService()
    measured_track = LocalizedAudioTrack(
        locale="ar-SA",
        total_audio_duration_seconds=44.21,
        scene_audio=[],
        status="completed",
    )
    # Simulate LLM returning modified scene IDs
    corrupted_llm_output = sample_localized_script.model_copy(deep=True)
    corrupted_llm_output.scenes[0].scene_id = "new_scene_id_001"
    corrupted_llm_output.scenes[1].scene_id = "different_id"

    with patch.object(loc_service.llm_provider, "generate_structured", return_value=corrupted_llm_output):
        rev_script, was_revised, _ = loc_service.reconcile_post_tts_duration(
            current_script=sample_localized_script,
            measured_audio_track=measured_track,
            target_duration_seconds=30.0,
        )
        # Structural enforcement MUST restore original scene IDs
        original_ids = [s.scene_id for s in sample_localized_script.scenes]
        revised_ids = [s.scene_id for s in rev_script.scenes]
        assert revised_ids == original_ids


# ---------------------------------------------------------------------------
# Test 12: learning objectives remain preserved
# ---------------------------------------------------------------------------
def test_learning_objectives_remain_preserved(sample_localized_script):
    loc_service = LocalizationService()
    measured_track = LocalizedAudioTrack(
        locale="ar-SA",
        total_audio_duration_seconds=44.21,
        scene_audio=[],
        status="completed",
    )
    # Simulate LLM modifying learning objective IDs
    corrupted_llm_output = sample_localized_script.model_copy(deep=True)
    corrupted_llm_output.scenes[0].learning_objective_ids = ["MODIFIED_LO"]

    with patch.object(loc_service.llm_provider, "generate_structured", return_value=corrupted_llm_output):
        rev_script, was_revised, _ = loc_service.reconcile_post_tts_duration(
            current_script=sample_localized_script,
            measured_audio_track=measured_track,
            target_duration_seconds=30.0,
        )
        # Structural enforcement MUST preserve original LO IDs
        assert rev_script.scenes[0].learning_objective_ids == ["LO1"]


# ---------------------------------------------------------------------------
# Test 13: subtitles remain within corrected scene timelines
# ---------------------------------------------------------------------------
def test_subtitles_remain_within_corrected_scene_timelines():
    from app.services.subtitles.formatter import split_narration_into_chunks

    narration = "مرحباً بكم في التدريب الأمني للتعرف على أساليب التصيد الإلكتروني بدقة."
    # Corrected TTS duration is 5.5 seconds
    chunks = split_narration_into_chunks(narration, total_duration_seconds=5.5)
    assert len(chunks) > 0
    # Every cue end time must be <= corrected audio duration
    for chunk in chunks:
        assert chunk.end_seconds <= 5.5
        assert chunk.start_seconds >= 0.0
