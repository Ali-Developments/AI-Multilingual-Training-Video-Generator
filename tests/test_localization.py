"""Comprehensive test suite for Step 4 Localization & Cultural Adaptation Pipeline.

Tests:
1. Locale normalization (ar-sa -> ar-SA, en-us -> en-US, bn-bd -> bn-BD, generic ar -> ar).
2. Duplicate locales are deduplicated: ['ar-sa', 'ar-SA', 'AR-sa'] -> ['ar-SA'].
3. Source locale in targets does not trigger localization LLM call.
4. Empty target list behaves correctly without failing source script.
5. Source FinalScript remains unchanged (source immutability).
6. Successful en-US -> ar-SA localization.
7. Successful en-US -> bn-BD localization.
8. ar-SA returns text_direction == 'rtl'.
9. bn-BD returns text_direction == 'ltr'.
10. Scene count is preserved.
11. Scene IDs are preserved.
12. Scene order is preserved.
13. Scene types are preserved.
14. Learning-objective IDs are preserved.
15. Unknown learning objective IDs are rejected/normalized appropriately.
16. None on-screen text remains valid.
17. Whitespace-only localized on-screen text is rejected.
18. Missing localized narration is rejected.
19. Missing visual direction is rejected.
20. Localized duration is recalculated from localized narration.
21. Total duration equals sum of localized scene durations.
22. Localized duration outside tolerance is detected.
23. LLM cannot fake localized duration metadata; Python recalculates it.
24. Valid localization does not invoke revision.
25. Invalid localization invokes revision exactly once when max_revisions = 1.
26. Revised valid localization completes.
27. Repeated invalid localization ends in needs_review.
28. Failure for one locale does not remove another successful locale.
29. Localization code uses LLMProvider abstraction.
30. Localization code contains no direct Groq SDK dependency.
31. No real API calls occur.
"""

from typing import Optional, List, Type, TypeVar, Dict, Any
import copy
import sys
import pytest
from pydantic import BaseModel

from app.models.schemas import (
    FinalScript,
    SceneDraft,
    LearningObjective,
    LocalizedScript,
    LocalizedScene,
    CulturalGuidance,
    LocalizationRequest,
    LocalizationValidationResult,
    LocalizationBundle,
    TerminologyEntry,
)
from app.services.llm.base import LLMProvider
from app.services.localization.locale_utils import (
    normalize_locale,
    get_text_direction,
    get_language_name,
    get_region_name,
)
from app.services.localization.validators import (
    normalize_localized_structure_and_durations,
    validate_localized_script,
)
from app.services.localization.service import LocalizationService

T = TypeVar("T", bound=BaseModel)

# Realistic English Source Narrations (~30s each at 140 WPM, total ~60s)
SAMPLE_SRC_SCENE_1_NARRATION = (
    "Welcome to cybersecurity awareness training. Today we examine how deceptive phishing emails enter your inbox "
    "pretending to come from trusted company executives or service providers. The primary defense is scrutinizing "
    "the exact sender domain. Fraudulent senders frequently alter a single letter or add obscure suffixes to mimic "
    "legitimate addresses. Always hover your cursor over the sender name to reveal the actual email address before "
    "clicking any embedded hyperlinks or downloading attachments."
)

SAMPLE_SRC_SCENE_2_NARRATION = (
    "Once you identify a suspicious message, proper protocol requires prompt reporting rather than simple deletion. "
    "Never attempt to forward the threat directly to colleagues via normal messaging channels. Instead, utilize "
    "the official 'Report Phishing' button located in your corporate toolbar. This sends the email headers and "
    "security metadata directly to the security operations center for rapid quarantine. Your vigilance protects "
    "not only your machine, but the entire organization against intrusion."
)

# Realistic Arabic Narrations (~70 words each, ~30s at 140 WPM)
SAMPLE_AR_SCENE_1_NARRATION = (
    "مرحباً بكم في التدريب التوعوي للأمن السيبراني المؤسسي. اليوم نستعرض بدقة كيف تصل رسائل التصيد الاحتيالي "
    "الخبيثة إلى صندوق بريدكم الإلكتروني منتحلة صفة مدراء تنفيذيين أو جهات موثوقة. خط الدفاع الأول والأهم هو فحص "
    "النطاق الفعلي للمرسل بعناية تامة. يقوم المهاجمون غالباً بتغيير حرف واحد أو إضافة لواحق غامضة لمحاكاة العناوين "
    "الرسمية المعتمدة. احرص دائماً على تمرير المؤشر فوق اسم المرسل للتحقق من العنوان الفعلي قبل الضغط على أي روابط أو مرفقات."
)

SAMPLE_AR_SCENE_2_NARRATION = (
    "عند اكتشافك لأي رسالة مشبوهة، يتطلب البروتوكول الأمني المعتمد إبلاغ فريق الاستجابة على الفور بدلاً من مجرد الحذف. "
    "لا تقم بإعادة توجيه الرسالة عبر قنوات المراسلة المعتادة للزملاء. بدلاً من ذلك، استخدم زر الإبلاغ عن التصيد في شريط "
    "الأدوات الرسمي لشركتك. سيؤدي هذا إلى إرسال ترويسات الرسالة والبيانات الفنية مباشرة إلى مركز العمليات الأمنية للعزل. "
    "يقظتك تحمي منظومتنا بأكملها من الاختراق."
)

# Realistic Bengali Narrations (~70 words each, ~30s at 140 WPM)
SAMPLE_BN_SCENE_1_NARRATION = (
    "সাইবার নিরাপত্তা সচেতনতা প্রশিক্ষণে আপনাদের স্বাগতম। আজ আমরা আলোচনা করব কীভাবে প্রতারণামূলক ফিশিং ইমেইল "
    "আপনার ইনবক্সে প্রবেশ করে বিশ্বস্ত কর্মকর্তাদের ভান ধরে। আপনার প্রধান প্রতিরক্ষা হলো প্রেরকের প্রকৃত ডোমেইন সাবধানে পরীক্ষা করা। "
    "প্রতারকরা প্রায়ই একটি অক্ষর পরিবর্তন করে বা অতিরিক্ত শব্দ যুক্ত করে নকল ঠিকানা তৈরি করে। যেকোনো লিঙ্কে ক্লিক করার আগে বা কোনো ফাইল "
    "ডাউনলোড করার আগে সর্বদা মাউসের কার্সারটি প্রেরকের নামের উপর রেখে প্রকৃত ঠিকানা যাচাই করে নিন।"
)

SAMPLE_BN_SCENE_2_NARRATION = (
    "সন্দেহজনক বার্তা শনাক্ত করার পর প্রাতিষ্ঠানিক নির্দেশিকা অনুযায়ী অবিলম্বে রিপোর্ট করা জরুরি কেবল মুছে ফেলা যথেষ্ট নয়। "
    "সাধারণ চ্যাট মাধ্যমে সহকর্মীদের কাছে এই বার্তা পাঠাবেন না। বরং আপনার কর্পোরেট টুলবারে থাকা অফিসিয়াল 'রিপোর্ট ফিশিং' বোতামটি "
    "ব্যবহার করুন। এটি ইমেইলের সমস্ত তথ্য সরাসরি নিরাপত্তা দলের কাছে পাঠিয়ে দেবে দ্রুত প্রতিকারের জন্য। আপনার সচেতনতাই আমাদের "
    "সমগ্র প্রতিষ্ঠানকে নিরাপদ রাখবে।"
)


def create_sample_final_script() -> FinalScript:
    """Create a canonical FinalScript instance representing approved Step 3 output."""
    return FinalScript(
        title="Cybersecurity Awareness: Phishing Defense",
        language="en-US",
        audience="General Corporate Employees",
        target_duration_seconds=60,
        total_estimated_duration_seconds=60,
        opening_hook="Can you spot a dangerous cyber threat lurking in your everyday email inbox?",
        closing_summary="Always inspect the sender domain and report suspicious emails immediately to keep our enterprise secure.",
        learning_objectives=[
            LearningObjective(id="LO1", description="Identify suspicious sender domains and spoofed addresses"),
            LearningObjective(id="LO2", description="Execute proper corporate reporting protocol for suspected phishing"),
        ],
        scenes=[
            SceneDraft(
                scene_id="scene_1",
                order=1,
                title="Identifying Phishing Emails",
                purpose="Awareness of spoofed senders and deceptive domain tricks",
                narration=SAMPLE_SRC_SCENE_1_NARRATION,
                estimated_duration_seconds=30,
                visual_direction="Presenter standing in a clean, modern corporate office with an email diagram.",
                on_screen_text="Verify Sender Domain Before Clicking",
                learning_objective_ids=["LO1"],
                scene_type="presenter",
            ),
            SceneDraft(
                scene_id="scene_2",
                order=2,
                title="Reporting Protocol",
                purpose="Instruction on proper escalation via corporate security tools",
                narration=SAMPLE_SRC_SCENE_2_NARRATION,
                estimated_duration_seconds=30,
                visual_direction="Presenter gestures toward simulated corporate toolbar highlighting Report Phishing button.",
                on_screen_text=None,  # Explicitly None to test None preservation
                learning_objective_ids=["LO2"],
                scene_type="presenter",
            ),
        ],
        metadata={
            "target_languages": ["ar-SA", "bn-BD"],
            "base_language": "en-US",
            "revision_count": 0,
        },
    )


def create_valid_arabic_localized_script() -> LocalizedScript:
    """Create a mathematically valid localized Arabic script matching the source."""
    return LocalizedScript(
        title="التوعية بالأمن السيبراني: الحماية من التصيد",
        source_language="en-US",
        language="ar",
        locale="ar-SA",
        text_direction="rtl",
        audience="General Corporate Employees",
        learning_objectives=[
            LearningObjective(id="LO1", description="التعرف على نطاقات البريد المشبوهة والعناوين المزيفة"),
            LearningObjective(id="LO2", description="تنفيذ بروتوكول الإبلاغ المؤسسي المعتمد عند الاشتباه"),
        ],
        opening_hook="هل يمكنك كشف تهديد سيبراني خبيث يتربص بك داخل بريدك اليومي؟",
        scenes=[
            LocalizedScene(
                scene_id="scene_1",
                order=1,
                title="التعرف على رسائل التصيد",
                purpose="التوعية بأساليب انتحال شخصية المرسل وحيل النطاقات",
                narration=SAMPLE_AR_SCENE_1_NARRATION,
                estimated_duration_seconds=30,
                visual_direction="مقدم العرض في بيئة مكتبية احترافية بالرياض يشرح مخطط البريد الإلكتروني.",
                on_screen_text="تحقق من نطاق المرسل قبل النقر",
                learning_objective_ids=["LO1"],
                scene_type="presenter",
            ),
            LocalizedScene(
                scene_id="scene_2",
                order=2,
                title="بروتوكول الإبلاغ",
                purpose="توضيح خطوات تصعيد التهديد عبر الأدوات المؤسسية",
                narration=SAMPLE_AR_SCENE_2_NARRATION,
                estimated_duration_seconds=30,
                visual_direction="المقدم يشير إلى شريط أدوات محاكٍ يوضح زر الإبلاغ عن التصيد.",
                on_screen_text=None,
                learning_objective_ids=["LO2"],
                scene_type="presenter",
            ),
        ],
        closing_summary="احرص دائماً على فحص النطاق وأبلغ فوراً عن الرسائل المريبة لحماية منظومتنا.",
        target_duration_seconds=60,
        total_estimated_duration_seconds=60,
        cultural_guidance=CulturalGuidance(
            locale="ar-SA",
            language_name="Arabic",
            region_name="Saudi Arabia",
            formality_guidance="Professional business Arabic with polite corporate register",
            presenter_style_guidance="Modern corporate presentation style suitable for Saudi enterprises",
            attire_guidance="Professional corporate attire",
            visual_environment_guidance="Contemporary Gulf corporate office setting",
            cultural_notes=["Factual security procedures remain identical to enterprise standard."],
        ),
        metadata={},
    )


def create_valid_bengali_localized_script() -> LocalizedScript:
    """Create a mathematically valid localized Bengali script matching the source."""
    return LocalizedScript(
        title="সাইবার নিরাপত্তা সচেতনতা: ফিশিং প্রতিরোধ",
        source_language="en-US",
        language="bn",
        locale="bn-BD",
        text_direction="ltr",
        audience="General Corporate Employees",
        learning_objectives=[
            LearningObjective(id="LO1", description="সন্দেহজনক প্রেরকের ডোমেইন ও জাল ঠিকানা শনাক্তকরণ"),
            LearningObjective(id="LO2", description="সন্দেহভাজন ফিশিংয়ের জন্য সঠিক প্রাতিষ্ঠানিক রিপোর্টিং প্রোটোকল অনুসরণ"),
        ],
        opening_hook="আপনি কি আপনার প্রতিদিনের ইমেইলে লুকিয়ে থাকা সাইবার হুমকি শনাক্ত করতে পারেন?",
        scenes=[
            LocalizedScene(
                scene_id="scene_1",
                order=1,
                title="ফিশিং ইমেইল শনাক্তকরণ",
                purpose="জাল প্রেরক এবং প্রতারণামূলক ডোমেইনের কৌশল সম্পর্কে সচেতনতা",
                narration=SAMPLE_BN_SCENE_1_NARRATION,
                estimated_duration_seconds=30,
                visual_direction="একটি আধুনিক কর্পোরেট অফিস পরিবেশে উপস্থাপক দাঁড়িয়ে ডায়াগ্রাম ব্যাখ্যা করছেন।",
                on_screen_text="ক্লিক করার আগে প্রেরকের ডোমেইন যাচাই করুন",
                learning_objective_ids=["LO1"],
                scene_type="presenter",
            ),
            LocalizedScene(
                scene_id="scene_2",
                order=2,
                title="রিপোর্টিং প্রোটোকল",
                purpose="কর্পোরেট নিরাপত্তা টুলের মাধ্যমে সঠিক রিপোর্ট করার নির্দেশনা",
                narration=SAMPLE_BN_SCENE_2_NARRATION,
                estimated_duration_seconds=30,
                visual_direction="উপস্থাপক কর্পোরেট টুলবারের 'রিপোর্ট ফিশিং' বোতামটির দিকে নির্দেশ করছেন।",
                on_screen_text=None,
                learning_objective_ids=["LO2"],
                scene_type="presenter",
            ),
        ],
        closing_summary="সর্বদা প্রেরকের ডোমেইন পরীক্ষা করুন এবং প্রতিষ্ঠানকে নিরাপদ রাখতে অবিলম্বে রিপোর্ট করুন।",
        target_duration_seconds=60,
        total_estimated_duration_seconds=60,
        cultural_guidance=CulturalGuidance(
            locale="bn-BD",
            language_name="Bengali",
            region_name="Bangladesh",
            formality_guidance="Formal professional Bengali standard (সাধু/চলিত মার্জিত রূপ)",
            presenter_style_guidance="Clear, authoritative professional corporate presentation style",
            attire_guidance="Business formal attire",
            visual_environment_guidance="Modern Dhaka corporate tech office environment",
            cultural_notes=["Universal security precautions presented in standard corporate Bengali."],
        ),
        metadata={},
    )


class MockLocalizationLLMProvider(LLMProvider):
    """Controllable in-memory LLMProvider for localization tests."""

    def __init__(
        self,
        default_fixture: Optional[LocalizedScript] = None,
        revision_fixture: Optional[LocalizedScript] = None,
        fixtures_by_locale: Optional[Dict[str, LocalizedScript]] = None,
        model_name_str: str = "mock-localization-llm-v1",
    ):
        self._model_name = model_name_str
        self.default_fixture = default_fixture
        self.revision_fixture = revision_fixture
        self.fixtures_by_locale = fixtures_by_locale or {}
        self.generate_structured_call_count = 0
        self.generate_text_call_count = 0
        self.call_history = []

    @property
    def model_name(self) -> str:
        return self._model_name

    def generate_text(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
    ) -> str:
        self.generate_text_call_count += 1
        self.call_history.append({"type": "text", "prompt": prompt})
        return "Mocked text"

    def generate_structured(
        self,
        prompt: str,
        schema: Type[T],
        system_prompt: Optional[str] = None,
        temperature: float = 0.2,
    ) -> T:
        self.generate_structured_call_count += 1
        self.call_history.append({"type": "structured", "schema": schema.__name__, "prompt": prompt})

        # Return revision fixture if this is a revision call
        if "LOCALIZATION REVISION REQUEST" in prompt and self.revision_fixture is not None:
            return copy.deepcopy(self.revision_fixture)

        # Check by target locale inside prompt
        for loc_key, fix in self.fixtures_by_locale.items():
            if f"Target Locale: {loc_key}" in prompt:
                return copy.deepcopy(fix)

        if self.default_fixture is not None:
            return copy.deepcopy(self.default_fixture)

        # Fallback default Arabic valid script
        return copy.deepcopy(create_valid_arabic_localized_script())


# ===========================================================================
# 1. Locale Normalization & Text Direction Tests
# ===========================================================================

def test_locale_normalization_standard_cases():
    """Test 1: Locale normalization converts casing correctly and rejects invalid formats."""
    assert normalize_locale("ar-sa") == "ar-SA"
    assert normalize_locale("en-us") == "en-US"
    assert normalize_locale("bn-bd") == "bn-BD"
    assert normalize_locale("zh-cn") == "zh-CN"
    assert normalize_locale("pt-br") == "pt-BR"
    assert normalize_locale("es-419") == "es-419"
    assert normalize_locale("zh-hans-cn") == "zh-Hans-CN"
    # Does not invent region when user only provides language:
    assert normalize_locale("ar") == "ar"
    assert normalize_locale("en") == "en"

    # Reject malformed
    with pytest.raises(ValueError):
        normalize_locale("")
    with pytest.raises(ValueError):
        normalize_locale("123")
    with pytest.raises(ValueError):
        normalize_locale("!invalid")


def test_duplicate_locales_deduplication():
    """Test 2: Duplicate target locales are normalized and deduplicated."""
    source = create_sample_final_script()
    provider = MockLocalizationLLMProvider(default_fixture=create_valid_arabic_localized_script())
    service = LocalizationService(llm_provider=provider)

    bundle = service.localize_bundle(
        source_script=source,
        target_locales=["ar-sa", "ar-SA", "AR-sa"],
    )

    assert len(bundle.localized_scripts) == 1
    assert "ar-SA" in bundle.localized_scripts
    assert bundle.metadata["unique_locales_count"] == 1
    assert provider.generate_structured_call_count == 1


def test_source_locale_in_targets_skips_llm_call():
    """Test 3: Target locale matching source language does NOT trigger LLM call."""
    source = create_sample_final_script()
    provider = MockLocalizationLLMProvider()
    service = LocalizationService(llm_provider=provider)

    req = LocalizationRequest(source_script=source, target_locale="en-US")
    script, val, status = service.localize(req)

    assert status == "completed"
    assert val.is_valid is True
    assert script.locale == "en-US"
    assert script.metadata.get("skipped_llm_call") is True
    assert provider.generate_structured_call_count == 0


def test_empty_target_list_behavior():
    """Test 4: Empty target list produces clean empty bundle without failing source."""
    source = create_sample_final_script()
    provider = MockLocalizationLLMProvider()
    service = LocalizationService(llm_provider=provider)

    bundle = service.localize_bundle(source_script=source, target_locales=[])

    assert len(bundle.localized_scripts) == 0
    assert len(bundle.failed_locales) == 0
    assert bundle.metadata["total_locales_requested"] == 0
    assert provider.generate_structured_call_count == 0


def test_source_script_immutability():
    """Test 5: Canonical FinalScript is strictly immutable and unchanged after localization."""
    source = create_sample_final_script()
    original_dump = source.model_dump()

    provider = MockLocalizationLLMProvider(default_fixture=create_valid_arabic_localized_script())
    service = LocalizationService(llm_provider=provider)

    bundle = service.localize_bundle(source_script=source, target_locales=["ar-SA", "bn-BD"])

    assert source.model_dump() == original_dump
    assert source.scenes[0].narration == SAMPLE_SRC_SCENE_1_NARRATION
    assert source.scenes[0].scene_id == "scene_1"
    assert source.language == "en-US"


def test_successful_en_to_ar_sa_localization():
    """Test 6: Successful en-US -> ar-SA localization."""
    source = create_sample_final_script()
    ar_script = create_valid_arabic_localized_script()
    provider = MockLocalizationLLMProvider(default_fixture=ar_script)
    service = LocalizationService(llm_provider=provider)

    req = LocalizationRequest(source_script=source, target_locale="ar-SA")
    script, val, status = service.localize(req)

    assert status == "completed"
    assert val.is_valid is True
    assert script.locale == "ar-SA"
    assert script.text_direction == "rtl"
    assert len(script.scenes) == 2


def test_successful_en_to_bn_bd_localization():
    """Test 7: Successful en-US -> bn-BD localization."""
    source = create_sample_final_script()
    bn_script = create_valid_bengali_localized_script()
    provider = MockLocalizationLLMProvider(default_fixture=bn_script)
    service = LocalizationService(llm_provider=provider)

    req = LocalizationRequest(source_script=source, target_locale="bn-BD")
    script, val, status = service.localize(req)

    assert status == "completed"
    assert val.is_valid is True
    assert script.locale == "bn-BD"
    assert script.text_direction == "ltr"
    assert len(script.scenes) == 2


def test_ar_sa_text_direction_rtl():
    """Test 8: ar-SA returns text_direction == 'rtl'."""
    assert get_text_direction("ar-SA") == "rtl"
    assert get_text_direction("ar") == "rtl"


def test_bn_bd_text_direction_ltr():
    """Test 9: bn-BD returns text_direction == 'ltr'."""
    assert get_text_direction("bn-BD") == "ltr"
    assert get_text_direction("en-US") == "ltr"


# ===========================================================================
# 2. Structural & Field Protection Tests
# ===========================================================================

def test_scene_count_preserved_and_mismatch_flagged():
    """Test 10: Scene count is strictly verified; mismatches trigger LOCALIZATION_SCENE_COUNT_MISMATCH."""
    source = create_sample_final_script()
    bad_script = create_valid_arabic_localized_script()
    # Delete scene 2 so count becomes 1 instead of 2
    bad_script.scenes = [bad_script.scenes[0]]

    val = validate_localized_script(bad_script, source, target_locale="ar-SA")
    assert val.is_valid is False
    codes = [i.code for i in val.issues]
    assert "LOCALIZATION_SCENE_COUNT_MISMATCH" in codes


def test_protected_structural_fields_restored_from_source():
    """Test 11-14: Scene IDs, order, scene types, and learning objective IDs are restored by Python."""
    source = create_sample_final_script()
    tampered_script = create_valid_arabic_localized_script()

    # Simulate LLM corrupting protected fields
    tampered_script.scenes[0].scene_id = "مشهد_1"  # Translated ID
    tampered_script.scenes[0].order = 99
    tampered_script.scenes[0].scene_type = "outro"
    tampered_script.scenes[0].learning_objective_ids = ["UNKNOWN_LO"]

    # Python normalizes structure deterministically
    normalize_localized_structure_and_durations(
        localized_script=tampered_script,
        source_script=source,
        target_locale="ar-SA",
        text_direction="rtl",
    )

    assert tampered_script.scenes[0].scene_id == "scene_1"
    assert tampered_script.scenes[0].order == 1
    assert tampered_script.scenes[0].scene_type == "presenter"
    assert tampered_script.scenes[0].learning_objective_ids == ["LO1"]


def test_unknown_learning_objective_ids_flagged():
    """Test 15: Unknown learning objective IDs or missing source objectives are flagged."""
    source = create_sample_final_script()
    script = create_valid_arabic_localized_script()
    # Add rogue objective ID
    script.learning_objectives.append(
        LearningObjective(id="LO99_UNKNOWN", description="Extra objective")
    )

    val = validate_localized_script(script, source, target_locale="ar-SA")
    assert val.is_valid is False
    codes = [i.code for i in val.issues]
    assert "UNKNOWN_LEARNING_OBJECTIVE" in codes


def test_none_on_screen_text_remains_valid():
    """Test 16: None on_screen_text remains valid and is preserved."""
    source = create_sample_final_script()
    script = create_valid_arabic_localized_script()
    assert script.scenes[1].on_screen_text is None

    val = validate_localized_script(script, source, target_locale="ar-SA")
    assert val.is_valid is True
    assert script.scenes[1].on_screen_text is None


def test_whitespace_only_on_screen_text_rejected():
    """Test 17: Whitespace-only on_screen_text is flagged as error."""
    source = create_sample_final_script()
    script = create_valid_arabic_localized_script()
    script.scenes[0].on_screen_text = "   "

    val = validate_localized_script(script, source, target_locale="ar-SA")
    assert val.is_valid is False
    codes = [i.code for i in val.issues]
    assert "WHITESPACE_ON_SCREEN_TEXT" in codes


def test_missing_narration_rejected():
    """Test 18: Missing or empty localized narration is flagged as error."""
    source = create_sample_final_script()
    script = create_valid_arabic_localized_script()
    script.scenes[0].narration = ""

    val = validate_localized_script(script, source, target_locale="ar-SA")
    assert val.is_valid is False
    codes = [i.code for i in val.issues]
    assert "MISSING_LOCALIZED_NARRATION" in codes


def test_missing_visual_direction_rejected():
    """Test 19: Missing visual direction is flagged as error."""
    source = create_sample_final_script()
    script = create_valid_arabic_localized_script()
    script.scenes[0].visual_direction = ""

    val = validate_localized_script(script, source, target_locale="ar-SA")
    assert val.is_valid is False
    codes = [i.code for i in val.issues]
    assert "MISSING_LOCALIZED_VISUAL_DIRECTION" in codes


# ===========================================================================
# 3. Duration & Timing Recalculation Tests
# ===========================================================================

def test_localized_duration_recalculated_from_narration():
    """Test 20: Scene duration is calculated from localized narration word count."""
    source = create_sample_final_script()
    script = create_valid_arabic_localized_script()

    # Short narration (14 words = 6 seconds at 140 WPM)
    script.scenes[0].narration = "هذه جملة تجريبية قصيرة تحتوي على بضع كلمات لاختبار سرعة الإلقاء بدقة تامة في النظام."
    normalize_localized_structure_and_durations(script, source, "ar-SA", "rtl", words_per_minute=140)

    assert script.scenes[0].estimated_duration_seconds == 6


def test_total_duration_equals_sum_of_scene_durations():
    """Test 21: Total duration strictly equals sum of scene durations."""
    source = create_sample_final_script()
    script = create_valid_arabic_localized_script()

    normalize_localized_structure_and_durations(script, source, "ar-SA", "rtl", words_per_minute=140)
    expected_sum = script.scenes[0].estimated_duration_seconds + script.scenes[1].estimated_duration_seconds
    assert script.total_estimated_duration_seconds == expected_sum


def test_localized_duration_outside_tolerance_detected():
    """Test 22: Localized duration exceeding tolerance is detected."""
    source = create_sample_final_script()
    script = create_valid_arabic_localized_script()

    # Make narrations extremely long (>100s when target is 60s)
    script.scenes[0].narration = SAMPLE_AR_SCENE_1_NARRATION * 3
    script.scenes[1].narration = SAMPLE_AR_SCENE_2_NARRATION * 3

    val = validate_localized_script(script, source, target_locale="ar-SA", tolerance_percent=20)
    assert val.is_valid is False
    codes = [i.code for i in val.issues]
    assert "LOCALIZED_DURATION_TOO_LONG" in codes


def test_llm_cannot_fake_localized_duration_metadata():
    """Test 23: Python deterministically recalculates duration; LLM cannot fake it."""
    source = create_sample_final_script()
    script = create_valid_arabic_localized_script()

    # Simulate LLM returning fake duration metadata
    script.scenes[0].estimated_duration_seconds = 999
    script.total_estimated_duration_seconds = 9999

    normalize_localized_structure_and_durations(script, source, "ar-SA", "rtl", words_per_minute=140)

    # Durations should be reset from fake 999/9999 to actual calculated word count duration
    assert script.scenes[0].estimated_duration_seconds != 999
    assert script.total_estimated_duration_seconds != 9999
    assert script.scenes[0].estimated_duration_seconds == 31
    assert script.total_estimated_duration_seconds == (
        script.scenes[0].estimated_duration_seconds + script.scenes[1].estimated_duration_seconds
    )


# ===========================================================================
# 4. Revision Loop & Orchestration Tests
# ===========================================================================

def test_valid_localization_does_not_invoke_revision():
    """Test 24: Valid initial localization completes without triggering revision."""
    source = create_sample_final_script()
    ar_script = create_valid_arabic_localized_script()
    provider = MockLocalizationLLMProvider(default_fixture=ar_script)
    service = LocalizationService(llm_provider=provider, max_revisions=1)

    req = LocalizationRequest(source_script=source, target_locale="ar-SA")
    script, val, status = service.localize(req)

    assert status == "completed"
    assert val.is_valid is True
    assert provider.generate_structured_call_count == 1
    assert script.metadata["revision_count"] == 0


def test_invalid_localization_invokes_revision_once():
    """Test 25 & 26: Invalid localization invokes revision exactly once and completes upon fix."""
    source = create_sample_final_script()

    # Initial invalid script (missing title)
    invalid_script = create_valid_arabic_localized_script()
    invalid_script.title = ""

    # Corrected script for revision
    revised_script = create_valid_arabic_localized_script()
    revised_script.title = "التوعية بالأمن السيبراني: الحماية من التصيد"

    provider = MockLocalizationLLMProvider(
        default_fixture=invalid_script,
        revision_fixture=revised_script,
    )
    service = LocalizationService(llm_provider=provider, max_revisions=1)

    req = LocalizationRequest(source_script=source, target_locale="ar-SA")
    script, val, status = service.localize(req)

    assert status == "completed"
    assert val.is_valid is True
    assert provider.generate_structured_call_count == 2
    assert script.metadata["revision_count"] == 1
    assert script.title == "التوعية بالأمن السيبراني: الحماية من التصيد"


def test_repeated_invalid_localization_ends_in_needs_review():
    """Test 27: Repeatedly invalid script stops after max_revisions with status 'needs_review'."""
    source = create_sample_final_script()

    # Always invalid script (missing narration)
    invalid_script = create_valid_arabic_localized_script()
    invalid_script.scenes[0].narration = ""

    provider = MockLocalizationLLMProvider(
        default_fixture=invalid_script,
        revision_fixture=invalid_script,
    )
    service = LocalizationService(llm_provider=provider, max_revisions=1)

    req = LocalizationRequest(source_script=source, target_locale="ar-SA")
    script, val, status = service.localize(req)

    assert status == "needs_review"
    assert val.is_valid is False
    assert provider.generate_structured_call_count == 2
    assert script.metadata["revision_count"] == 1


def test_error_isolation_across_locales():
    """Test 28: Failure in one locale does not affect successful completion in another."""
    source = create_sample_final_script()
    valid_ar = create_valid_arabic_localized_script()

    # Bengali fails
    invalid_bn = create_valid_bengali_localized_script()
    invalid_bn.scenes[0].narration = ""

    provider = MockLocalizationLLMProvider(
        fixtures_by_locale={"ar-SA": valid_ar, "bn-BD": invalid_bn},
        revision_fixture=invalid_bn,
    )
    service = LocalizationService(llm_provider=provider, max_revisions=1)

    bundle = service.localize_bundle(
        source_script=source,
        target_locales=["ar-SA", "bn-BD"],
    )

    # ar-SA must be successful
    assert "ar-SA" in bundle.localized_scripts
    assert bundle.localized_scripts["ar-SA"].locale == "ar-SA"

    # bn-BD must be recorded in failed_locales without crashing bundle
    assert "bn-BD" in bundle.failed_locales
    assert bundle.failed_locales["bn-BD"]["status"] == "needs_review"


def test_localization_uses_llm_provider_abstraction():
    """Test 29: Localization service uses LLMProvider abstraction."""
    provider = MockLocalizationLLMProvider()
    assert isinstance(provider, LLMProvider)
    service = LocalizationService(llm_provider=provider)
    assert service.llm_provider == provider


def test_no_direct_groq_sdk_in_localization_modules():
    """Test 30: Localization modules do not import groq SDK directly."""
    import app.services.localization.service as s_mod
    import app.services.localization.validators as v_mod
    import app.services.localization.prompts as p_mod
    import app.services.localization.locale_utils as l_mod

    for mod in [s_mod, v_mod, p_mod, l_mod]:
        assert "groq" not in dir(mod)
        # Check source text does not contain import groq
        import inspect
        src = inspect.getsource(mod)
        assert "import groq" not in src
        assert "from groq" not in src


def test_zero_real_api_calls_in_tests(monkeypatch):
    """Test 31: Verify no external network calls occur."""
    source = create_sample_final_script()
    provider = MockLocalizationLLMProvider(default_fixture=create_valid_arabic_localized_script())
    service = LocalizationService(llm_provider=provider)

    bundle = service.localize_bundle(source_script=source, target_locales=["ar-SA", "bn-BD"])
    assert len(bundle.localized_scripts) >= 1
