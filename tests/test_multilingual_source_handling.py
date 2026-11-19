"""Focused test suite for Multilingual Source Language Handling & Cross-Language Script Generation.

Covers:
1. English source -> Arabic canonical script (including Egyptian Macaroni Béchamel acceptance case).
2. Arabic source -> English canonical script.
3. Mixed Arabic/English source -> Arabic canonical script.
4. French source -> German output.
5. Urdu source -> English output (and Arabic-script disambiguation).
6. Bengali source -> Arabic output.
7. Empty source content with a valid topic.
8. Unsupported locale handling (HTTP 422 / ValidationError).
9. Existing English-to-English workflows.
10. Existing Arabic-to-Arabic workflows.
11. Correct localization when source and target languages match (and protection against unlocalized English mirroring).
12. Correct handling of uncertain language detection.
"""

from pathlib import Path
from typing import Dict, Optional, Type, TypeVar
import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel, ValidationError

from app.core.config import settings
from app.core.language import (
    detect_source_language,
    verify_output_language,
)
from app.main import create_app
from app.models.schemas import (
    ContentAnalysis,
    CulturalGuidance,
    FinalScript,
    LearningObjective,
    LocalizationRequest,
    LocalizedScene,
    LocalizedScript,
    SceneDraft,
    ScriptDraft,
    TrainingVideoRequest,
)
from app.services.llm.base import LLMProvider
from app.services.localization.service import LocalizationService
from app.workflows.script_generation.graph import create_script_workflow
from app.workflows.script_generation.state import VideoScriptState
from app.workflows.script_generation.validators import validate_script_draft

T = TypeVar("T", bound=BaseModel)


# ---------------------------------------------------------------------------
# Realistic Multilingual Narration Fixtures (~30s at locale-calibrated WPM)
# ---------------------------------------------------------------------------

# 58 words in Arabic (~30s at 115 WPM)
ARABIC_BECHAMEL_NARRATION_30S = (
    "مرحباً بكم في درس تحضير المكرونة بالبشاميل المصرية الأصيلة في مطبخكم خطوة بخطوة. "
    "نبدأ أولاً بسلق المكرونة القلم في ماء مغلي مملح حتى تنضج بشكل مثالي ومتماسك. "
    "بعد ذلك نقوم بتعصيج اللحم المفروم مع البصل المفروم والثوم والملح والفلفل الأسود والقرفة. "
    "ثم نحضر صلصة البشاميل الكريمية بمزج الزبدة والدقيق والحليب الدافئ ونرتب الطبقات ونخبزها بالفرن."
)

# 70 words in English (~30s at 140 WPM)
ENGLISH_KABSA_NARRATION_30S = (
    "Welcome to our culinary training module on preparing authentic traditional Saudi chicken kabsa step by step. "
    "Begin by gently sauteing sliced onions and fresh tomatoes with whole aromatic spices including cardamom, cinnamon, "
    "cloves, and dried black lime in a heavy pot. Next, add the chicken pieces and simmer in rich seasoned broth "
    "until tender. Finally, cook the washed basmati rice in the flavorful broth and garnish with toasted almonds."
)

# 70 words in German (~30s at 140 WPM)
GERMAN_TRAINING_NARRATION_30S = (
    "Willkommen zu unserem Schulungsmodul für Informationssicherheit und Datenschutz im modernen Unternehmen für alle Mitarbeiter. "
    "Heute lernen wir, wie Sie verdächtige Nachrichten in Ihrem Posteingang frühzeitig erkennen und sicher überprüfen können. "
    "Kontrollieren Sie immer zuerst die vollständige Absenderadresse und klicken Sie niemals unüberlegt auf unbekannte Anhänge oder Links. "
    "Melden Sie jeden Verdachtsfall sofort über die offizielle Schaltfläche an unser Sicherheitsteam, um alle Systeme dauerhaft zu schützen."
)


class MultilingualAwareMockLLM(LLMProvider):
    """
    Mock LLM provider that inspects the prompt's requested Canonical Output Language
    or Target Locale and returns structured scripts in the requested language.
    """

    def __init__(self, fail_first_language_attempt: bool = False):
        self.fail_first_language_attempt = fail_first_language_attempt
        self.script_calls = 0
        self.analysis_calls = 0
        self.localization_calls = 0
        self.prompts_received = []

    @property
    def model_name(self) -> str:
        return "mock-multilingual-llm"

    def generate_text(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
    ) -> str:
        return "mock text"

    def generate_structured(
        self,
        prompt: str,
        schema: Type[T],
        system_prompt: Optional[str] = None,
        temperature: float = 0.2,
        **kwargs,
    ) -> T:
        self.prompts_received.append({"schema": schema.__name__, "prompt": prompt})

        output_labels = ("Canonical Output Language: ", "Language: ", "Target Locale: ", "Required Canonical Language: ")
        output_lines = [line for line in prompt.splitlines() if line.lstrip("- ").startswith(output_labels)]
        wants_arabic = any("ar-SA" in line for line in output_lines)
        wants_german = any("de-DE" in line for line in output_lines)

        if schema == ContentAnalysis:
            self.analysis_calls += 1
            if wants_arabic:
                return ContentAnalysis(
                    topic_summary="تحضير المكرونة بالبشاميل المصرية الأصيلة",
                    key_concepts=["سلق المكرونة", "تعصيج اللحم", "صلصة البشاميل"],
                    learning_objectives=[
                        LearningObjective(id="LO1", description="إعداد صلصة البشاميل وتجهيز طبقات المكرونة بالفرن"),
                    ],
                    audience_notes="الطهاة وعشاق المطبخ",
                    recommended_scene_count=1,
                    recommended_structure=["التحضير والخبز"],
                    important_terms=["Béchamel", "Penne"],
                    factual_constraints=["ضبط قوام البشاميل"],
                )
            elif wants_german:
                return ContentAnalysis(
                    topic_summary="Grundlagen der Informationssicherheit im Unternehmen",
                    key_concepts=["Absenderprüfung", "Vorfallmeldung"],
                    learning_objectives=[
                        LearningObjective(id="LO1", description="Verdächtige E-Mails erkennen und sicher melden"),
                    ],
                    audience_notes="Mitarbeiter im Unternehmen",
                    recommended_scene_count=1,
                    recommended_structure=["Einführung und Praxis"],
                    important_terms=["Phishing", "IT-Sicherheit"],
                    factual_constraints=["Immer Absender prüfen"],
                )
            else:
                return ContentAnalysis(
                    topic_summary="Authentic Culinary & Security Training",
                    key_concepts=["Preparation", "Execution"],
                    learning_objectives=[
                        LearningObjective(id="LO1", description="Master step-by-step preparation technique"),
                    ],
                    audience_notes="General learners",
                    recommended_scene_count=1,
                    recommended_structure=["Main Demonstration"],
                    important_terms=["Kabsa", "Basmati"],
                    factual_constraints=["Follow exact steps"],
                )

        if schema == ScriptDraft:
            self.script_calls += 1
            # Simulate an LLM that mistakenly outputs English on Attempt 1 when Arabic was requested
            if self.fail_first_language_attempt and self.script_calls == 1 and wants_arabic:
                return ScriptDraft(
                    title="Egyptian Macaroni Bechamel",
                    language="en-US",
                    audience="Cooks",
                    learning_objectives=[
                        LearningObjective(id="LO1", description="Prepare bechamel sauce"),
                    ],
                    opening_hook="Let us make Egyptian macaroni bechamel in English.",
                    closing_summary="Serve warm and enjoy.",
                    scenes=[
                        SceneDraft(
                            scene_id="scene_1",
                            order=1,
                            title="Preparation",
                            purpose="Demonstrate cooking",
                            scene_type="demonstration",
                            narration=ENGLISH_KABSA_NARRATION_30S,
                            visual_direction="Kitchen counter view.",
                            on_screen_text="Boil Pasta & Make Sauce",
                            learning_objective_ids=["LO1"],
                            estimated_duration_seconds=30,
                        )
                    ],
                    total_estimated_duration_seconds=30,
                )

            if wants_arabic:
                return ScriptDraft(
                    title="طريقة تحضير المكرونة بالبشاميل المصرية",
                    language="ar-SA",
                    audience="الطهاة المبتدئون",
                    learning_objectives=[
                        LearningObjective(id="LO1", description="إعداد صلصة البشاميل وتجهيز طبقات المكرونة بالفرن"),
                    ],
                    opening_hook="هل ترغب في تحضير أشهى صينية مكرونة بالبشاميل مصرية بقوام كريمي متقن؟",
                    closing_summary="قدم المكرونة بالبشاميل ساخنة بعد أن تهدأ قليلاً واستمتع بمذاقها الأصيل.",
                    scenes=[
                        SceneDraft(
                            scene_id="scene_1",
                            order=1,
                            title="خطوات التحضير والخبز",
                            purpose="شرح سلق المكرونة وتعصيج اللحم وتحضير البشاميل",
                            scene_type="demonstration",
                            narration=ARABIC_BECHAMEL_NARRATION_30S,
                            visual_direction="عرض خطوات خفق الزبدة والدقيق مع الحليب وترتيب طبقات المكرونة.",
                            on_screen_text="تحضير البشاميل وترتيب الطبقات",
                            learning_objective_ids=["LO1"],
                            estimated_duration_seconds=30,
                        )
                    ],
                    total_estimated_duration_seconds=30,
                )

            if wants_german:
                return ScriptDraft(
                    title="Informationssicherheit am Arbeitsplatz",
                    language="de-DE",
                    audience="Mitarbeiter",
                    learning_objectives=[
                        LearningObjective(id="LO1", description="Verdächtige E-Mails erkennen und sicher melden"),
                    ],
                    opening_hook="Wie erkennen Sie gefährliche Nachrichten sofort in Ihrem täglichen Postfach?",
                    closing_summary="Prüfen Sie stets den Absender und melden Sie jeden Verdacht an das Sicherheitsteam.",
                    scenes=[
                        SceneDraft(
                            scene_id="scene_1",
                            order=1,
                            title="Prüfung und Meldung",
                            purpose="Schulung zur E-Mail-Prüfung",
                            scene_type="presenter",
                            narration=GERMAN_TRAINING_NARRATION_30S,
                            visual_direction="Präsentation der Absenderprüfung im E-Mail-Programm.",
                            on_screen_text="Absender immer prüfen",
                            learning_objective_ids=["LO1"],
                            estimated_duration_seconds=30,
                        )
                    ],
                    total_estimated_duration_seconds=30,
                )

            return ScriptDraft(
                title="Traditional Culinary & Operational Guide",
                language="en-US",
                audience="Learners",
                learning_objectives=[
                    LearningObjective(id="LO1", description="Master step-by-step preparation technique"),
                ],
                opening_hook="Ready to master this step-by-step instructional technique with confidence?",
                closing_summary="Follow these essential steps carefully for consistent results every time.",
                scenes=[
                    SceneDraft(
                        scene_id="scene_1",
                        order=1,
                        title="Core Process",
                        purpose="Demonstrate key steps",
                        scene_type="demonstration",
                        narration=ENGLISH_KABSA_NARRATION_30S,
                        visual_direction="Step-by-step demonstration of the preparation workflow.",
                        on_screen_text="Follow Key Steps",
                        learning_objective_ids=["LO1"],
                        estimated_duration_seconds=30,
                    )
                ],
                total_estimated_duration_seconds=30,
            )

        if schema == LocalizedScript:
            self.localization_calls += 1
            if wants_arabic:
                return LocalizedScript(
                    title="طريقة تحضير المكرونة بالبشاميل المصرية",
                    source_language="en-US",
                    language="ar-SA",
                    locale="ar-SA",
                    text_direction="rtl",
                    audience="الطهاة",
                    learning_objectives=[
                        LearningObjective(id="LO1", description="إعداد صلصة البشاميل وتجهيز طبقات المكرونة بالفرن"),
                    ],
                    opening_hook="هل ترغب في تحضير أشهى صينية مكرونة بالبشاميل مصرية؟",
                    scenes=[
                        LocalizedScene(
                            scene_id="scene_1",
                            order=1,
                            title="خطوات التحضير",
                            purpose="شرح الخطوات",
                            narration=ARABIC_BECHAMEL_NARRATION_30S,
                            estimated_duration_seconds=30,
                            visual_direction="عرض خطوات التحضير في المطبخ.",
                            on_screen_text="تحضير البشاميل",
                            learning_objective_ids=["LO1"],
                            scene_type="demonstration",
                        )
                    ],
                    closing_summary="قدمها ساخنة واستمتع بمذاقها.",
                    target_duration_seconds=30,
                    total_estimated_duration_seconds=30,
                    cultural_guidance=CulturalGuidance(
                        locale="ar-SA",
                        language_name="Arabic",
                        region_name="Saudi Arabia",
                        cultural_notes=["Translated into Arabic."],
                    ),
                    metadata={},
                )

            if wants_german:
                return LocalizedScript(
                    title="Informationssicherheit am Arbeitsplatz",
                    source_language="fr-FR",
                    language="de-DE",
                    locale="de-DE",
                    text_direction="ltr",
                    audience="Mitarbeiter",
                    learning_objectives=[
                        LearningObjective(id="LO1", description="Verdächtige E-Mails erkennen und sicher melden"),
                    ],
                    opening_hook="Wie erkennen Sie gefährliche Nachrichten sofort?",
                    scenes=[
                        LocalizedScene(
                            scene_id="scene_1",
                            order=1,
                            title="Prüfung und Meldung",
                            purpose="Schulung",
                            narration=GERMAN_TRAINING_NARRATION_30S,
                            estimated_duration_seconds=30,
                            visual_direction="Präsentation im Büro.",
                            on_screen_text="Absender prüfen",
                            learning_objective_ids=["LO1"],
                            scene_type="presenter",
                        )
                    ],
                    closing_summary="Prüfen Sie stets den Absender.",
                    target_duration_seconds=30,
                    total_estimated_duration_seconds=30,
                    cultural_guidance=CulturalGuidance(
                        locale="de-DE",
                        language_name="German",
                        region_name="Germany",
                        cultural_notes=["Translated into German."],
                    ),
                    metadata={},
                )

            return LocalizedScript(
                title="Traditional Culinary & Operational Guide",
                source_language="ar-SA",
                language="en-US",
                locale="en-US",
                text_direction="ltr",
                audience="Learners",
                learning_objectives=[
                    LearningObjective(id="LO1", description="Master step-by-step preparation technique"),
                ],
                opening_hook="Ready to master this step-by-step instructional technique?",
                scenes=[
                    LocalizedScene(
                        scene_id="scene_1",
                        order=1,
                        title="Core Process",
                        purpose="Demonstrate key steps",
                        narration=ENGLISH_KABSA_NARRATION_30S,
                        estimated_duration_seconds=30,
                        visual_direction="Step-by-step demonstration.",
                        on_screen_text="Follow Key Steps",
                        learning_objective_ids=["LO1"],
                        scene_type="demonstration",
                    )
                ],
                closing_summary="Follow these essential steps carefully.",
                target_duration_seconds=30,
                total_estimated_duration_seconds=30,
                cultural_guidance=CulturalGuidance(
                    locale="en-US",
                    language_name="English",
                    region_name="United States",
                    cultural_notes=["Translated into English."],
                ),
                metadata={},
            )

        raise ValueError(f"Unsupported schema: {schema}")


# ===========================================================================
# 1. English Source -> Arabic Canonical Script (Béchamel Acceptance Test)
# ===========================================================================

def test_1_english_source_to_arabic_canonical_script_bechamel(tmp_path, monkeypatch):
    """
    Acceptance Criteria:
    User enters English cooking instructions for Egyptian macaroni béchamel,
    selects Arabic ('ar-SA') as canonical script language and 'ar-SA' as target output.
    Request succeeds without HTTP 422, canonical narration is generated in Arabic,
    and localization mirrors valid Arabic without LLM re-translation.
    """
    req = TrainingVideoRequest(
        topic="Egyptian Macaroni Béchamel Preparation",
        source_content=(
            "Boil penne pasta until al dente. Brown minced beef with onions, garlic, salt, black pepper, "
            "and a pinch of cinnamon. Prepare creamy béchamel sauce by whisking butter, flour, and warm milk "
            "until smooth, then layer pasta, spiced meat, and béchamel in a baking dish and bake until golden."
        ),
        base_language="ar-SA",
        target_languages=["ar-SA"],
        target_duration_seconds=30,
        video_style="demonstration_tutorial",
    )

    assert req.base_language == "ar-SA"
    assert req.canonical_language == "ar-SA"
    assert req.detected_source_language == "en-US"
    assert len(req.language_warnings) == 1
    assert "English" in req.language_warnings[0]
    assert "Arabic" in req.language_warnings[0]

    # Run Stage 1 script generation workflow
    mock_llm = MultilingualAwareMockLLM()
    workflow = create_script_workflow(llm_provider=mock_llm)
    state = workflow.invoke(VideoScriptState(request=req))

    assert state["workflow_status"] == "completed"
    final_script: FinalScript = state["final_script"]
    assert final_script is not None
    assert final_script.language == "ar-SA"
    lang_ok, _ = verify_output_language(final_script.scenes[0].narration, "ar-SA")
    assert lang_ok is True

    # Run Stage 2 localization for ar-SA: since canonical script is genuinely Arabic, it mirrors cleanly
    loc_service = LocalizationService(llm_provider=mock_llm)
    bundle = loc_service.localize_bundle(source_script=final_script, target_locales=["ar-SA"])
    assert "ar-SA" in bundle.localized_scripts
    assert mock_llm.localization_calls == 0
    assert bundle.localized_scripts["ar-SA"].text_direction == "rtl"


# ===========================================================================
# 2. Arabic Source -> English Canonical Script
# ===========================================================================

def test_2_arabic_source_to_english_canonical_script():
    """Verify Arabic source material with English canonical script ('en-US') succeeds without HTTP 422."""
    req = TrainingVideoRequest(
        topic="طريقة تحضير الكبسة السعودية الأصيلة بالدجاج",
        source_content=(
            "تشويح البصل والطماطم مع البهارات الصحيحة مثل الهيل والقرفة والقرنفل واللومي، "
            "ثم إضافة الدجاج والمرق وطهي أرز البسمتي على نار هادئة وتقديمه مع اللوز المحمص."
        ),
        base_language="en-US",
        target_languages=["en-US"],
        target_duration_seconds=30,
    )

    assert req.base_language == "en-US"
    assert req.detected_source_language == "ar-SA"
    assert len(req.language_warnings) == 1
    assert "Arabic" in req.language_warnings[0]

    mock_llm = MultilingualAwareMockLLM()
    workflow = create_script_workflow(llm_provider=mock_llm)
    state = workflow.invoke(VideoScriptState(request=req))

    assert state["workflow_status"] == "completed"
    final_script: FinalScript = state["final_script"]
    assert final_script.language == "en-US"
    lang_ok, _ = verify_output_language(final_script.scenes[0].narration, "en-US")
    assert lang_ok is True


# ===========================================================================
# 3. Mixed Arabic/English Source -> Arabic Canonical Script
# ===========================================================================

def test_3_mixed_arabic_english_source_to_arabic_canonical():
    """Verify mixed Arabic topic + English technical/culinary notes succeeds and detects mixed content."""
    req = TrainingVideoRequest(
        topic="تحضير المكرونة بالبشاميل وتقنيات الـ Roux والـ Béchamel",
        source_content=(
            "Use equal parts butter and flour for the white roux, then whisk in warm milk gradually. "
            "يتم إضافة جوزة الطيب والملح والفلفل الأبيض للحصول على قوام كريمي متجانس قبل الخبز في الفرن."
        ),
        base_language="ar-SA",
        target_languages=["ar-SA"],
        target_duration_seconds=30,
    )

    det = detect_source_language(topic=req.topic, source_content=req.source_content)
    assert det.is_mixed is True
    assert req.base_language == "ar-SA"
    assert len(req.language_warnings) == 1
    assert "Mixed-language" in req.language_warnings[0] or "canonical script" in req.language_warnings[0]

    mock_llm = MultilingualAwareMockLLM()
    workflow = create_script_workflow(llm_provider=mock_llm)
    state = workflow.invoke(VideoScriptState(request=req))
    assert state["workflow_status"] == "completed"
    assert state["final_script"].language == "ar-SA"


# ===========================================================================
# 4. French Source -> German Output
# ===========================================================================

def test_4_french_source_to_german_output():
    """Verify French source text is distinguished from English and generates German output."""
    french_topic = "Formation sur la sécurité informatique pour les employés"
    french_source = (
        "Dans cette formation, vous apprendrez comment vérifier les courriels suspects avec prudence. "
        "Ne cliquez pas sur les liens inconnus et signalez toujours chaque menace à votre équipe."
    )

    det = detect_source_language(topic=french_topic, source_content=french_source)
    assert det.detected_language == "fr"
    assert det.detected_locale == "fr-FR"
    assert not det.is_uncertain

    req = TrainingVideoRequest(
        topic=french_topic,
        source_content=french_source,
        base_language="de-DE",
        target_languages=["de-DE"],
        target_duration_seconds=30,
    )
    assert req.detected_source_language == "fr-FR"
    assert req.base_language == "de-DE"
    assert len(req.language_warnings) == 1
    assert "French" in req.language_warnings[0]
    assert "German" in req.language_warnings[0]

    mock_llm = MultilingualAwareMockLLM()
    workflow = create_script_workflow(llm_provider=mock_llm)
    state = workflow.invoke(VideoScriptState(request=req))
    assert state["workflow_status"] == "completed"
    assert state["final_script"].language == "de-DE"
    lang_ok, _ = verify_output_language(state["final_script"].scenes[0].narration, "de-DE")
    assert lang_ok is True


# ===========================================================================
# 5. Urdu Source -> English Output (and Urdu vs Arabic Disambiguation)
# ===========================================================================

def test_5_urdu_source_to_english_output():
    """Verify Urdu source content in Arabic script is detected as 'ur-PK' (not 'ar-SA') and generates English."""
    urdu_topic = "دفتر میں سائبر سیکیورٹی کی بنیادی تربیت"
    urdu_source = (
        "اس تربیتی کورس میں آپ سیکھیں گے کہ مشکوک ای میلز کی شناخت کیسے کی جاتی ہے اور اپنے کمپیوٹر کو "
        "حملوں سے بچانے کے لیے کن حفاظتی اقدامات پر عمل کرنا ضروری ہے۔"
    )

    det = detect_source_language(topic=urdu_topic, source_content=urdu_source)
    assert det.detected_language == "ur"
    assert det.detected_locale == "ur-PK"
    assert not det.is_uncertain

    req = TrainingVideoRequest(
        topic=urdu_topic,
        source_content=urdu_source,
        base_language="en-US",
        target_languages=["en-US"],
        target_duration_seconds=30,
    )
    assert req.detected_source_language == "ur-PK"
    assert req.base_language == "en-US"
    assert len(req.language_warnings) == 1
    assert "Urdu" in req.language_warnings[0]

    mock_llm = MultilingualAwareMockLLM()
    workflow = create_script_workflow(llm_provider=mock_llm)
    state = workflow.invoke(VideoScriptState(request=req))
    assert state["workflow_status"] == "completed"
    assert state["final_script"].language == "en-US"


# ===========================================================================
# 6. Bengali Source -> Arabic Output
# ===========================================================================

def test_6_bengali_source_to_arabic_output():
    """Verify Bengali source content ('bn-BD') with Arabic target ('ar-SA') succeeds."""
    bn_topic = "কর্পোরেট কর্মীদের জন্য কর্মক্ষেত্রে সাইবার নিরাপত্তা প্রশিক্ষণ"
    bn_source = (
        "আজকের প্রশিক্ষণে আমরা শিখব কীভাবে প্রতারণামূলক ফিশিং ইমেইল শনাক্ত করতে হয় এবং "
        "প্রেরকের আসল ঠিকানা যাচাই করে দ্রুত নিরাপত্তা দলকে জানাতে হয়।"
    )

    det = detect_source_language(topic=bn_topic, source_content=bn_source)
    assert det.detected_language == "bn"
    assert det.detected_locale == "bn-BD"

    req = TrainingVideoRequest(
        topic=bn_topic,
        source_content=bn_source,
        base_language="ar-SA",
        target_languages=["ar-SA"],
        target_duration_seconds=30,
    )
    assert req.detected_source_language == "bn-BD"
    assert req.base_language == "ar-SA"
    assert len(req.language_warnings) == 1
    assert "Bengali" in req.language_warnings[0]

    mock_llm = MultilingualAwareMockLLM()
    workflow = create_script_workflow(llm_provider=mock_llm)
    state = workflow.invoke(VideoScriptState(request=req))
    assert state["workflow_status"] == "completed"
    assert state["final_script"].language == "ar-SA"


# ===========================================================================
# 7. Empty Source Content with a Valid Topic
# ===========================================================================

def test_7_empty_source_content_with_valid_topic():
    """Verify empty source_content with a valid Arabic or English topic works cleanly."""
    req = TrainingVideoRequest(
        topic="طريقة عمل المكرونة بالبشاميل المصرية في المنزل خطوة بخطوة",
        source_content="",
        base_language="ar-SA",
        target_languages=["ar-SA", "en-US"],
        target_duration_seconds=30,
    )
    assert req.detected_source_language == "ar-SA"
    assert req.language_warnings == []

    mock_llm = MultilingualAwareMockLLM()
    workflow = create_script_workflow(llm_provider=mock_llm)
    state = workflow.invoke(VideoScriptState(request=req))
    assert state["workflow_status"] == "completed"


# ===========================================================================
# 8. Unsupported Locale & Missing Content Handling (HTTP 422 Preserved)
# ===========================================================================

def test_8_unsupported_locale_and_invalid_payload_raise_422(tmp_path, monkeypatch):
    """Verify HTTP 422 is still raised for unsupported locales and missing content."""
    # 1. Unsupported base_language prefix
    with pytest.raises(ValidationError) as exc_base:
        TrainingVideoRequest(
            topic="Valid Topic",
            base_language="xx-YY",
            target_languages=["en-US"],
        )
    assert "Unsupported locale" in str(exc_base.value)

    # 2. Unsupported target_languages entry
    with pytest.raises(ValidationError) as exc_target:
        TrainingVideoRequest(
            topic="Valid Topic",
            base_language="en-US",
            target_languages=["zz-ZZ"],
        )
    assert "Unsupported locale" in str(exc_target.value)

    # 3. Malformed locale format
    with pytest.raises(ValidationError):
        TrainingVideoRequest(
            topic="Valid Topic",
            base_language="invalid_locale_format_123",
        )

    # 4. FastAPI endpoint returns HTTP 422 on unsupported locale, and 201 on cross-language request
    from app.api.v1.projects import manifest_manager
    test_storage = tmp_path / "storage"
    test_storage.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "STORAGE_PATH", test_storage)
    monkeypatch.setattr(manifest_manager, "storage_base_dir", test_storage)

    app = create_app()
    with TestClient(app) as client:
        bad_res = client.post(
            "/api/v1/projects",
            json={
                "request": {
                    "topic": "Egyptian Macaroni Béchamel",
                    "base_language": "xx-YY",
                    "target_languages": ["ar-SA"],
                }
            },
        )
        assert bad_res.status_code == 422

        good_res = client.post(
            "/api/v1/projects",
            json={
                "request": {
                    "topic": "Egyptian Macaroni Béchamel",
                    "source_content": "Boil pasta, brown minced meat, prepare béchamel sauce with milk and flour, and bake.",
                    "base_language": "ar-SA",
                    "target_languages": ["ar-SA"],
                    "target_duration_seconds": 30,
                }
            },
        )
        assert good_res.status_code == 201
        body = good_res.json()
        assert body["source_request"]["base_language"] == "ar-SA"
        assert body["source_request"]["detected_source_language"] == "en-US"
        assert len(body["source_request"]["language_warnings"]) == 1


# ===========================================================================
# 9 & 10. Existing English-to-English and Arabic-to-Arabic Workflows
# ===========================================================================

def test_9_existing_english_to_english_workflow():
    """Verify standard English source -> English canonical & output has zero warnings."""
    req = TrainingVideoRequest(
        topic="Workplace Phishing Defense Essentials",
        source_content="Always verify the sender email address before clicking links or opening attachments in your inbox.",
        base_language="en-US",
        target_languages=["en-US"],
        target_duration_seconds=30,
    )
    assert req.detected_source_language == "en-US"
    assert req.language_warnings == []


def test_10_existing_arabic_to_arabic_workflow():
    """Verify standard Arabic source -> Arabic canonical & output has zero warnings."""
    req = TrainingVideoRequest(
        topic="أساسيات الحماية من التصيد الاحتيالي في بيئة العمل",
        source_content="يجب دائماً فحص النطاق الفعلي للمرسل قبل الضغط على أي رابط أو تنزيل أي مرفقات.",
        base_language="ar-SA",
        target_languages=["ar-SA"],
        target_duration_seconds=30,
    )
    assert req.detected_source_language == "ar-SA"
    assert req.language_warnings == []


# ===========================================================================
# 11. Localization Safety & Bounded Language Correction When Output Language Is Wrong
# ===========================================================================

def test_11_bounded_correction_and_localization_refuses_untranslated_mirroring():
    """
    Verify:
    A) If initial ScriptDraft narration is mistakenly in English when 'ar-SA' was requested,
       validate_script_draft flags SCRIPT_LANGUAGE_MISMATCH and revise_script repairs it to Arabic.
    B) If a FinalScript labeled 'ar-SA' ever contains English narration, LocalizationService.localize()
       detects the mismatch and executes LLM translation into 'ar-SA' instead of mirroring English as Arabic.
    """
    # Part A: Stage 1 bounded revision when LLM outputs English on Attempt 1 for ar-SA
    req = TrainingVideoRequest(
        topic="Egyptian Macaroni Béchamel",
        source_content="Boil pasta, make white roux with butter and flour, add milk, layer with meat, and bake.",
        base_language="ar-SA",
        target_languages=["ar-SA"],
        target_duration_seconds=30,
    )
    mock_llm = MultilingualAwareMockLLM(fail_first_language_attempt=True)
    workflow = create_script_workflow(llm_provider=mock_llm)
    state = workflow.invoke(VideoScriptState(request=req, max_revisions=1))

    assert state["workflow_status"] == "completed"
    assert state["revision_count"] == 1
    assert mock_llm.script_calls == 2
    final_script: FinalScript = state["final_script"]
    assert final_script.language == "ar-SA"
    lang_ok, _ = verify_output_language(final_script.scenes[0].narration, "ar-SA")
    assert lang_ok is True

    # Part B: Stage 2 safeguard if a FinalScript labeled 'ar-SA' actually has English narration
    mislabeled_source = FinalScript(
        title="Egyptian Macaroni Béchamel",
        language="ar-SA",  # Labeled ar-SA, but narration below is English!
        audience="Home Cooks",
        target_duration_seconds=30,
        total_estimated_duration_seconds=30,
        opening_hook="Let us make béchamel pasta.",
        closing_summary="Serve hot.",
        learning_objectives=[
            LearningObjective(id="LO1", description="Prepare béchamel sauce"),
        ],
        scenes=[
            SceneDraft(
                scene_id="scene_1",
                order=1,
                title="Preparation",
                purpose="Cook pasta",
                narration=ENGLISH_KABSA_NARRATION_30S,
                estimated_duration_seconds=30,
                visual_direction="Kitchen counter.",
                learning_objective_ids=["LO1"],
                scene_type="demonstration",
            )
        ],
    )

    loc_llm = MultilingualAwareMockLLM()
    loc_service = LocalizationService(llm_provider=loc_llm)
    loc_script, val, status = loc_service.localize(
        LocalizationRequest(source_script=mislabeled_source, target_locale="ar-SA")
    )

    # Must NOT skip LLM call! It must translate into genuine Arabic:
    assert loc_llm.localization_calls == 1
    assert status == "completed"
    assert val.is_valid is True
    assert loc_script.metadata.get("skipped_llm_call") is not True
    ar_ok, _ = verify_output_language(loc_script.scenes[0].narration, "ar-SA")
    assert ar_ok is True


# ===========================================================================
# 12. Uncertain Language Detection Preserves User Selection
# ===========================================================================

def test_12_uncertain_language_detection_preserves_explicit_selection():
    """Verify short or ambiguous source input marks detection as uncertain and preserves user base_language without false warnings."""
    det = detect_source_language(topic="Béchamel 101", source_content="300g")
    assert det.is_uncertain is True
    assert det.detected_locale is None

    req = TrainingVideoRequest(
        topic="Béchamel 101",
        source_content="300g",
        base_language="ar-SA",
        target_languages=["ar-SA"],
        target_duration_seconds=30,
    )
    # Preserves explicit ar-SA selection and emits no false mismatch warning
    assert req.base_language == "ar-SA"
    assert req.detected_source_language == "ar-SA"
    assert req.language_warnings == []

    # When base_language is 'auto' and detection is uncertain, falls back to 'en-US'
    req_auto = TrainingVideoRequest(
        topic="ISO 27001",
        source_content="v2.0",
        base_language="auto",
        target_languages=["ar-SA"],
        target_duration_seconds=30,
    )
    assert req_auto.base_language == "en-US"

