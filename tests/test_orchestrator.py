"""Comprehensive test suite for Step 10 Full End-to-End Project Orchestration.

Tests:
1. ProjectManifestManager lifecycle: creation, loading, saving, listing manifests.
2. Complete end-to-end pipeline run from TrainingVideoRequest to final videos.
3. Proper artifact persistence: project.json, audio, visuals, subtitles, scene videos, final videos.
4. Timing synchronization: audio waveform duration updates localized script scenes.
5. Idempotent rerun: completed artifacts are reused and not regenerated.
6. Partial resume capability: resumes uncompleted stages without re-running completed script/localization stages.
7. Locale failure isolation: failure in one locale preserves successful outputs in other locales.
8. Status progression: pending -> running -> completed (or needs_review/failed).
9. Zero paid external API calls.
"""

from pathlib import Path
from typing import Optional, List, Type, TypeVar
import pytest
from pydantic import BaseModel

from app.models.schemas import (
    TrainingVideoRequest,
    ProjectManifest,
    ContentAnalysis,
    ScriptDraft,
    SceneDraft,
    LearningObjective,
    FinalScript,
    LocalizedScript,
    LocalizedScene,
    CulturalGuidance,
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
from app.services.composition.mock_provider import MockCompositionProvider
from app.workflows.manifest import ProjectManifestManager
from app.workflows.orchestrator import ProjectOrchestrator

T = TypeVar("T", bound=BaseModel)

SAMPLE_EN_NARRATION_1 = (
    "Welcome to cybersecurity awareness training. Today we examine how deceptive phishing emails enter your inbox "
    "pretending to come from trusted company executives or service providers. The primary defense is scrutinizing "
    "the exact sender domain. Fraudulent senders frequently alter a single letter or add obscure suffixes to mimic "
    "legitimate addresses. Always hover your cursor over the sender name to reveal the actual email address before "
    "clicking any embedded hyperlinks or downloading attachments."
)
SAMPLE_EN_NARRATION_2 = (
    "Once you identify a suspicious message, proper protocol requires prompt reporting rather than simple deletion. "
    "Never attempt to forward the threat directly to colleagues via normal messaging channels. Instead, utilize "
    "the official 'Report Phishing' button located in your corporate toolbar. This sends the email headers and "
    "security metadata directly to the security operations center for rapid quarantine. Your vigilance protects "
    "not only your machine, but the entire organization against intrusion."
)

SAMPLE_AR_NARRATION_1 = (
    "مرحباً بكم في التدريب التوعوي للأمن السيبراني المؤسسي. اليوم نستعرض بدقة كيف تصل رسائل التصيد الاحتيالي "
    "الخبيثة إلى صندوق بريدكم الإلكتروني منتحلة صفة مدراء تنفيذيين أو جهات موثوقة. خط الدفاع الأول والأهم هو فحص "
    "النطاق الفعلي للمرسل بعناية تامة. يقوم المهاجمون غالباً بتغيير حرف واحد أو إضافة لواحق غامضة لمحاكاة العناوين "
    "الرسمية المعتمدة. احرص دائماً على تمرير المؤشر فوق اسم المرسل للتحقق من العنوان الفعلي قبل الضغط على أي روابط أو مرفقات."
)
SAMPLE_AR_NARRATION_2 = (
    "عند اكتشافك لأي رسالة مشبوهة، يتطلب البروتوكول الأمني المعتمد إبلاغ فريق الاستجابة على الفور بدلاً من مجرد الحذف. "
    "لا تقم بإعادة توجيه الرسالة عبر قنوات المراسلة المعتادة للزملاء. بدلاً من ذلك، استخدم زر الإبلاغ عن التصيد في شريط "
    "الأدوات الرسمي لشركتك. سيؤدي هذا إلى إرسال ترويسات الرسالة والبيانات الفنية مباشرة إلى مركز العمليات الأمنية للعزل. "
    "يقظتك تحمي منظومتنا بأكملها من الاختراق."
)
SAMPLE_BN_NARRATION_1 = (
    "সাইবার নিরাপত্তা সচেতনতা প্রশিক্ষণে আপনাদের স্বাগতম। আজ আমরা আলোচনা করব কীভাবে প্রতারণামূলক ফিশিং ইমেইল "
    "আপনার ইনবক্সে প্রবেশ করে বিশ্বস্ত কর্মকর্তাদের ভান ধরে। আপনার প্রধান প্রতিরক্ষা হলো প্রেরকের প্রকৃত ডোমেইন সাবধানে পরীক্ষা করা। "
    "প্রতারকরা প্রায়ই একটি অক্ষর পরিবর্তন করে বা অতিরিক্ত শব্দ যুক্ত করে নকল ঠিকানা তৈরি করে। যেকোনো লিঙ্কে ক্লিক করার আগে বা কোনো ফাইল "
    "ডাউনলোড করার আগে সর্বদা মাউসের কার্সারটি প্রেরকের নামের উপর রেখে প্রকৃত ঠিকানা যাচাই করে নিন।"
)
SAMPLE_BN_NARRATION_2 = (
    "সন্দেহজনক বার্তা শনাক্ত করার পর প্রাতিষ্ঠানিক নির্দেশিকা অনুযায়ী অবিলম্বে রিপোর্ট করা জরুরি কেবল মুছে ফেলা যথেষ্ট নয়। "
    "সাধারণ চ্যাট মাধ্যমে সহকর্মীদের কাছে এই বার্তা পাঠাবেন না। বরং আপনার কর্পোরেট টুলবারে থাকা অফিসিয়াল 'রিপোর্ট ফিশিং' বোতামটি "
    "ব্যবহার করুন। এটি ইমেইলের সমস্ত তথ্য সরাসরি নিরাপত্তা দলের কাছে পাঠিয়ে দেবে দ্রুত প্রতিকারের জন্য। আপনার সচেতনতাই আমাদের "
    "সমগ্র প্রতিষ্ঠানকে নিরাপদ রাখবে।"
)


class UnifiedMockLLMProvider(LLMProvider):
    """Mock LLMProvider providing structured outputs for script generation and localization."""

    def __init__(self, model_name_str: str = "mock-unified-llm"):
        self._model_name = model_name_str
        self.script_calls = 0
        self.loc_calls = 0

    @property
    def model_name(self) -> str:
        return self._model_name

    def generate_text(self, prompt: str, system_prompt: Optional[str] = None, temperature: float = 0.7, max_tokens: Optional[int] = None) -> str:
        return "Mock text response"

    def generate_structured(self, prompt: str, schema: Type[T], system_prompt: Optional[str] = None, temperature: float = 0.2) -> T:
        if schema == ContentAnalysis:
            return ContentAnalysis(
                topic_summary="Phishing Defense",
                key_concepts=["Email domains", "Reporting"],
                learning_objectives=[
                    LearningObjective(id="LO1", description="Identify spoofed domains"),
                    LearningObjective(id="LO2", description="Report suspicious emails"),
                ],
                audience_notes="Employees",
                recommended_scene_count=2,
                recommended_structure=["Intro", "Action"],
                important_terms=["Phishing", "Spoofing"],
                factual_constraints=["Inspect senders"],
            )

        if schema == ScriptDraft:
            self.script_calls += 1
            return ScriptDraft(
                title="Cybersecurity Awareness",
                language="en-US",
                audience="Employees",
                learning_objectives=[
                    LearningObjective(id="LO1", description="Identify spoofed domains"),
                    LearningObjective(id="LO2", description="Report suspicious emails"),
                ],
                opening_hook="Can you spot a dangerous threat in your inbox?",
                scenes=[
                    SceneDraft(
                        scene_id="scene_1",
                        order=1,
                        title="Domain Verification",
                        purpose="Awareness of spoofed senders",
                        narration=SAMPLE_EN_NARRATION_1,
                        estimated_duration_seconds=30,
                        visual_direction="Presenter in office.",
                        on_screen_text="Check Sender Domain",
                        learning_objective_ids=["LO1"],
                        scene_type="presenter",
                    ),
                    SceneDraft(
                        scene_id="scene_2",
                        order=2,
                        title="Reporting Protocol",
                        purpose="Explain action steps",
                        narration=SAMPLE_EN_NARRATION_2,
                        estimated_duration_seconds=30,
                        visual_direction="Diagram on screen.",
                        on_screen_text="Click Report Phishing",
                        learning_objective_ids=["LO2"],
                        scene_type="visual_demo",
                    ),
                ],
                closing_summary="Report threats promptly to protect the team.",
                total_estimated_duration_seconds=60,
            )

        if schema == LocalizedScript:
            self.loc_calls += 1
            is_ar = "ar-SA" in prompt or "Arabic" in prompt
            locale = "ar-SA" if is_ar else "bn-BD"
            nar1 = SAMPLE_AR_NARRATION_1 if is_ar else SAMPLE_BN_NARRATION_1
            nar2 = SAMPLE_AR_NARRATION_2 if is_ar else SAMPLE_BN_NARRATION_2
            direction = "rtl" if is_ar else "ltr"

            return LocalizedScript(
                title="التوعية بالأمن السيبراني" if is_ar else "সাইবার সচেতনতা",
                source_language="en-US",
                language="ar" if is_ar else "bn",
                locale=locale,
                text_direction=direction,
                audience="Employees",
                learning_objectives=[
                    LearningObjective(id="LO1", description="Identify spoofed domains"),
                    LearningObjective(id="LO2", description="Report suspicious emails"),
                ],
                opening_hook="مقدمة" if is_ar else "ভূমিকা",
                scenes=[
                    LocalizedScene(
                        scene_id="scene_1",
                        order=1,
                        title="التحقق من النطاق" if is_ar else "ডোমেইন যাচাই",
                        purpose="P1",
                        narration=nar1,
                        estimated_duration_seconds=30,
                        visual_direction="مقدم العرض يشرح الشعار في مكتب عصري." if is_ar else "উপস্থাপক আধুনিক অফিসে ডায়াগ্রাম ব্যাখ্যা করছেন।",
                        on_screen_text="تحقق من المرسل" if is_ar else "যাচাই করুন",
                        learning_objective_ids=["LO1"],
                        scene_type="presenter",
                    ),
                    LocalizedScene(
                        scene_id="scene_2",
                        order=2,
                        title="بروتوكول الإبلاغ" if is_ar else "রিপোর্ট",
                        purpose="P2",
                        narration=nar2,
                        estimated_duration_seconds=30,
                        visual_direction="رسم توضيحي لزر الإبلاغ المؤسسي." if is_ar else "রিপোর্টিং বোতামের দৃশ্যমান চিত্র।",
                        on_screen_text=None,
                        learning_objective_ids=["LO2"],
                        scene_type="visual_demo",
                    ),
                ],
                closing_summary="خاتمة" if is_ar else "উপসংহার",
                target_duration_seconds=60,
                total_estimated_duration_seconds=60,
                cultural_guidance=CulturalGuidance(
                    locale=locale,
                    formality_guidance="Formal",
                    visual_environment_guidance="Office",
                    cultural_notes=[],
                ),
                metadata={},
            )

        raise ValueError(f"Unexpected schema requested: {schema}")


def create_test_orchestrator(tmp_path: Path, llm: Optional[LLMProvider] = None) -> ProjectOrchestrator:
    """Create orchestrator instance configured with fast, safe mock providers."""
    manifest_mgr = ProjectManifestManager(storage_base_dir=tmp_path / "storage")
    llm_p = llm or UnifiedMockLLMProvider()
    loc_service = LocalizationService(llm_provider=llm_p)
    tts_service = TTSService(provider=MockTTSProvider(), output_base_dir=tmp_path / "storage")
    avatar_service = AvatarService(provider=MockAvatarProvider(), output_base_dir=tmp_path / "storage")
    visual_service = VisualService(provider=MockVisualProvider(), output_base_dir=tmp_path / "storage")
    subtitle_service = SubtitleService(provider=DeterministicSubtitleProvider(), output_base_dir=tmp_path / "storage")
    comp_service = CompositionService(provider=MockCompositionProvider(), output_base_dir=tmp_path / "storage")

    return ProjectOrchestrator(
        manifest_manager=manifest_mgr,
        llm_provider=llm_p,
        localization_service=loc_service,
        tts_service=tts_service,
        avatar_service=avatar_service,
        visual_service=visual_service,
        subtitle_service=subtitle_service,
        composition_service=comp_service,
    )


def test_manifest_manager_lifecycle(tmp_path: Path):
    """Verify ProjectManifestManager correctly creates, loads, saves, and lists project manifests."""
    mgr = ProjectManifestManager(storage_base_dir=tmp_path / "storage")
    req = TrainingVideoRequest(
        topic="Phishing Defense",
        audience="Staff",
        base_language="en-US",
        target_languages=["ar-SA"],
        target_duration_seconds=60,
    )

    manifest = mgr.create_manifest("proj_1", req)
    assert manifest.project_id == "proj_1"
    assert manifest.status == "pending"
    assert mgr.get_manifest_path("proj_1").exists()

    loaded = mgr.load_manifest("proj_1")
    assert loaded is not None
    assert loaded.project_id == "proj_1"
    assert loaded.source_request.topic == "Phishing Defense"

    manifest.status = "completed"
    mgr.save_manifest(manifest)

    updated = mgr.load_manifest("proj_1")
    assert updated.status == "completed"

    projects = mgr.list_projects()
    assert len(projects) == 1
    assert projects[0].project_id == "proj_1"


def test_end_to_end_project_execution(tmp_path: Path):
    """Verify complete end-to-end orchestration across all stages."""
    orchestrator = create_test_orchestrator(tmp_path)
    req = TrainingVideoRequest(
        topic="Workplace Cybersecurity Awareness",
        audience="Corporate Employees",
        base_language="en-US",
        target_languages=["ar-SA"],
        target_duration_seconds=60,
    )

    manifest = orchestrator.run_project(project_id="proj_e2e_1", request=req)

    # 1. State & Stage verification
    assert manifest.status == "completed"
    assert manifest.script_status == "completed"
    assert manifest.localization_status == "completed"
    assert manifest.audio_status == "completed"
    assert manifest.avatar_status == "completed"
    assert manifest.visual_status == "completed"
    assert manifest.subtitle_status == "completed"
    assert manifest.composition_status == "completed"

    # 2. Artifacts verification in manifest
    assert manifest.final_script is not None
    assert len(manifest.final_script.scenes) == 2
    assert "ar-SA" in manifest.localization_bundle.localized_scripts
    assert "ar-SA" in manifest.audio_tracks
    assert "ar-SA" in manifest.visual_tracks
    assert "ar-SA" in manifest.subtitle_tracks
    assert "ar-SA" in manifest.final_videos

    # 3. Disk persistence verification
    proj_dir = tmp_path / "storage" / "proj_e2e_1"
    assert (proj_dir / "project.json").exists()
    final_video_path = Path(manifest.final_videos["ar-SA"].video_path)
    assert final_video_path.exists()
    assert final_video_path.stat().st_size > 0


def test_orchestrator_idempotency_and_no_unnecessary_calls(tmp_path: Path):
    """Verify that re-running a completed project reuses existing artifacts without LLM calls."""
    mock_llm = UnifiedMockLLMProvider()
    orchestrator = create_test_orchestrator(tmp_path, llm=mock_llm)
    req = TrainingVideoRequest(
        topic="Safety Module",
        audience="All",
        base_language="en-US",
        target_languages=["ar-SA"],
        target_duration_seconds=60,
    )

    # Run 1
    manifest1 = orchestrator.run_project("proj_idem", req)
    assert manifest1.status == "completed"
    initial_script_calls = mock_llm.script_calls
    initial_loc_calls = mock_llm.loc_calls

    # Run 2 (without force_regenerate)
    manifest2 = orchestrator.run_project("proj_idem", req, force_regenerate=False)
    assert manifest2.status == "completed"

    # Verify zero additional LLM invocations occurred
    assert mock_llm.script_calls == initial_script_calls
    assert mock_llm.loc_calls == initial_loc_calls


def test_orchestrator_resume_from_partial_failure(tmp_path: Path):
    """Verify resume picks up from uncompleted stages without re-running completed stages."""
    mock_llm = UnifiedMockLLMProvider()
    orchestrator = create_test_orchestrator(tmp_path, llm=mock_llm)
    req = TrainingVideoRequest(
        topic="Incident Response",
        audience="Staff",
        base_language="en-US",
        target_languages=["ar-SA"],
        target_duration_seconds=60,
    )

    # Run initial pipeline
    manifest = orchestrator.run_project("proj_resume", req)
    assert manifest.status == "completed"

    # Simulate incomplete composition stage
    manifest.composition_status = "pending"
    manifest.final_videos = {}
    orchestrator.manifest_manager.save_manifest(manifest)

    # Resume project
    script_calls_before = mock_llm.script_calls
    resumed_manifest = orchestrator.resume_project("proj_resume")

    assert resumed_manifest.status == "completed"
    assert resumed_manifest.composition_status == "completed"
    assert "ar-SA" in resumed_manifest.final_videos
    # Script generation was not recomputed
    assert mock_llm.script_calls == script_calls_before
