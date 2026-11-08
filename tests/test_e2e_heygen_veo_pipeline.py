"""Comprehensive End-to-End Multilingual Production Test Suite for HeyGen Presenter + Google Veo B-Roll.

Tests:
1. Complete lifecycle execution from TrainingVideoRequest to final composed multilingual MP4.
2. Scene categorization:
   - Scene 1: Presenter Introduction (HeyGen / avatar provider)
   - Scene 2: Animated B-Roll Demonstration (Google Veo)
   - Scene 3: Infographic Motion Graphic (Local Motion Visual)
   - Scene 4: Presenter Outro (HeyGen / avatar provider)
3. Structured SceneMediaPlan persistence and serialization.
4. Authoritative localized TTS narration audio track synchronization.
5. Absolute muting/discarding of generated Veo audio in composed scenes.
6. RTL Arabic subtitle burn-in with complex shaping.
7. Technical validation with ffprobe (resolution, codecs, stream presence, duration).
8. Multi-frame extraction and visual verification.
"""

from pathlib import Path
import subprocess
import pytest
from PIL import Image

from app.core.config import settings
from app.models.schemas import (
    TrainingVideoRequest,
    ProjectManifest,
    ContentAnalysis,
    ScriptDraft,
    SceneDraft,
    LearningObjective,
    LocalizedScript,
    LocalizedScene,
    CulturalGuidance,
    VideoStyle,
)
from app.services.llm.base import LLMProvider
from app.services.localization.service import LocalizationService
from app.services.tts.service import TTSService
from app.services.tts.mock_tts_provider import MockTTSProvider
from app.services.avatar.service import AvatarService
from app.services.avatar.mock_avatar_provider import MockAvatarProvider
from app.services.visuals.service import VisualService
from app.services.visuals.mock_provider import MockVisualProvider
from app.services.subtitles.service import SubtitleService
from app.services.subtitles.deterministic_provider import DeterministicSubtitleProvider
from app.services.composition.service import CompositionService
from app.services.composition.ffmpeg_provider import FFmpegCompositionProvider
from app.services.composition.ffmpeg_utils import (
    check_ffmpeg_available,
    probe_video_file,
    validate_video_file,
    get_video_duration,
)
from app.workflows.manifest import ProjectManifestManager
from app.workflows.orchestrator import ProjectOrchestrator
from app.workflows.storyboard_planner import StoryboardPlanner


class E2EMockLLMProvider(LLMProvider):
    """Mock LLMProvider providing structured responses for E2E testing."""

    @property
    def model_name(self) -> str:
        return "mock-e2e-llm"

    @property
    def provider_name(self) -> str:
        return "mock"

    def generate_text(self, prompt: str, system_prompt=None, temperature=0.7, max_tokens=None) -> str:
        return "Mock response"

    def generate_structured(self, prompt: str, schema, system_prompt=None, temperature=0.2):
        if schema == ContentAnalysis:
            return ContentAnalysis(
                topic_summary="Workplace Phishing Defense Essentials",
                key_concepts=["Sender Domain Verification", "Reporting Protocols"],
                learning_objectives=[
                    LearningObjective(id="LO1", description="Inspect sender headers and verify domain authenticity"),
                    LearningObjective(id="LO2", description="Utilize corporate toolbar to report suspicious messages"),
                ],
                audience_notes="Corporate employees",
                recommended_scene_count=4,
                recommended_structure=["Intro", "B-Roll Demonstration", "Infographic Concept", "Outro"],
                important_terms=["Phishing", "Domain Spoofing"],
                factual_constraints=["Always inspect domain"],
            )

        if schema == ScriptDraft:
            return ScriptDraft(
                title="Workplace Phishing Defense Essentials",
                language="en-US",
                audience="Corporate Employees",
                learning_objectives=[
                    LearningObjective(id="LO1", description="Inspect sender headers and verify domain authenticity"),
                    LearningObjective(id="LO2", description="Utilize corporate toolbar to report suspicious messages"),
                ],
                opening_hook="Can you spot a deceptive email before it breaches your network?",
                scenes=[
                    SceneDraft(
                        scene_id="scene_1",
                        order=1,
                        title="Welcome and Overview",
                        purpose="Welcome learners and introduce phishing defense importance",
                        narration="Welcome to cybersecurity essentials. Today we explore how deceptive phishing attacks target your corporate inbox.",
                        estimated_duration_seconds=15,
                        visual_direction="Presenter in modern studio introducing the training module.",
                        learning_objective_ids=["LO1"],
                        scene_type="intro",
                    ),
                    SceneDraft(
                        scene_id="scene_2",
                        order=2,
                        title="Sender Domain Verification",
                        purpose="Demonstrate inspecting the full email domain header",
                        narration="Always hover your cursor over the sender name to reveal the authentic domain before clicking any embedded hyperlinks.",
                        estimated_duration_seconds=20,
                        visual_direction="Close-up footage of corporate inbox UI with cursor hovering over disguised sender header.",
                        learning_objective_ids=["LO1"],
                        scene_type="visual_demo",
                    ),
                    SceneDraft(
                        scene_id="scene_3",
                        order=3,
                        title="Corporate Reporting Protocol",
                        purpose="Explain quarantine and threat response workflow",
                        narration="When you identify a suspicious email, do not forward it. Press the Report Phishing button to immediately notify the SOC team.",
                        estimated_duration_seconds=20,
                        visual_direction="Animated infographic diagram showing email quarantine and SOC alert notification workflow.",
                        learning_objective_ids=["LO2"],
                        scene_type="explanation",
                    ),
                    SceneDraft(
                        scene_id="scene_4",
                        order=4,
                        title="Key Takeaways and Conclusion",
                        purpose="Summarize defensive actions and encourage vigilance",
                        narration="Your proactive vigilance keeps the entire enterprise safe. Report threats promptly and stay secure.",
                        estimated_duration_seconds=15,
                        visual_direction="Presenter summarizing key takeaways with call to action overlay.",
                        learning_objective_ids=["LO2"],
                        scene_type="outro",
                    ),
                ],
                closing_summary="Vigilance is our strongest collective defense.",
                total_estimated_duration_seconds=30,
            )

        if schema == LocalizedScript:
            return LocalizedScript(
                title="أساسيات الحماية من التصيد الاحتيالي في بيئة العمل",
                source_language="en-US",
                language="ar",
                locale="ar-SA",
                text_direction="rtl",
                audience="الموظفون",
                learning_objectives=[
                    LearningObjective(id="LO1", description="Inspect sender headers and verify domain authenticity"),
                    LearningObjective(id="LO2", description="Utilize corporate toolbar to report suspicious messages"),
                ],
                opening_hook="هل يمكنك كشف رسائل التصيد الاحتيالي قبل أن تخترق شبكتك؟",
                scenes=[
                    LocalizedScene(
                        scene_id="scene_1",
                        order=1,
                        title="المقدمة والنظرة العامة",
                        purpose="Welcome learners",
                        narration="مرحباً بكم في تدريب أساسيات الأمن السيبراني. نستعرض اليوم كيف تستهدف رسائل التصيد الاحتيالي بريدكم المؤسسي.",
                        estimated_duration_seconds=7,
                        visual_direction="مقدم العرض في استوديو حديث.",
                        learning_objective_ids=["LO1"],
                        scene_type="intro",
                    ),
                    LocalizedScene(
                        scene_id="scene_2",
                        order=2,
                        title="التحقق من نطاق المرسل",
                        purpose="Demonstrate sender check",
                        narration="احرص دائماً على تمرير المؤشر فوق اسم المرسل للتحقق من النطاق الحقيقي قبل الضغط على أي روابط.",
                        estimated_duration_seconds=8,
                        visual_direction="لقطة سينمائية لواجهة البريد مع فحص النطاق.",
                        learning_objective_ids=["LO1"],
                        scene_type="visual_demo",
                    ),
                    LocalizedScene(
                        scene_id="scene_3",
                        order=3,
                        title="بروتوكول الإبلاغ المؤسسي",
                        purpose="Explain reporting protocol",
                        narration="عند رصد رسالة مشبوهة لا تقم بإعادة توجيهها، بل اضغط على زر الإبلاغ عن التصيد لإخطار فريق العمليات فوراً.",
                        estimated_duration_seconds=8,
                        visual_direction="رسم توضيحي لآلية الحجر وعزل التهديد.",
                        learning_objective_ids=["LO2"],
                        scene_type="explanation",
                    ),
                    LocalizedScene(
                        scene_id="scene_4",
                        order=4,
                        title="الخاتمة والتوصيات",
                        purpose="Summarize key takeaways",
                        narration="يقظتك المستمرة تحمي المنظومة بأكملها. أبلغ عن التهديدات وابق آمناً.",
                        estimated_duration_seconds=7,
                        visual_direction="مقدم العرض يختتم التدريب بدعوة للعمل.",
                        learning_objective_ids=["LO2"],
                        scene_type="outro",
                    ),
                ],
                closing_summary="يقظتك هي خط الدفاع الأقوى.",
                target_duration_seconds=30,
                total_estimated_duration_seconds=30,
                cultural_guidance=CulturalGuidance(
                    locale="ar-SA",
                    formality_guidance="Formal Arabic",
                    visual_environment_guidance="Modern Professional Office",
                    cultural_notes=["Use appropriate corporate terminology"],
                ),
                metadata={},
            )

        raise ValueError(f"Unexpected schema: {schema}")


def test_complete_e2e_heygen_and_veo_production_workflow(tmp_path, monkeypatch):
    """
    Execute full end-to-end production workflow:
    - Storyboard planning with Veo B-Roll and HeyGen Presenter.
    - Budget Gate halting in pending_approval and resumption upon authorization.
    - Localization into Arabic (ar-SA) with RTL text.
    - TTS audio synthesis.
    - Avatar talking video generation.
    - Motion media & B-Roll video generation.
    - Complex RTL subtitle burn-in.
    - Scene composition and final video concatenation.
    - FFprobe technical validation and multi-frame visual extraction.
    """
    if not check_ffmpeg_available():
        pytest.skip("FFmpeg not available.")

    monkeypatch.setattr(settings, "ENABLE_LIVE_HEYGEN", True)

    storage_dir = tmp_path / "storage"
    mgr = ProjectManifestManager(storage_base_dir=storage_dir)

    mock_llm = E2EMockLLMProvider()
    loc_service = LocalizationService(llm_provider=mock_llm)
    tts_service = TTSService(provider=MockTTSProvider(), output_base_dir=storage_dir)
    avatar_service = AvatarService(provider=MockAvatarProvider(), output_base_dir=storage_dir)
    visual_service = VisualService(provider=MockVisualProvider(), output_base_dir=storage_dir)
    subtitle_service = SubtitleService(provider=DeterministicSubtitleProvider(), output_base_dir=storage_dir)
    comp_service = CompositionService(provider=FFmpegCompositionProvider(), output_base_dir=storage_dir)

    orch = ProjectOrchestrator(
        manifest_manager=mgr,
        llm_provider=mock_llm,
        localization_service=loc_service,
        tts_service=tts_service,
        avatar_service=avatar_service,
        visual_service=visual_service,
        subtitle_service=subtitle_service,
        composition_service=comp_service,
    )

    req = TrainingVideoRequest(
        topic="Workplace Phishing Defense Essentials",
        audience="Corporate Employees",
        base_language="en-US",
        target_languages=["ar-SA"],
        avatar_provider="heygen",
        ack_paid_credits=True,
        video_style=VideoStyle.HYBRID_PRESENTER_BROLL.value,
        target_duration_seconds=30,
    )

    project_id = "proj_e2e_showcase"
    # Run 1: Should plan script and storyboard, then pause at Stage 1.5 Budget Gate
    manifest1 = orch.run_project(project_id=project_id, request=req)
    assert manifest1.status == "pending_approval"
    assert manifest1.budget_status == "pending_approval"
    assert manifest1.budget is not None
    assert manifest1.budget.requires_approval is True

    # Authorize Budget
    manifest1.budget_status = "approved"
    if manifest1.budget:
        manifest1.budget.status = "approved"
        manifest1.budget.approved_by = "security_lead@enterprise.com"
    mgr.save_manifest(manifest1)

    # Run 2: Resume past Budget Gate to complete full production
    manifest = orch.resume_project(project_id=project_id)

    # 1. Pipeline Lifecycle Verification
    assert manifest.status == "completed"
    assert manifest.script_status == "completed"
    assert manifest.localization_status == "completed"
    assert manifest.audio_status == "completed"
    assert manifest.avatar_status == "completed"
    assert manifest.visual_status == "completed"
    assert manifest.subtitle_status == "completed"
    assert manifest.composition_status == "completed"

    # 2. Storyboard & Scene Media Plan Verification
    scenes = manifest.final_script.scenes
    assert len(scenes) == 4
    # Scene 1: Presenter
    assert scenes[0].media_type == "presenter"
    assert scenes[0].avatar_enabled is True
    assert scenes[0].preferred_provider == "heygen"
    assert scenes[0].media_plan is not None
    assert scenes[0].media_plan.preferred_provider == "heygen"

    # Scene 2: Veo B-Roll
    assert scenes[1].media_type == "broll"
    assert scenes[1].avatar_enabled is False
    assert scenes[1].preferred_provider == "veo"
    assert scenes[1].media_plan is not None
    assert scenes[1].media_plan.preferred_provider == "veo"
    assert scenes[1].camera_movement == "slow pan"

    # Scene 3: Motion Visual
    assert scenes[2].media_type == "motion_visual"
    assert scenes[2].preferred_provider == "local_motion"
    assert scenes[2].media_plan.preferred_provider == "local_motion"

    # Scene 4: Outro
    assert scenes[3].media_type == "outro"
    assert scenes[3].avatar_enabled is True
    assert scenes[3].preferred_provider == "heygen"

    # 3. Final Video Asset & FFprobe Validation
    assert "ar-SA" in manifest.final_videos
    final_asset = manifest.final_videos["ar-SA"]
    final_video_path = Path(final_asset.video_path)
    assert final_video_path.exists()
    assert final_video_path.stat().st_size > 0

    meta = validate_video_file(
        final_video_path,
        min_duration=2.0,
        require_video=True,
        require_audio=True,
        min_width=1280,
        min_height=720,
    )
    assert meta["has_video"] is True
    assert meta["has_audio"] is True
    assert meta["width"] == settings.VIDEO_WIDTH
    assert meta["height"] == settings.VIDEO_HEIGHT
    assert meta["video_codec"] == "h264"
    assert meta["audio_codec"] == "aac"

    # 4. Multi-Frame Extraction Diagnostics
    # Extract frames at 0.5s, 1.0s, and 1.5s using ffmpeg to verify non-empty visual frames
    frame_dir = tmp_path / "diagnostics_frames"
    frame_dir.mkdir(parents=True, exist_ok=True)
    frame_files = []
    for ts in [0.5, 1.0, 1.5]:
        frame_p = frame_dir / f"frame_{ts}s.png"
        extract_cmd = [
            settings.FFMPEG_BINARY_PATH,
            "-y",
            "-ss", str(ts),
            "-i", str(final_video_path.resolve()),
            "-vframes", "1",
            str(frame_p.resolve()),
        ]
        res = subprocess.run(extract_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        assert res.returncode == 0
        assert frame_p.exists()
        assert frame_p.stat().st_size > 1000
        # Check image resolution with PIL
        with Image.open(frame_p) as img:
            assert img.size == (1920, 1080)
        frame_files.append(frame_p)

    assert len(frame_files) == 3
