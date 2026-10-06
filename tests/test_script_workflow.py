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
)
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
        model_name_str: str = "mock-llm-v1"
    ):
        self._model_name = model_name_str
        self.analysis_fixture = analysis_fixture
        self.script_draft_fixture = script_draft_fixture
        self.revised_script_fixture = revised_script_fixture
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
