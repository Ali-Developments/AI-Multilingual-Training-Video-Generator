"""Comprehensive test suite verifying fixes for:
- ISSUE-001: Script Generation Pipeline Failure & Diagnostic Preservation
- ISSUE-006: Locale-Aware Pre-TTS Duration Estimation
- ISSUE-005: Source-Content and Base-Language Mismatch Validation
"""

import pytest
from typing import Optional, Type, TypeVar
from pydantic import BaseModel, ValidationError

from app.models.schemas import (
    TrainingVideoRequest,
    ContentAnalysis,
    LearningObjective,
    SceneDraft,
    ScriptDraft,
    ValidationIssue,
    ScriptValidationResult,
    ProjectManifest,
)
from app.services.llm.base import LLMProvider
from app.workflows.script_generation.validators import (
    estimate_narration_duration_seconds,
    normalize_script_durations,
    validate_script_draft,
    LocaleDurationEstimator,
)
from app.workflows.script_generation.state import VideoScriptState
from app.workflows.script_generation.nodes import ScriptWorkflowNodes
from app.workflows.script_generation.graph import create_script_workflow
from app.core.language import detect_primary_script, validate_source_language_mismatch
from tests.test_orchestrator import create_test_orchestrator


T = TypeVar("T", bound=BaseModel)


class FailingMockLLM(LLMProvider):
    """Mock LLM provider designed to trigger validation failure and revision exhaustion."""

    def __init__(self, failure_type: str = "validation"):
        self.failure_type = failure_type
        self.call_count = 0

    @property
    def model_name(self) -> str:
        return f"mock-{self.failure_type}"

    def generate_text(self, prompt: str, system_prompt: Optional[str] = None, temperature: float = 0.7, max_tokens: Optional[int] = None) -> str:
        return "text"

    def generate_structured(self, prompt: str, schema: Type[T], system_prompt: Optional[str] = None, temperature: float = 0.2) -> T:
        self.call_count += 1
        if self.failure_type == "provider_crash":
            raise RuntimeError("Upstream LLM Provider network timeout (HTTP 504)")

        if schema == ContentAnalysis:
            return ContentAnalysis(
                topic_summary="Phishing basics",
                key_concepts=["Headers"],
                learning_objectives=[LearningObjective(id="LO1", description="Check sender")],
                audience_notes="Employees",
                recommended_scene_count=1,
                recommended_structure=["Intro"],
                important_terms=["Phishing"],
                factual_constraints=["Be careful"],
            )

        if schema == ScriptDraft:
            if self.failure_type == "malformed":
                raise ValueError("JSON decode error: Unterminated string starting at line 1 column 45")
            # Returns an invalid script with missing opening hook and wrong duration
            return ScriptDraft(
                title="Invalid Draft",
                language="en-US",
                audience="Learners",
                opening_hook="",  # Triggers MISSING_OPENING_HOOK
                scenes=[
                    SceneDraft(
                        scene_id="s1",
                        order=1,
                        title="Scene 1",
                        narration="Only three words.",  # Too short for a 60s video
                        visual_direction="Visual",
                        learning_objective_ids=["LO1"],
                    )
                ],
            )

        raise ValueError(f"Unexpected schema: {schema}")


# ===========================================================================
# ISSUE-006: Locale-Aware WPM Duration Estimation Tests
# ===========================================================================

def test_locale_estimator_english():
    """Verify English baseline rate (~140 WPM)."""
    # 70 words in English at 140 WPM = (70/140)*60 = 30 seconds
    en_narration = " ".join(["word"] * 70)
    dur = estimate_narration_duration_seconds(en_narration, language="en-US")
    assert dur == 30
    assert LocaleDurationEstimator.get_wpm_for_locale("en-US") == 140
    assert LocaleDurationEstimator.get_wpm_for_locale("en-GB") == 140


def test_locale_estimator_arabic():
    """Verify Arabic calibrated speech rate (115 WPM)."""
    # In Arabic, 58 space tokens at 115 WPM = round((58/115)*60) = 30 seconds
    ar_narration = (
        "مرحبا بكم في تدريب التوعية بالأمن السيبراني اليوم سنتعلم كيفية التعرف على "
        "رسائل البريد الإلكتروني الاحتيالية التي تنتحل صفة جهات رسمية وموثوقة احرص "
        "دائما على التحقق من عنوان المرسل الفعلي قبل الضغط على أي رابط مريب وقم بإبلاغ "
        "فريق أمن المعلومات مباشرة لحماية بيانات المنظمة بالكامل"
    )
    wpm = LocaleDurationEstimator.get_wpm_for_locale("ar-SA")
    assert wpm == 115

    dur_ar = estimate_narration_duration_seconds(ar_narration, language="ar-SA")
    # With 115 WPM, speech duration is accurately calibrated higher than 140 WPM
    dur_en_wpm = estimate_narration_duration_seconds(ar_narration, words_per_minute=140)
    assert dur_ar > dur_en_wpm


def test_locale_estimator_bengali():
    """Verify Bengali calibrated speech rate (120 WPM)."""
    bn_narration = (
        "সাইবার নিরাপত্তা সচেতনতা প্রশিক্ষণে আপনাকে স্বাগতম আজ আমরা শিখব কিভাবে প্রতারণামূলক "
        "ফিশিং ইমেল সনাক্ত করতে হয় প্রেরকের আসল ঠিকানা সর্বদা যাচাই করুন"
    )
    wpm = LocaleDurationEstimator.get_wpm_for_locale("bn-BD")
    assert wpm == 120

    dur_bn = estimate_narration_duration_seconds(bn_narration, language="bn-BD")
    assert dur_bn > 0


def test_locale_estimator_fallback_unknown_locale():
    """Verify unknown locales fall back to 140 WPM safely."""
    text = " ".join(["test"] * 70)
    assert LocaleDurationEstimator.get_wpm_for_locale("xx-YY") == 140
    assert estimate_narration_duration_seconds(text, language="xx-YY") == 30


def test_locale_estimator_long_scripts():
    """Verify long script scaling across locales."""
    long_text = " ".join(["content"] * 280)
    # English: (280/140)*60 = 120s
    assert estimate_narration_duration_seconds(long_text, language="en-US") == 120
    # Arabic: (280/115)*60 = 146s
    assert estimate_narration_duration_seconds(long_text, language="ar-SA") == 146


def test_short_script_tolerance_buffer():
    """Verify short video tolerance allows reasonable +/- 8s buffer without false rejection."""
    # 30-second target with 24-second script (difference 6s, 20%)
    script = ScriptDraft(
        title="Short Script",
        language="ar-SA",
        audience="Staff",
        opening_hook="Important hook for security",
        scenes=[
            SceneDraft(
                scene_id="s1",
                order=1,
                title="Scene 1",
                narration=" ".join(["كلمة"] * 46),  # 46 words at 115 WPM = 24 seconds
                visual_direction="Visual direction",
            )
        ]
    )
    # Target 30s: with 8s buffer for short scripts, 24s is accepted
    res = validate_script_draft(script, target_duration_seconds=30, language="ar-SA")
    assert res.is_valid
    assert not any(i.code == "DURATION_OUT_OF_TOLERANCE" for i in res.issues)


# ===========================================================================
# ISSUE-005: Source-Content and Base-Language Mismatch Tests
# ===========================================================================

def test_detect_primary_script():
    """Verify Unicode heuristics for script identification."""
    latin = "Workplace Phishing Defense Essentials for Corporate Employees"
    arabic = "أساسيات الحماية من التصيد الاحتيالي في بيئة العمل للموظفين"
    bengali = "কর্পোরেট কর্মীদের জন্য কর্মক্ষেত্রে ফিশিং প্রতিরক্ষা প্রয়োজনীয়তা"

    assert detect_primary_script(latin) == "latin"
    assert detect_primary_script(arabic) == "arabic"
    assert detect_primary_script(bengali) == "bengali"
    assert detect_primary_script("short") is None


def test_schema_rejects_latin_content_with_arabic_base_language():
    """Verify TrainingVideoRequest raises ValidationError on English source + ar-SA base_language."""
    with pytest.raises(ValidationError) as exc_info:
        TrainingVideoRequest(
            topic="Workplace Phishing Defense Essentials for Corporate Employees",
            source_content="Phishing emails often mimic IT department urgent password reset requests. Always inspect the sender domain.",
            base_language="ar-SA",
            target_languages=["ar-SA"],
            target_duration_seconds=60,
        )
    assert "Source / Base Language" in str(exc_info.value)
    assert "ar-SA" in str(exc_info.value)


def test_schema_rejects_arabic_content_with_english_base_language():
    """Verify TrainingVideoRequest raises ValidationError on Arabic source + en-US base_language."""
    with pytest.raises(ValidationError) as exc_info:
        TrainingVideoRequest(
            topic="أساسيات الحماية من التصيد الاحتيالي في بيئة العمل للموظفين",
            source_content="رسائل التصيد الاحتيالي غالبا ما تحاكي طلبات إعادة تعيين كلمة المرور العاجلة من إدارة تقنية المعلومات",
            base_language="en-US",
            target_languages=["ar-SA"],
            target_duration_seconds=60,
        )
    assert "Arabic script" in str(exc_info.value)


def test_normalize_input_node_rejects_mismatch():
    """Verify normalize_input node fails early before any LLM calls on mismatch."""
    req = TrainingVideoRequest.model_construct(
        topic="Workplace Phishing Defense Essentials for Corporate Employees",
        source_content="Detailed English instructional reference content regarding email security.",
        base_language="ar-SA",
        target_languages=["ar-SA"],
        target_duration_seconds=60,
        audience="Staff",
        tone="professional",
        difficulty_level="beginner",
    )
    nodes = ScriptWorkflowNodes(llm_provider=FailingMockLLM())
    state = VideoScriptState.model_construct(request=req)
    res = nodes.normalize_input(state)
    assert res["workflow_status"] == "failed"
    assert any("Source / Base Language" in err for err in res["errors"])


def test_matching_languages_accepted():
    """Verify valid language pairings pass without error."""
    req_en = TrainingVideoRequest(
        topic="Workplace Phishing Defense Essentials",
        source_content="English text for corporate security training.",
        base_language="en-US",
        target_languages=["ar-SA", "bn-BD"],
        target_duration_seconds=60,
    )
    assert req_en.base_language == "en-US"

    req_ar = TrainingVideoRequest(
        topic="أساسيات الحماية من التصيد الاحتيالي في بيئة العمل",
        source_content="رسائل التصيد الاحتيالي تحاكي طلبات إعادة تعيين كلمة المرور.",
        base_language="ar-SA",
        target_languages=["ar-SA"],
        target_duration_seconds=60,
    )
    assert req_ar.base_language == "ar-SA"


# ===========================================================================
# ISSUE-001: Script Generation Pipeline Failure & Diagnostic Swallowing Tests
# ===========================================================================

def test_mark_needs_review_preserves_validation_issues_and_revisions():
    """Verify mark_needs_review node captures validation issue codes, messages, and revision count."""
    nodes = ScriptWorkflowNodes(llm_provider=FailingMockLLM())
    state = VideoScriptState(
        revision_count=1,
        max_revisions=1,
        validation=ScriptValidationResult(
            is_valid=False,
            issues=[
                ValidationIssue(code="MISSING_OPENING_HOOK", severity="error", message="Missing hook statement."),
                ValidationIssue(code="DURATION_OUT_OF_TOLERANCE", severity="error", message="Duration 5s vs 60s."),
            ],
            estimated_total_duration_seconds=5,
            duration_difference_seconds=-55,
            duration_difference_percent=91.6,
        ),
        errors=["Initial setup note"],
    )
    res = nodes.mark_needs_review(state)
    assert res["workflow_status"] == "needs_review"
    assert res["final_script"] is None
    assert "errors" in res
    errors_str = " ".join(res["errors"])
    assert "MISSING_OPENING_HOOK" in errors_str
    assert "DURATION_OUT_OF_TOLERANCE" in errors_str
    assert "after 1 revision(s)" in errors_str


def test_orchestrator_surfaces_validation_exhaustion_diagnostics(tmp_path):
    """Verify orchestrator Stage 1 failure populates manifest with real validation errors, not generic text."""
    failing_llm = FailingMockLLM(failure_type="validation")
    orchestrator = create_test_orchestrator(tmp_path, llm=failing_llm)

    req = TrainingVideoRequest(
        topic="Phishing Defense Fundamentals",
        source_content="Comprehensive training materials regarding phishing defense.",
        base_language="en-US",
        target_languages=["ar-SA"],
        target_duration_seconds=60,
    )
    manifest = orchestrator.manifest_manager.create_manifest(project_id="proj_diag_test", request=req)

    result_manifest = orchestrator.run_project("proj_diag_test")
    assert result_manifest.status == "failed"
    assert result_manifest.script_status == "failed"
    assert len(result_manifest.errors) > 0

    first_error = result_manifest.errors[0]
    # Verify the OLD generic swallowed error is NOT produced:
    assert first_error != "Script generation failed: No final script produced"
    # Verify actual failure reason is revealed in manifest:
    assert "needs_review" in first_error
    assert "MISSING_OPENING_HOOK" in first_error or "DURATION_OUT_OF_TOLERANCE" in first_error


def test_orchestrator_surfaces_provider_network_crash(tmp_path):
    """Verify orchestrator Stage 1 failure surfaces provider exceptions cleanly."""
    crashing_llm = FailingMockLLM(failure_type="provider_crash")
    orchestrator = create_test_orchestrator(tmp_path, llm=crashing_llm)

    req = TrainingVideoRequest(
        topic="Phishing Defense Fundamentals",
        source_content="Comprehensive training materials regarding phishing defense.",
        base_language="en-US",
        target_languages=["ar-SA"],
        target_duration_seconds=60,
    )
    orchestrator.manifest_manager.create_manifest(project_id="proj_crash_test", request=req)
    result_manifest = orchestrator.run_project("proj_crash_test")

    assert result_manifest.status == "failed"
    assert any("HTTP 504" in err for err in result_manifest.errors)


# ===========================================================================
# Section 8: Phase A Smoke Test (Workplace Phishing Defense Essentials, 30s)
# ===========================================================================

class SmokeTest30sMockLLM(LLMProvider):
    """Mock LLM calibrated to return a valid 30s instructional script."""

    @property
    def model_name(self) -> str:
        return "mock-smoke-30s"

    def generate_text(self, prompt: str, system_prompt: Optional[str] = None, temperature: float = 0.7, max_tokens: Optional[int] = None) -> str:
        return "Smoke test mock"

    def generate_structured(self, prompt: str, schema: Type[T], system_prompt: Optional[str] = None, temperature: float = 0.2) -> T:
        if schema == ContentAnalysis:
            return ContentAnalysis(
                topic_summary="Workplace Phishing Defense Essentials",
                key_concepts=["Sender Domain Verification", "Incident Reporting"],
                learning_objectives=[
                    LearningObjective(id="LO1", description="Inspect sender email domain"),
                ],
                audience_notes="Corporate Employees",
                recommended_scene_count=1,
                recommended_structure=["Essential Defense"],
                important_terms=["Phishing", "Spoofing"],
                factual_constraints=["Always verify senders"],
            )

        if schema == ScriptDraft:
            # 70 words in English = exactly 30 seconds at 140 WPM
            words_70 = [
                "Welcome", "to", "workplace", "phishing", "defense", "essentials.", "Today", "we", "examine", "how",
                "deceptive", "emails", "enter", "your", "inbox", "mimicking", "urgent", "requests", "from", "trusted",
                "management.", "The", "primary", "defense", "is", "scrutinizing", "the", "sender", "address.", "Fraudulent",
                "attackers", "frequently", "alter", "letters", "to", "mimic", "legitimate", "company", "domains.", "Always",
                "hover", "over", "the", "sender", "name", "to", "verify", "the", "actual", "address",
                "before", "opening", "any", "attachment", "or", "clicking", "links.", "Report", "suspicious", "messages",
                "immediately", "to", "security", "operations.", "Your", "vigilance", "protects", "the", "entire", "organization."
            ]
            narration_30s = " ".join(words_70)
            return ScriptDraft(
                title="Workplace Phishing Defense Essentials",
                language="en-US",
                audience="Corporate Employees",
                learning_objectives=[
                    LearningObjective(id="LO1", description="Inspect sender email domain"),
                ],
                opening_hook="Can you spot a deceptive phishing email before it compromises your account?",
                closing_summary="Always inspect the sender domain and report suspicious emails to security.",
                scenes=[
                    SceneDraft(
                        scene_id="scene_1",
                        order=1,
                        title="Verifying Sender Domains",
                        purpose="Teach email header scrutiny",
                        scene_type="presenter",
                        narration=narration_30s,
                        visual_direction="Close-up of corporate inbox with highlighted sender address.",
                        on_screen_text="Verify the Sender Domain",
                        learning_objective_ids=["LO1"],
                        estimated_duration_seconds=30,
                    )
                ],
                total_estimated_duration_seconds=30,
            )

        # For localization if pipeline continues
        from app.models.schemas import LocalizedScript, LocalizedScene, CulturalGuidance
        if schema == LocalizedScript:
            ar_words_58 = [
                "مرحبا", "بكم", "في", "أساسيات", "الحماية", "من", "التصيد", "الاحتيالي", "في", "بيئة",
                "العمل.", "اليوم", "نستعرض", "كيفية", "التعرف", "على", "الرسائل", "المزيفة", "التي", "تنتحل",
                "صفة", "الإدارة.", "خط", "الدفاع", "الأول", "هو", "فحص", "نطاق", "المرسل", "الفعلي",
                "بعناية.", "احرص", "دائما", "على", "تمرير", "المؤشر", "فوق", "اسم", "المرسل", "للتأكد",
                "من", "العنوان", "قبل", "الضغط", "على", "أي", "رابط.", "بلغ", "فريق", "الأمن",
                "فورا", "لحماية", "بيانات", "المنظمة", "بالكامل", "ضد", "أي", "اختراق."
            ]
            ar_narration_30s = " ".join(ar_words_58)
            return LocalizedScript(
                title="أساسيات الحماية من التصيد الاحتيالي في بيئة العمل",
                source_language="en-US",
                language="ar-SA",
                locale="ar-SA",
                audience="Corporate Employees",
                text_direction="rtl",
                learning_objectives=[
                    LearningObjective(id="LO1", description="Inspect sender email domain"),
                ],
                opening_hook="هل يمكنك التعرف على رسائل التصيد الاحتيالي قبل أن تخترق حسابك؟",
                closing_summary="تحقق دائما من نطاق المرسل وقم بإبلاغ فريق أمن المعلومات مباشرة.",
                scenes=[
                    LocalizedScene(
                        scene_id="scene_1",
                        order=1,
                        title="التحقق من نطاق المرسل",
                        purpose="تعليم فحص عنوان المرسل",
                        scene_type="presenter",
                        narration=ar_narration_30s,
                        visual_direction="لقطة قريبة لصندوق البريد مع إبراز عنوان المرسل.",
                        on_screen_text="تحقق من نطاق المرسل",
                        learning_objective_ids=["LO1"],
                        estimated_duration_seconds=30,
                    )
                ],
                target_duration_seconds=30,
                total_estimated_duration_seconds=30,
                cultural_guidance=CulturalGuidance(
                    locale="ar-SA",
                    formality_guidance="Formal professional Saudi Arabic",
                    visual_environment_guidance="Modern office setting",
                    cultural_notes=["Standard professional terminology"],
                ),
                metadata={},
            )

        raise ValueError(f"Unexpected schema: {schema}")


def test_phase_a_smoke_test_30s_pipeline(tmp_path):
    """
    Phase A Smoke Test per specification:
    Topic: Workplace Phishing Defense Essentials
    Source Content: English phishing training text
    Source/Base Language: en-US
    Target: ar-SA
    Duration: 30 seconds
    Tone: professional
    Difficulty: beginner
    """
    smoke_llm = SmokeTest30sMockLLM()
    orchestrator = create_test_orchestrator(tmp_path, llm=smoke_llm)

    req = TrainingVideoRequest(
        topic="Workplace Phishing Defense Essentials",
        source_content="Phishing emails often mimic IT urgent password reset requests. Always inspect the sender domain and report suspicious emails immediately.",
        base_language="en-US",
        target_languages=["ar-SA"],
        target_duration_seconds=30,
        tone="professional",
        difficulty_level="beginner",
        audience="Corporate Employees",
    )

    project_id = "proj_smoke_phase_a"
    orchestrator.manifest_manager.create_manifest(project_id=project_id, request=req)

    manifest = orchestrator.run_project(project_id)

    # Stage 1 produces FinalScript successfully
    assert manifest.script_status == "completed", f"Script status failed with errors: {manifest.errors}"
    assert manifest.final_script is not None
    assert manifest.final_script.title == "Workplace Phishing Defense Essentials"
    assert manifest.final_script.target_duration_seconds == 30
    assert len(manifest.final_script.scenes) == 1
    assert manifest.final_script.scenes[0].estimated_duration_seconds == 30

    # Verify downstream localization was also produced
    assert manifest.localization_status == "completed"
    assert "ar-SA" in manifest.localization_bundle.localized_scripts

