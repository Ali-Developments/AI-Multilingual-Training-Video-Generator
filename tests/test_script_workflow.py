"""Comprehensive test suite for Step 3 Video-Ready Script Generation Workflow.

Tests:
1. Exact WPM speech-rate calculation for scene duration.
2. Total script duration strictly equals the sum of scene durations.
3. LLM cannot fake duration values; Python normalizes duration deterministically from word count.
4. Too-short script fails duration validation.
5. Too-long script fails duration validation.
6. Target duration discrepancy triggers revision with explicit expansion guidance.
7. Missing opening hook is flagged as validation error.
8. Outro/recap as opening scene is flagged as validation error.
9. Malformed (whitespace-only) on_screen_text is flagged as error.
10. Valid None on_screen_text is accepted without error.
11. Duplicate scene IDs are detected.
12. Missing narration is detected.
13. Missing visual direction is detected.
14. Unknown learning objective IDs and uncovered required objectives are detected.
15. Graph compiles successfully.
16. Happy path execution with valid request: normalize -> analyze -> generate -> validate -> finalize.
17. Topic-only input succeeds.
18. Source_content-only input succeeds.
19. Missing both topic and source_content fails validation.
20. Target duration bounds validation (<15s or >3600s).
21. Valid script does NOT invoke revise_script.
22. Invalid initial script invokes revise_script exactly once when max_revisions = 1.
23. Revised valid script completes successfully.
24. Repeatedly invalid script stops after max_revisions and sets workflow_status = 'needs_review'.
25. Workflow uses MockLLMProvider for all LLM operations.
26. Workflow nodes never import or call groq SDK directly.
"""

from typing import Optional, List, Type, TypeVar
import pytest
from pydantic import BaseModel

from app.models.schemas import (
    TrainingVideoRequest,
    LearningObjective,
    ContentAnalysis,
    SceneDraft,
    ScriptDraft,
    FinalScript,
)
from app.services.llm.base import LLMProvider
from app.workflows.script_generation.validators import (
    validate_script_draft,
    estimate_narration_duration_seconds,
    normalize_script_durations,
    assess_learning_objective_coverage,
    get_scene_objective_map,
)
from app.workflows.script_generation.prompts import (
    build_script_revision_prompt,
    build_workflow_script_prompt,
)
from app.workflows.script_generation.nodes import ScriptWorkflowNodes
from app.workflows.script_generation.state import VideoScriptState
from app.workflows.script_generation.graph import create_script_workflow

T = TypeVar("T", bound=BaseModel)

# Realistic scene narrations: Scene 1 has 71 words (~30s at 140 WPM), Scene 2 has 68 words (~29s at 140 WPM); together ~139 words (~60s total)
SAMPLE_SCENE_1_NARRATION = (
    "Welcome to cybersecurity awareness training. Today we examine how deceptive phishing emails enter your inbox "
    "pretending to come from trusted company executives or service providers. The primary defense is scrutinizing "
    "the exact sender domain. Fraudulent senders frequently alter a single letter or add obscure suffixes to mimic "
    "legitimate addresses. Always hover your cursor over the sender name to reveal the actual email address before "
    "clicking any embedded hyperlinks or downloading attachments."
)

SAMPLE_SCENE_2_NARRATION = (
    "Once you identify a suspicious message, proper protocol requires prompt reporting rather than simple deletion. "
    "Never attempt to forward the threat directly to colleagues via normal messaging channels. Instead, utilize "
    "the official 'Report Phishing' button located in your corporate toolbar. This sends the email headers and "
    "security metadata directly to the security operations center for rapid quarantine. Your vigilance protects "
    "not only your machine, but the entire organization against intrusion."
)


class MockLLMProvider(LLMProvider):
    """Controllable in-memory LLMProvider for testing workflows without network calls."""

    def __init__(
        self,
        analysis_fixture: Optional[ContentAnalysis] = None,
        script_draft_fixture: Optional[ScriptDraft] = None,
        revised_script_fixture: Optional[ScriptDraft] = None,
        revision_fixtures: Optional[List[ScriptDraft]] = None,
        model_name_str: str = "mock-llm-v1"
    ):
        self._model_name = model_name_str
        self.analysis_fixture = analysis_fixture
        self.script_draft_fixture = script_draft_fixture
        self.revised_script_fixture = revised_script_fixture
        self.revision_fixtures = list(revision_fixtures) if revision_fixtures else []
        self.call_history = []
        self.generate_script_call_count = 0
        self.revise_script_call_count = 0

    @property
    def model_name(self) -> str:
        return self._model_name

    def generate_text(self, prompt: str, system_prompt: Optional[str] = None, temperature: float = 0.7, max_tokens: Optional[int] = None) -> str:
        self.call_history.append({"type": "text", "prompt": prompt})
        return "Mocked text response"

    def generate_structured(self, prompt: str, schema: Type[T], system_prompt: Optional[str] = None, temperature: float = 0.2) -> T:
        self.call_history.append({"type": "structured", "schema": schema.__name__, "prompt": prompt})

        if schema == ContentAnalysis:
            if self.analysis_fixture:
                return self.analysis_fixture
            return ContentAnalysis(
                topic_summary="Phishing defense fundamentals",
                key_concepts=["Email headers", "Urgency indicators", "Reporting process"],
                learning_objectives=[
                    LearningObjective(id="LO1", description="Identify suspicious email domains"),
                    LearningObjective(id="LO2", description="Follow organizational reporting protocol")
                ],
                audience_notes="General corporate employees",
                recommended_scene_count=2,
                recommended_structure=["Introduction", "Practical Example", "Outro"],
                important_terms=["Spear phishing", "Spoofing"],
                factual_constraints=["Never click unknown verification links"]
            )

        if schema == ScriptDraft:
            self.generate_script_call_count += 1
            # If revision fixture provided and this is a subsequent revision call
            if self.generate_script_call_count > 1:
                self.revise_script_call_count += 1
                if self.revision_fixtures:
                    idx = min(self.revise_script_call_count - 1, len(self.revision_fixtures) - 1)
                    return self.revision_fixtures[idx]
                if self.revised_script_fixture:
                    return self.revised_script_fixture

            if self.script_draft_fixture:
                return self.script_draft_fixture

            # Default mathematically valid script (~139 words total ~ 60s at 140 WPM)
            return ScriptDraft(
                title="Phishing Defense 101",
                language="en-US",
                audience="Corporate Employees",
                learning_objectives=[
                    LearningObjective(id="LO1", description="Identify suspicious email domains"),
                    LearningObjective(id="LO2", description="Follow organizational reporting protocol")
                ],
                opening_hook="Can you spot a sophisticated phishing attack before it compromises your credentials?",
                closing_summary="Always inspect the sender address and report suspicious messages immediately.",
                scenes=[
                    SceneDraft(
                        scene_id="scene_1",
                        order=1,
                        title="Spotting Spoofed Domains",
                        purpose="Introduce domain inspection",
                        scene_type="presenter",
                        narration=SAMPLE_SCENE_1_NARRATION,
                        visual_direction="Close-up of an email client showing a suspicious misspelled sender address.",
                        on_screen_text="Check the Sender Domain",
                        learning_objective_ids=["LO1"],
                        estimated_duration_seconds=30
                    ),
                    SceneDraft(
                        scene_id="scene_2",
                        order=2,
                        title="Incident Reporting",
                        purpose="Explain reporting protocol",
                        scene_type="explanation",
                        narration=SAMPLE_SCENE_2_NARRATION,
                        visual_direction="Animated illustration of clicking the 'Report Phishing' button.",
                        on_screen_text="Report Immediately",
                        learning_objective_ids=["LO2"],
                        estimated_duration_seconds=30
                    )
                ],
                total_estimated_duration_seconds=60
            )

        raise ValueError(f"Unhandled mock schema: {schema}")


# ---------------------------------------------------------------------------
# Duration & Validation Unit Tests
# ---------------------------------------------------------------------------

def test_narration_duration_estimator_exact_wpm():
    """Verify pre-TTS narration duration calculation based on word count and WPM."""
    # 71 words at 140 WPM = round((71 / 140) * 60) = 30 seconds
    assert estimate_narration_duration_seconds(SAMPLE_SCENE_1_NARRATION, words_per_minute=140) == 30

    # 35 words at 140 WPM = 15 seconds
    short_text = "This is a clean sample narration containing exactly fourteen words for our unit test."
    # 14 words at 140 WPM = 6 seconds
    assert estimate_narration_duration_seconds(short_text, words_per_minute=140) == 6

    # Empty text returns 0 seconds
    assert estimate_narration_duration_seconds("") == 0


def test_total_duration_strictly_equals_sum_of_scene_durations():
    """Verify total_estimated_duration_seconds is strictly derived from sum of scenes."""
    script = ScriptDraft(
        title="Duration Consistency",
        audience="Learners",
        opening_hook="Hook statement",
        scenes=[
            SceneDraft(scene_id="s1", order=1, title="S1", narration=SAMPLE_SCENE_1_NARRATION, visual_direction="V1"),
            SceneDraft(scene_id="s2", order=2, title="S2", narration=SAMPLE_SCENE_2_NARRATION, visual_direction="V2"),
        ]
    )
    normalize_script_durations(script, words_per_minute=140)
    assert script.scenes[0].estimated_duration_seconds == 30
    assert script.scenes[1].estimated_duration_seconds == 30
    assert script.total_estimated_duration_seconds == 60
    assert script.total_estimated_duration_seconds == sum(s.estimated_duration_seconds for s in script.scenes)


def test_llm_cannot_fake_duration_values():
    """Verify that if LLM returns arbitrary/hallucinated durations, Python normalizes them."""
    # LLM returns 14 words (~6s) but claims estimated_duration_seconds = 999
    short_narration = "This is a clean sample narration containing exactly fourteen words for our unit test."
    script = ScriptDraft(
        title="Fake Duration Test",
        audience="Learners",
        opening_hook="Hook statement",
        scenes=[
            SceneDraft(
                scene_id="s1",
                order=1,
                title="S1",
                narration=short_narration,
                visual_direction="V1",
                estimated_duration_seconds=999
            )
        ]
    )
    # Run deterministic normalization
    normalize_script_durations(script, words_per_minute=140)
    # The hallucinated 999 is replaced by the deterministic 6 seconds
    assert script.scenes[0].estimated_duration_seconds == 6
    assert script.total_estimated_duration_seconds == 6


def test_too_short_script_fails_duration_validation():
    """Verify a very short narration for a 60s target video fails duration tolerance."""
    script = ScriptDraft(
        title="Short Script",
        audience="Learners",
        opening_hook="Hook",
        scenes=[
            SceneDraft(
                scene_id="s1",
                order=1,
                title="S1",
                narration="Only six words in this entire scene.",
                visual_direction="V1"
            )
        ]
    )
    # 6 words = ~3 seconds, target 60 seconds (deviation > 90%)
    result = validate_script_draft(script, target_duration_seconds=60, tolerance_percent=20)
    assert not result.is_valid
    assert any(i.code == "DURATION_OUT_OF_TOLERANCE" for i in result.issues)
    assert result.duration_difference_seconds < -40


def test_too_long_script_fails_duration_validation():
    """Verify excessively long narration fails duration validation."""
    long_narration = " ".join(["repetitive speech content"] * 100) # 300 words = ~129s
    script = ScriptDraft(
        title="Long Script",
        audience="Learners",
        opening_hook="Hook",
        scenes=[
            SceneDraft(scene_id="s1", order=1, title="S1", narration=long_narration, visual_direction="V1")
        ]
    )
    result = validate_script_draft(script, target_duration_seconds=30, tolerance_percent=20)
    assert not result.is_valid
    assert any(i.code == "DURATION_OUT_OF_TOLERANCE" for i in result.issues)
    assert result.duration_difference_seconds > 50


def test_validator_detects_missing_opening_hook():
    """Verify validation flags missing opening hook statement."""
    script = ScriptDraft(
        title="Missing Hook Test",
        audience="Staff",
        opening_hook="",
        scenes=[
            SceneDraft(scene_id="scene_1", order=1, title="S1", narration=SAMPLE_SCENE_1_NARRATION, visual_direction="V1", estimated_duration_seconds=30)
        ]
    )
    result = validate_script_draft(script, target_duration_seconds=30)
    assert not result.is_valid
    assert any(i.code == "MISSING_OPENING_HOOK" for i in result.issues)


def test_validator_detects_invalid_opening_scene_type():
    """Verify opening scene cannot be of type outro or recap."""
    script = ScriptDraft(
        title="Bad Opening Scene",
        audience="Staff",
        opening_hook="Valid hook",
        scenes=[
            SceneDraft(scene_id="scene_1", order=1, title="S1", scene_type="outro", narration=SAMPLE_SCENE_1_NARRATION, visual_direction="V1", estimated_duration_seconds=30)
        ]
    )
    result = validate_script_draft(script, target_duration_seconds=30)
    assert not result.is_valid
    assert any(i.code == "INVALID_OPENING_SCENE" for i in result.issues)


def test_validator_detects_malformed_on_screen_text():
    """Verify whitespace-only on_screen_text is flagged as malformed."""
    script = ScriptDraft(
        title="Whitespace Text Test",
        audience="Staff",
        opening_hook="Valid hook",
        scenes=[
            SceneDraft(
                scene_id="scene_1",
                order=1,
                title="S1",
                narration=SAMPLE_SCENE_1_NARRATION,
                visual_direction="V1",
                on_screen_text="    ",  # Malformed whitespace
                estimated_duration_seconds=30
            )
        ]
    )
    result = validate_script_draft(script, target_duration_seconds=30)
    assert not result.is_valid
    assert any(i.code == "MALFORMED_ON_SCREEN_TEXT" for i in result.issues)


def test_validator_allows_valid_none_on_screen_text():
    """Verify intentionally omitted (None) on_screen_text passes validation without error."""
    script = ScriptDraft(
        title="None Text Test",
        audience="Staff",
        opening_hook="Valid hook",
        scenes=[
            SceneDraft(
                scene_id="scene_1",
                order=1,
                title="S1",
                narration=SAMPLE_SCENE_1_NARRATION,
                visual_direction="V1",
                on_screen_text=None,  # Intentionally no text overlay
                estimated_duration_seconds=30
            )
        ]
    )
    result = validate_script_draft(script, target_duration_seconds=30)
    assert not any(i.code == "MALFORMED_ON_SCREEN_TEXT" for i in result.issues)


def test_validator_detects_duplicate_scene_ids():
    """Verify validation detects duplicate scene identifiers."""
    script = ScriptDraft(
        title="Duplicate Test",
        audience="Engineers",
        opening_hook="Hook",
        scenes=[
            SceneDraft(scene_id="scene_1", order=1, title="Scene 1", narration=SAMPLE_SCENE_1_NARRATION, visual_direction="Visual 1"),
            SceneDraft(scene_id="scene_1", order=2, title="Scene 2", narration=SAMPLE_SCENE_2_NARRATION, visual_direction="Visual 2"),
        ]
    )
    result = validate_script_draft(script, target_duration_seconds=60)
    assert not result.is_valid
    assert any(i.code == "DUPLICATE_SCENE_ID" for i in result.issues)


def test_validator_detects_missing_narration_and_visual_direction():
    """Verify validation flags empty narration or missing visual guidance."""
    script = ScriptDraft(
        title="Empty Fields Test",
        audience="Engineers",
        opening_hook="Hook",
        scenes=[
            SceneDraft(scene_id="scene_1", order=1, title="S1", narration="", visual_direction="Graphic"),
            SceneDraft(scene_id="scene_2", order=2, title="S2", narration=SAMPLE_SCENE_2_NARRATION, visual_direction=""),
        ]
    )
    result = validate_script_draft(script, target_duration_seconds=60)
    assert not result.is_valid
    codes = {i.code for i in result.issues}
    assert "MISSING_NARRATION" in codes
    assert "MISSING_VISUAL_DIRECTION" in codes


def test_validator_detects_invalid_and_uncovered_learning_objectives():
    """Verify unknown objective IDs and uncovered required objectives are flagged."""
    analysis = ContentAnalysis(
        topic_summary="Test",
        audience_notes="Test",
        recommended_scene_count=1,
        learning_objectives=[
            LearningObjective(id="LO1", description="Objective 1"),
            LearningObjective(id="LO2", description="Objective 2"),
        ]
    )
    script = ScriptDraft(
        title="LO Test",
        audience="Learners",
        opening_hook="Hook",
        scenes=[
            SceneDraft(
                scene_id="scene_1",
                order=1,
                title="S1",
                narration=SAMPLE_SCENE_1_NARRATION,
                visual_direction="Valid visual",
                learning_objective_ids=["LO1", "LO99"]
            )
        ]
    )
    result = validate_script_draft(script, target_duration_seconds=30, analysis=analysis)
    assert not result.is_valid
    codes = {i.code for i in result.issues}
    assert "UNKNOWN_OBJECTIVE_ID" in codes
    assert "UNCOVERED_LEARNING_OBJECTIVE" in codes


# ---------------------------------------------------------------------------
# LangGraph Workflow Behavior Tests
# ---------------------------------------------------------------------------

def test_workflow_compiles_successfully():
    """Verify LangGraph StateGraph compiles without errors."""
    mock_llm = MockLLMProvider()
    app = create_script_workflow(llm_provider=mock_llm)
    assert app is not None


def test_workflow_valid_script_does_not_invoke_revision():
    """Verify a valid initial script runs straight to finalize_script and does NOT invoke revise_script."""
    mock_llm = MockLLMProvider()
    app = create_script_workflow(llm_provider=mock_llm)

    request = TrainingVideoRequest(
        topic="Phishing Essentials",
        audience="Corporate Staff",
        base_language="en-US",
        target_duration_seconds=60
    )

    initial_state = VideoScriptState(request=request)
    final_state = app.invoke(initial_state)

    assert final_state["workflow_status"] == "completed"
    assert final_state["revision_count"] == 0
    assert mock_llm.revise_script_call_count == 0
    assert final_state["final_script"] is not None
    assert isinstance(final_state["final_script"], FinalScript)
    assert final_state["final_script"].total_estimated_duration_seconds == 60


def test_workflow_invalid_initial_script_invokes_revision_exactly_once():
    """Verify that an invalid initial draft triggers revise_script exactly once when max_revisions = 1."""
    defective_first_draft = ScriptDraft(
        title="Defective Draft",
        audience="Staff",
        opening_hook="Hook",
        learning_objectives=[
            LearningObjective(id="LO1", description="Objective 1"),
            LearningObjective(id="LO2", description="Objective 2"),
        ],
        scenes=[
            SceneDraft(scene_id="scene_1", order=1, title="S1", narration="", visual_direction="Visual", learning_objective_ids=["LO1"]),
            SceneDraft(scene_id="scene_2", order=2, title="S2", narration=SAMPLE_SCENE_2_NARRATION, visual_direction="Visual", learning_objective_ids=["LO2"]),
        ]
    )

    repaired_draft = ScriptDraft(
        title="Repaired Draft",
        audience="Staff",
        opening_hook="Hook",
        learning_objectives=[
            LearningObjective(id="LO1", description="Objective 1"),
            LearningObjective(id="LO2", description="Objective 2"),
        ],
        scenes=[
            SceneDraft(scene_id="scene_1", order=1, title="S1", narration=SAMPLE_SCENE_1_NARRATION, visual_direction="Visual", learning_objective_ids=["LO1"]),
            SceneDraft(scene_id="scene_2", order=2, title="S2", narration=SAMPLE_SCENE_2_NARRATION, visual_direction="Visual", learning_objective_ids=["LO2"]),
        ]
    )

    mock_llm = MockLLMProvider(
        script_draft_fixture=defective_first_draft,
        revised_script_fixture=repaired_draft
    )
    app = create_script_workflow(llm_provider=mock_llm)

    req = TrainingVideoRequest(topic="Repair Test", target_duration_seconds=60)
    final_state = app.invoke(VideoScriptState(request=req, max_revisions=1))

    assert final_state["workflow_status"] == "completed"
    assert final_state["revision_count"] == 1
    assert mock_llm.revise_script_call_count == 1
    assert final_state["final_script"].title == "Repaired Draft"


def test_workflow_repeatedly_invalid_script_stops_after_max_revisions():
    """Verify repeatedly invalid script stops after max_revisions and sets needs_review."""
    always_defective_draft = ScriptDraft(
        title="Permanently Broken Draft",
        audience="Staff",
        opening_hook="Hook",
        scenes=[
            SceneDraft(scene_id="scene_1", order=1, title="S1", narration="", visual_direction="Visual")
        ]
    )

    mock_llm = MockLLMProvider(
        script_draft_fixture=always_defective_draft,
        revised_script_fixture=always_defective_draft
    )
    app = create_script_workflow(llm_provider=mock_llm)

    req = TrainingVideoRequest(topic="Broken Test", target_duration_seconds=60)
    final_state = app.invoke(VideoScriptState(request=req, max_revisions=1))

    assert final_state["workflow_status"] == "needs_review"
    assert final_state["revision_count"] == 1
    assert final_state.get("final_script") is None
    assert final_state["validation"].is_valid is False


def test_workflow_topic_only_input():
    """Verify topic-only request normalizes and runs cleanly."""
    mock_llm = MockLLMProvider()
    app = create_script_workflow(llm_provider=mock_llm)

    request = TrainingVideoRequest(topic="Fire Safety Protocol", target_duration_seconds=60)
    final_state = app.invoke(VideoScriptState(request=request))
    assert final_state["workflow_status"] == "completed"
    assert final_state["request"].topic == "Fire Safety Protocol"
    assert final_state["request"].source_content is None


def test_workflow_source_content_only_input():
    """Verify source_content-only request normalizes and runs cleanly."""
    mock_llm = MockLLMProvider()
    app = create_script_workflow(llm_provider=mock_llm)

    request = TrainingVideoRequest(source_content="1. Evacuate building\n2. Call 911", target_duration_seconds=60)
    final_state = app.invoke(VideoScriptState(request=request))
    assert final_state["workflow_status"] == "completed"
    assert final_state["request"].source_content == "1. Evacuate building\n2. Call 911"
    assert final_state["request"].topic is None


def test_workflow_missing_both_topic_and_source_content():
    """Verify request validation rejects missing both topic and source_content."""
    with pytest.raises(ValueError, match="At least one of 'topic' or 'source_content'"):
        TrainingVideoRequest(topic="", source_content=None)


def test_workflow_duration_bounds_rejected():
    """Verify duration below 15s or above 3600s is rejected by normalize_input."""
    mock_llm = MockLLMProvider()
    app = create_script_workflow(llm_provider=mock_llm)

    bad_req = TrainingVideoRequest.model_construct(
        topic="Fast Video",
        target_duration_seconds=5
    )
    final_state = app.invoke(VideoScriptState(request=bad_req))
    assert final_state["workflow_status"] == "failed"
    assert any("Invalid target_duration_seconds" in err for err in final_state["errors"])


def test_workflow_uses_mock_llm_provider_for_all_llm_operations():
    """Verify workflow executes entirely against injected MockLLMProvider with recorded call history."""
    mock_llm = MockLLMProvider()
    app = create_script_workflow(llm_provider=mock_llm)

    request = TrainingVideoRequest(topic="Mock Verification", target_duration_seconds=60)
    app.invoke(VideoScriptState(request=request))

    # Verify structured calls for ContentAnalysis and ScriptDraft were logged
    schemas_called = [call["schema"] for call in mock_llm.call_history if call["type"] == "structured"]
    assert "ContentAnalysis" in schemas_called
    assert "ScriptDraft" in schemas_called


def test_workflow_nodes_never_call_groq_directly():
    """Verify workflow nodes use only the LLMProvider abstraction and do not import groq SDK."""
    import inspect
    from app.workflows.script_generation import nodes

    nodes_source = inspect.getsource(nodes)
    assert "import groq" not in nodes_source
    assert "from groq" not in nodes_source
    assert "Groq(" not in nodes_source


# ---------------------------------------------------------------------------
# Learning Objective Coverage & Targeted Revision Regression Tests
# ---------------------------------------------------------------------------

SAMPLE_LO1_SHORT_NARRATION = (
    "Examine the sender address with extreme care whenever receiving an email with unexpected attachments. "
    "Deceptive characters, spoofed subdomains, and misplaced letters often indicate an unauthorized external "
    "attempt to compromise internal enterprise authentication systems."
)  # 35 words ~ 15s

SAMPLE_LO2_SHORT_NARRATION = (
    "When you detect a suspicious message, immediately click the organizational report button in your email client. "
    "Never forward the email directly to your coworkers, as doing so spreads the active malicious payload "
    "across company systems."
)  # 35 words ~ 15s

SAMPLE_LO3_SHORT_NARRATION = (
    "To understand why spoofed messages reach inboxes, security teams inspect SPF, DKIM, and DMARC verification headers. "
    "These cryptographic protocols confirm whether the originating server had authorized rights to transmit "
    "messages for that company domain."
)  # 35 words ~ 15s

SAMPLE_LO4_SHORT_NARRATION = (
    "Finally, evaluate the remediation outcome after reporting. The security operations team analyzes telemetry, "
    "quarantines matched threats company-wide, and updates mail filtering rules to permanently prevent "
    "identical phishing vectors from reaching any employee."
)  # 35 words ~ 15s


def _create_four_objective_analysis() -> ContentAnalysis:
    """Helper creating a canonical ContentAnalysis fixture with four distinct learning objectives."""
    return ContentAnalysis(
        topic_summary="Comprehensive Phishing Defense and Verification Protocol",
        key_concepts=["Domain inspection", "Incident reporting", "Header analysis", "Quarantine evaluation"],
        learning_objectives=[
            LearningObjective(id="LO1", description="Identify deceptive phishing indicators in email domains"),
            LearningObjective(id="LO2", description="Apply organizational incident reporting protocols"),
            LearningObjective(id="LO3", description="Explain technical headers and SPF verification"),
            LearningObjective(id="LO4", description="Evaluate post-incident quarantine outcomes"),
        ],
        audience_notes="All enterprise staff members",
        recommended_scene_count=4,
        recommended_structure=["Intro", "Detection", "Reporting", "Verification", "Resolution", "Outro"],
        important_terms=["SPF", "DKIM", "DMARC", "Spoofing"],
        factual_constraints=["Always report via official toolbar"]
    )


def test_four_learning_objectives_missing_lo3_and_lo4_detected():
    """Verify that an initial script covering only LO1 and LO2 triggers UNCOVERED_LEARNING_OBJECTIVE for LO3 and LO4."""
    analysis = _create_four_objective_analysis()

    # Draft covering only LO1 and LO2
    script = ScriptDraft(
        title="Phishing Fundamentals",
        audience="Enterprise Staff",
        opening_hook="Can you reliably identify and report modern email threats?",
        scenes=[
            SceneDraft(
                scene_id="scene_1",
                order=1,
                title="Domain Inspection",
                purpose="Teach domain inspection",
                scene_type="presenter",
                narration=SAMPLE_SCENE_1_NARRATION,  # 71 words ~ 30s
                visual_direction="Presenter reviewing spoofed email header.",
                on_screen_text="Inspect the Domain",
                learning_objective_ids=["LO1"],
                estimated_duration_seconds=30
            ),
            SceneDraft(
                scene_id="scene_2",
                order=2,
                title="Incident Reporting",
                purpose="Teach reporting protocol",
                scene_type="explanation",
                narration=SAMPLE_SCENE_2_NARRATION,  # 68 words ~ 29s
                visual_direction="Screen recording of clicking Report button.",
                on_screen_text="Report Immediately",
                learning_objective_ids=["LO2"],
                estimated_duration_seconds=30
            ),
        ],
        total_estimated_duration_seconds=60
    )

    result = validate_script_draft(script, target_duration_seconds=60, analysis=analysis)

    assert not result.is_valid
    uncovered_issues = [i for i in result.issues if i.code == "UNCOVERED_LEARNING_OBJECTIVE"]
    assert len(uncovered_issues) == 2

    uncovered_messages = [i.message for i in uncovered_issues]
    assert any("LO3" in msg for msg in uncovered_messages)
    assert any("LO4" in msg for msg in uncovered_messages)
    assert not any("LO1" in msg for msg in uncovered_messages)
    assert not any("LO2" in msg for msg in uncovered_messages)

    # Deterministic coverage report verification
    rep = result.coverage_report
    assert rep is not None
    assert rep["total_objectives"] == 4
    assert rep["covered_objectives"] == 2
    uncovered_entries = rep["uncovered_objectives"]
    assert len(uncovered_entries) == 2
    assert {u["id"] for u in uncovered_entries} == {"LO3", "LO4"}
    assert all(u["covered_scene_ids"] == [] for u in uncovered_entries)


def test_revision_prompt_contains_exact_missing_ids_and_descriptions():
    """Verify revision prompt includes exact missing objective IDs, full descriptions, and existing scene breakdown."""
    analysis = _create_four_objective_analysis()
    req = TrainingVideoRequest(topic="Phishing Defense", target_duration_seconds=60)

    # Draft covering only LO1 and LO2
    script = ScriptDraft(
        title="Phishing Fundamentals",
        audience="Enterprise Staff",
        opening_hook="Can you reliably identify and report modern email threats?",
        scenes=[
            SceneDraft(
                scene_id="scene_1",
                order=1,
                title="Domain Inspection",
                purpose="Teach domain inspection",
                scene_type="presenter",
                narration=SAMPLE_SCENE_1_NARRATION,
                visual_direction="Presenter reviewing spoofed email header.",
                learning_objective_ids=["LO1"],
                estimated_duration_seconds=30
            ),
            SceneDraft(
                scene_id="scene_2",
                order=2,
                title="Incident Reporting",
                purpose="Teach reporting protocol",
                scene_type="explanation",
                narration=SAMPLE_SCENE_2_NARRATION,
                visual_direction="Screen recording of clicking Report button.",
                learning_objective_ids=["LO2"],
                estimated_duration_seconds=30
            ),
        ]
    )

    result = validate_script_draft(script, target_duration_seconds=60, analysis=analysis)
    prompt = build_script_revision_prompt(req, analysis, script, result)

    # 1. Exact missing IDs
    assert "LO3" in prompt
    assert "LO4" in prompt

    # 2. Exact full descriptions
    assert "Explain technical headers and SPF verification" in prompt
    assert "Evaluate post-incident quarantine outcomes" in prompt

    # 3. Existing scene breakdown and assigned objectives
    assert "scene_1" in prompt
    assert "Domain Inspection" in prompt
    assert "scene_2" in prompt
    assert "Incident Reporting" in prompt

    # 4. Actionable remediation instruction
    assert "TARGETED LEARNING OBJECTIVE REMEDIATION" in prompt
    assert "Do NOT simply attach missing objective IDs to arbitrary scenes" in prompt


def test_successful_revision_covering_all_four_objectives():
    """Verify that a defective initial draft missing LO3 & LO4 successfully completes after targeted revision."""
    analysis = _create_four_objective_analysis()

    # Initial draft missing LO3 and LO4
    initial_draft = ScriptDraft(
        title="Phishing Fundamentals (Draft 1)",
        audience="Enterprise Staff",
        opening_hook="Can you reliably identify and report modern email threats?",
        learning_objectives=analysis.learning_objectives,
        scenes=[
            SceneDraft(
                scene_id="scene_1",
                order=1,
                title="Domain Inspection",
                purpose="Teach domain inspection",
                scene_type="presenter",
                narration=SAMPLE_SCENE_1_NARRATION,
                visual_direction="Visual 1",
                learning_objective_ids=["LO1"],
                estimated_duration_seconds=30
            ),
            SceneDraft(
                scene_id="scene_2",
                order=2,
                title="Incident Reporting",
                purpose="Teach reporting protocol",
                scene_type="explanation",
                narration=SAMPLE_SCENE_2_NARRATION,
                visual_direction="Visual 2",
                learning_objective_ids=["LO2"],
                estimated_duration_seconds=30
            ),
        ],
        total_estimated_duration_seconds=60
    )

    # Revised draft covering all four objectives (4 scenes * ~15s = ~60s)
    revised_draft = ScriptDraft(
        title="Phishing Fundamentals (Revised)",
        audience="Enterprise Staff",
        opening_hook="Can you reliably identify, report, and verify modern email threats?",
        closing_summary="Vigilance and understanding technical verification protects our entire organization.",
        learning_objectives=analysis.learning_objectives,
        scenes=[
            SceneDraft(
                scene_id="scene_1",
                order=1,
                title="Spotting Indicators",
                purpose="Domain inspection",
                scene_type="presenter",
                narration=SAMPLE_LO1_SHORT_NARRATION,
                visual_direction="Close-up of spoofed header.",
                on_screen_text="Check Sender Domain",
                learning_objective_ids=["LO1"],
                estimated_duration_seconds=15
            ),
            SceneDraft(
                scene_id="scene_2",
                order=2,
                title="Reporting Protocol",
                purpose="Reporting instruction",
                scene_type="explanation",
                narration=SAMPLE_LO2_SHORT_NARRATION,
                visual_direction="Toolbar report button highlight.",
                on_screen_text="Report Threat Promptly",
                learning_objective_ids=["LO2"],
                estimated_duration_seconds=15
            ),
            SceneDraft(
                scene_id="scene_3",
                order=3,
                title="Technical Headers",
                purpose="Header and SPF verification",
                scene_type="visual_demo",
                narration=SAMPLE_LO3_SHORT_NARRATION,
                visual_direction="Diagram of SPF and DKIM authentication.",
                on_screen_text="SPF / DKIM Verification",
                learning_objective_ids=["LO3"],
                estimated_duration_seconds=15
            ),
            SceneDraft(
                scene_id="scene_4",
                order=4,
                title="Resolution & Quarantine",
                purpose="Quarantine outcome evaluation",
                scene_type="outro",
                narration=SAMPLE_LO4_SHORT_NARRATION,
                visual_direction="SOC dashboard showing quarantine and rule updates.",
                on_screen_text="Quarantine & Protection",
                learning_objective_ids=["LO4"],
                estimated_duration_seconds=15
            ),
        ],
        total_estimated_duration_seconds=60
    )

    mock_llm = MockLLMProvider(
        analysis_fixture=analysis,
        script_draft_fixture=initial_draft,
        revised_script_fixture=revised_draft
    )
    app = create_script_workflow(llm_provider=mock_llm)

    req = TrainingVideoRequest(topic="Phishing Defense", target_duration_seconds=60)
    final_state = app.invoke(VideoScriptState(request=req, max_revisions=2))

    assert final_state["workflow_status"] == "completed"
    assert final_state["revision_count"] == 1
    assert mock_llm.revise_script_call_count == 1
    assert final_state["final_script"] is not None
    assert final_state["final_script"].title == "Phishing Fundamentals (Revised)"
    assert len(final_state["final_script"].scenes) == 4

    # All 4 objectives represented in final script
    covered_ids = set()
    for s in final_state["final_script"].scenes:
        covered_ids.update(s.learning_objective_ids)
    assert covered_ids == {"LO1", "LO2", "LO3", "LO4"}


def test_failed_revision_remains_in_needs_review():
    """Verify that when a revision still leaves objectives uncovered and revision limit is reached, it marks needs_review."""
    analysis = _create_four_objective_analysis()

    # Initial draft missing LO3 and LO4
    initial_draft = ScriptDraft(
        title="Initial Draft",
        audience="Staff",
        opening_hook="Hook statement",
        scenes=[
            SceneDraft(
                scene_id="scene_1",
                order=1,
                title="S1",
                narration=SAMPLE_SCENE_1_NARRATION,
                visual_direction="V1",
                learning_objective_ids=["LO1"],
                estimated_duration_seconds=30
            ),
            SceneDraft(
                scene_id="scene_2",
                order=2,
                title="S2",
                narration=SAMPLE_SCENE_2_NARRATION,
                visual_direction="V2",
                learning_objective_ids=["LO2"],
                estimated_duration_seconds=30
            ),
        ]
    )

    # Incomplete revision: only fixes LO3, still forgets LO4
    unresolved_revision = ScriptDraft(
        title="Incomplete Revision",
        audience="Staff",
        opening_hook="Hook statement",
        scenes=[
            SceneDraft(
                scene_id="scene_1",
                order=1,
                title="S1",
                narration=SAMPLE_SCENE_1_NARRATION,
                visual_direction="V1",
                learning_objective_ids=["LO1", "LO2"],
                estimated_duration_seconds=30
            ),
            SceneDraft(
                scene_id="scene_2",
                order=2,
                title="S2",
                narration=SAMPLE_SCENE_2_NARRATION,
                visual_direction="V2",
                learning_objective_ids=["LO3"],  # LO4 is still missing!
                estimated_duration_seconds=30
            ),
        ]
    )

    mock_llm = MockLLMProvider(
        analysis_fixture=analysis,
        script_draft_fixture=initial_draft,
        revised_script_fixture=unresolved_revision
    )
    app = create_script_workflow(llm_provider=mock_llm)

    req = TrainingVideoRequest(topic="Unresolved Revision Test", target_duration_seconds=60)
    final_state = app.invoke(VideoScriptState(request=req, max_revisions=1))

    assert final_state["workflow_status"] == "needs_review"
    assert final_state["revision_count"] == 1
    assert final_state.get("final_script") is None
    assert any("UNCOVERED_LEARNING_OBJECTIVE" in err for err in final_state["errors"])
    assert any("LO4" in err for err in final_state["errors"])


def test_multiple_objectives_legitimately_assigned_to_one_scene():
    """Verify that multiple objectives assigned to a single scene pass deterministic validation."""
    analysis = _create_four_objective_analysis()

    # 2 scenes covering [LO1, LO2] and [LO3, LO4]
    script = ScriptDraft(
        title="Multi-Objective Script",
        audience="Enterprise Staff",
        opening_hook="Welcome to integrated threat identification and response.",
        closing_summary="Comprehensive detection and verification ensures enterprise security.",
        scenes=[
            SceneDraft(
                scene_id="scene_1",
                order=1,
                title="Detection and Reporting",
                purpose="Cover domain inspection and immediate incident reporting",
                scene_type="presenter",
                narration=SAMPLE_SCENE_1_NARRATION,  # 71 words ~ 30s
                visual_direction="Split screen of domain inspection and report button.",
                learning_objective_ids=["LO1", "LO2"],
                estimated_duration_seconds=30
            ),
            SceneDraft(
                scene_id="scene_2",
                order=2,
                title="Verification and Resolution",
                purpose="Cover cryptographic headers and incident resolution",
                scene_type="explanation",
                narration=SAMPLE_SCENE_2_NARRATION,  # 68 words ~ 29s
                visual_direction="Diagram of SPF validation and quarantine log.",
                learning_objective_ids=["LO3", "LO4"],
                estimated_duration_seconds=30
            ),
        ],
        total_estimated_duration_seconds=60
    )

    result = validate_script_draft(script, target_duration_seconds=60, analysis=analysis)

    assert result.is_valid
    assert not any(i.code == "UNCOVERED_LEARNING_OBJECTIVE" for i in result.issues)
    assert not any(i.code == "UNKNOWN_OBJECTIVE_ID" for i in result.issues)
    assert result.coverage_report["total_objectives"] == 4
    assert result.coverage_report["covered_objectives"] == 4
    assert result.coverage_report["uncovered_objectives"] == []


def test_unknown_objective_ids_still_rejected():
    """Verify that referencing unknown or hallucinated objective IDs fails validation."""
    analysis = _create_four_objective_analysis()

    script = ScriptDraft(
        title="Unknown Objectives Test",
        audience="Staff",
        opening_hook="Hook statement",
        scenes=[
            SceneDraft(
                scene_id="scene_1",
                order=1,
                title="S1",
                narration=SAMPLE_SCENE_1_NARRATION,
                visual_direction="V1",
                learning_objective_ids=["LO1", "LO99", "HALLUCINATED_ID"],
                estimated_duration_seconds=30
            ),
            SceneDraft(
                scene_id="scene_2",
                order=2,
                title="S2",
                narration=SAMPLE_SCENE_2_NARRATION,
                visual_direction="V2",
                learning_objective_ids=["LO2", "LO3", "LO4"],
                estimated_duration_seconds=30
            ),
        ]
    )

    result = validate_script_draft(script, target_duration_seconds=60, analysis=analysis)

    assert not result.is_valid
    unknown_issues = [i for i in result.issues if i.code == "UNKNOWN_OBJECTIVE_ID"]
    assert len(unknown_issues) == 2
    messages = [i.message for i in unknown_issues]
    assert any("LO99" in m for m in messages)
    assert any("HALLUCINATED_ID" in m for m in messages)


def test_mixed_duration_and_learning_objective_validation_failures():
    """Verify script with both duration discrepancy and uncovered objectives is flagged and prompt addresses both."""
    analysis = _create_four_objective_analysis()
    req = TrainingVideoRequest(topic="Mixed Defect Test", target_duration_seconds=120)

    # Only 14 words (~6s) for a 120s video, and only covers LO1
    short_narration = "This brief scene covers only the introductory concept for our unit test validation."
    script = ScriptDraft(
        title="Short & Incomplete",
        audience="Staff",
        opening_hook="Quick hook",
        scenes=[
            SceneDraft(
                scene_id="scene_1",
                order=1,
                title="Brief Scene",
                narration=short_narration,
                visual_direction="Brief visual",
                learning_objective_ids=["LO1"],
                estimated_duration_seconds=6
            )
        ]
    )

    result = validate_script_draft(script, target_duration_seconds=120, analysis=analysis)

    assert not result.is_valid
    codes = {i.code for i in result.issues}
    assert "DURATION_OUT_OF_TOLERANCE" in codes
    assert "UNCOVERED_LEARNING_OBJECTIVE" in codes

    prompt = build_script_revision_prompt(req, analysis, script, result)

    # Verifies duration expansion guidance is included
    assert "DURATION GUIDANCE" in prompt
    assert "TOO SHORT" in prompt

    # Verifies missing objective remediation is included
    assert "TARGETED LEARNING OBJECTIVE REMEDIATION" in prompt
    assert "LO2" in prompt
    assert "LO3" in prompt
    assert "LO4" in prompt
    assert "Apply organizational incident reporting protocols" in prompt
    assert "Explain technical headers and SPF verification" in prompt
    assert "Evaluate post-incident quarantine outcomes" in prompt


def test_final_script_preserves_every_objective_from_content_analysis():
    """Verify final script preserves every objective from ContentAnalysis even if ScriptDraft returned an incomplete list."""
    analysis = _create_four_objective_analysis()

    # Draft with incomplete learning_objectives list (LLM returned only LO1)
    draft_with_incomplete_lo = ScriptDraft(
        title="Complete Scenes Incomplete LO List",
        audience="Staff",
        opening_hook="Hook statement",
        closing_summary="Summary statement",
        learning_objectives=[
            LearningObjective(id="LO1", description="Identify deceptive phishing indicators in email domains")
        ],  # Only 1 of 4 objectives in draft field!
        scenes=[
            SceneDraft(scene_id="s1", order=1, title="S1", narration=SAMPLE_LO1_SHORT_NARRATION, visual_direction="V1", learning_objective_ids=["LO1"], estimated_duration_seconds=15),
            SceneDraft(scene_id="s2", order=2, title="S2", narration=SAMPLE_LO2_SHORT_NARRATION, visual_direction="V2", learning_objective_ids=["LO2"], estimated_duration_seconds=15),
            SceneDraft(scene_id="s3", order=3, title="S3", narration=SAMPLE_LO3_SHORT_NARRATION, visual_direction="V3", learning_objective_ids=["LO3"], estimated_duration_seconds=15),
            SceneDraft(scene_id="s4", order=4, title="S4", narration=SAMPLE_LO4_SHORT_NARRATION, visual_direction="V4", learning_objective_ids=["LO4"], estimated_duration_seconds=15),
        ],
        total_estimated_duration_seconds=60
    )

    req = TrainingVideoRequest(topic="Canonical LO Test", target_duration_seconds=60)
    mock_llm = MockLLMProvider()
    nodes = ScriptWorkflowNodes(llm_provider=mock_llm)

    state = VideoScriptState(
        request=req,
        analysis=analysis,
        draft_script=draft_with_incomplete_lo,
        revision_count=0
    )

    res = nodes.finalize_script(state)
    assert res["workflow_status"] == "completed"
    final: FinalScript = res["final_script"]
    assert final is not None

    # Canonical learning objectives must all be present
    assert len(final.learning_objectives) == 4
    final_ids = [lo.id for lo in final.learning_objectives]
    assert final_ids == ["LO1", "LO2", "LO3", "LO4"]
    assert final.learning_objectives[2].description == "Explain technical headers and SPF verification"
    assert final.learning_objectives[3].description == "Evaluate post-incident quarantine outcomes"


def test_coverage_diagnostics_structure_and_reusability():
    """Verify assess_learning_objective_coverage produces deterministic structured report and get_scene_objective_map works."""
    analysis = _create_four_objective_analysis()

    # Script covering LO1 and LO3
    script = ScriptDraft(
        title="Coverage Diagnostics Test",
        audience="Staff",
        opening_hook="Hook",
        scenes=[
            SceneDraft(scene_id="scene_1", order=1, title="S1", narration=SAMPLE_LO1_SHORT_NARRATION, visual_direction="V1", learning_objective_ids=["LO1"], estimated_duration_seconds=15),
            SceneDraft(scene_id="scene_2", order=2, title="S2", narration=SAMPLE_LO3_SHORT_NARRATION, visual_direction="V2", learning_objective_ids=["LO3"], estimated_duration_seconds=15),
        ]
    )

    report = assess_learning_objective_coverage(script, analysis)

    assert report["total_objectives"] == 4
    assert report["covered_objectives"] == 2
    assert len(report["uncovered_objectives"]) == 2

    uncovered_ids = [u["id"] for u in report["uncovered_objectives"]]
    assert uncovered_ids == ["LO2", "LO4"]
    assert all("covered_scene_ids" in u for u in report["uncovered_objectives"])

    # Empty analysis returns clean empty report
    empty_report = assess_learning_objective_coverage(script, None)
    assert empty_report["total_objectives"] == 0
    assert empty_report["covered_objectives"] == 0
    assert empty_report["uncovered_objectives"] == []

    # Scene objective map
    scene_map = get_scene_objective_map(script)
    assert len(scene_map) == 2
    assert scene_map[0]["scene_id"] == "scene_1"
    assert scene_map[0]["learning_objective_ids"] == ["LO1"]


def test_workflow_bounded_recovery_strategy_with_configurable_max_revisions():
    """Verify bounded recovery strategy where workflow recovers on second revision when max_revisions=2."""
    analysis = _create_four_objective_analysis()

    # Initial draft: covers only LO1
    draft_0 = ScriptDraft(
        title="Draft 0",
        audience="Staff",
        opening_hook="Hook",
        scenes=[
            SceneDraft(scene_id="s1", order=1, title="S1", narration=SAMPLE_SCENE_1_NARRATION, visual_direction="V1", learning_objective_ids=["LO1"], estimated_duration_seconds=30),
            SceneDraft(scene_id="s2", order=2, title="S2", narration=SAMPLE_SCENE_2_NARRATION, visual_direction="V2", learning_objective_ids=[], estimated_duration_seconds=30),
        ]
    )

    # Revision 1: fixes LO2 and LO3, but still misses LO4
    draft_rev_1 = ScriptDraft(
        title="Draft Rev 1",
        audience="Staff",
        opening_hook="Hook",
        scenes=[
            SceneDraft(scene_id="s1", order=1, title="S1", narration=SAMPLE_SCENE_1_NARRATION, visual_direction="V1", learning_objective_ids=["LO1", "LO2"], estimated_duration_seconds=30),
            SceneDraft(scene_id="s2", order=2, title="S2", narration=SAMPLE_SCENE_2_NARRATION, visual_direction="V2", learning_objective_ids=["LO3"], estimated_duration_seconds=30),
        ]
    )

    # Revision 2: fixes LO4, all 4 objectives now covered
    draft_rev_2 = ScriptDraft(
        title="Draft Rev 2 - Finalized",
        audience="Staff",
        opening_hook="Hook",
        closing_summary="Summary",
        scenes=[
            SceneDraft(scene_id="s1", order=1, title="S1", narration=SAMPLE_LO1_SHORT_NARRATION, visual_direction="V1", learning_objective_ids=["LO1"], estimated_duration_seconds=15),
            SceneDraft(scene_id="s2", order=2, title="S2", narration=SAMPLE_LO2_SHORT_NARRATION, visual_direction="V2", learning_objective_ids=["LO2"], estimated_duration_seconds=15),
            SceneDraft(scene_id="s3", order=3, title="S3", narration=SAMPLE_LO3_SHORT_NARRATION, visual_direction="V3", learning_objective_ids=["LO3"], estimated_duration_seconds=15),
            SceneDraft(scene_id="s4", order=4, title="S4", narration=SAMPLE_LO4_SHORT_NARRATION, visual_direction="V4", learning_objective_ids=["LO4"], estimated_duration_seconds=15),
        ],
        total_estimated_duration_seconds=60
    )

    mock_llm = MockLLMProvider(
        analysis_fixture=analysis,
        script_draft_fixture=draft_0,
        revision_fixtures=[draft_rev_1, draft_rev_2]
    )
    app = create_script_workflow(llm_provider=mock_llm)

    req = TrainingVideoRequest(topic="Multi-Revision Recovery", target_duration_seconds=60)
    final_state = app.invoke(VideoScriptState(request=req, max_revisions=2))

    assert final_state["workflow_status"] == "completed"
    assert final_state["revision_count"] == 2
    assert final_state["final_script"] is not None
    assert final_state["final_script"].title == "Draft Rev 2 - Finalized"


def test_arbitrary_number_of_learning_objectives_five_objectives():
    """Verify workflow and validation seamlessly support arbitrary numbers of objectives (e.g. 5 objectives)."""
    analysis = ContentAnalysis(
        topic_summary="Advanced Network Security",
        key_concepts=["C1", "C2", "C3", "C4", "C5"],
        learning_objectives=[
            LearningObjective(id="LO1", description="Understand perimeter firewalls"),
            LearningObjective(id="LO2", description="Configure zero-trust policies"),
            LearningObjective(id="LO3", description="Inspect encrypted egress traffic"),
            LearningObjective(id="LO4", description="Mitigate DNS tunneling"),
            LearningObjective(id="LO5", description="Audit access anomalies"),
        ],
        audience_notes="Network engineers",
        recommended_scene_count=5,
        recommended_structure=["P1", "P2", "P3", "P4", "P5"],
        important_terms=["Zero Trust", "DNS Tunneling"]
    )

    script = ScriptDraft(
        title="Zero Trust Architecture",
        audience="Network Engineers",
        opening_hook="Can your perimeter withstand modern stealth threats?",
        closing_summary="Zero trust ensures resilient defenses.",
        scenes=[
            SceneDraft(scene_id="s1", order=1, title="S1", narration=SAMPLE_LO1_SHORT_NARRATION, visual_direction="V1", learning_objective_ids=["LO1", "LO2"], estimated_duration_seconds=15),
            SceneDraft(scene_id="s2", order=2, title="S2", narration=SAMPLE_LO2_SHORT_NARRATION, visual_direction="V2", learning_objective_ids=["LO3"], estimated_duration_seconds=15),
            SceneDraft(scene_id="s3", order=3, title="S3", narration=SAMPLE_LO3_SHORT_NARRATION, visual_direction="V3", learning_objective_ids=["LO4"], estimated_duration_seconds=15),
            SceneDraft(scene_id="s4", order=4, title="S4", narration=SAMPLE_LO4_SHORT_NARRATION, visual_direction="V4", learning_objective_ids=["LO5"], estimated_duration_seconds=15),
        ],
        total_estimated_duration_seconds=60
    )

    result = validate_script_draft(script, target_duration_seconds=60, analysis=analysis)
    assert result.is_valid
    assert result.coverage_report["total_objectives"] == 5
    assert result.coverage_report["covered_objectives"] == 5
    assert result.coverage_report["uncovered_objectives"] == []
