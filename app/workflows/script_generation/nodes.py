"""Workflow node implementations for video script generation.

All LLM operations are routed strictly through the injected LLMProvider abstraction.
Nodes do NOT directly import or call vendor-specific SDKs.
"""

from typing import Dict, Any, Optional
from datetime import datetime, timezone

from app.core.logging import logger
from app.models.schemas import (
    TrainingVideoRequest,
    ContentAnalysis,
    ScriptDraft,
    FinalScript,
)
from app.services.llm.base import LLMProvider
from app.workflows.script_generation.state import VideoScriptState
from app.workflows.script_generation.validators import (
    validate_script_draft,
    normalize_script_durations,
)
from app.workflows.script_generation.prompts import (
    SYSTEM_PROMPT_CONTENT_ANALYZER,
    SYSTEM_PROMPT_SCRIPT_WRITER,
    SYSTEM_PROMPT_SCRIPT_REVISER,
    build_content_analysis_prompt,
    build_workflow_script_prompt,
    build_script_revision_prompt,
)


class ScriptWorkflowNodes:
    """Encapsulates LangGraph workflow nodes with injected LLMProvider dependency."""

    def __init__(self, llm_provider: LLMProvider):
        """
        Initialize workflow nodes.
        
        Args:
            llm_provider: Abstract LLMProvider instance (e.g. GroqProvider or test mock).
        """
        self.llm_provider = llm_provider

    def normalize_input(self, state: VideoScriptState) -> Dict[str, Any]:
        """
        Validate, trim, and normalize the incoming video generation request.
        
        NOTE: This node does NOT make LLM calls.
        """
        logger.info("Executing node: normalize_input")
        req = state.request

        if req is None:
            return {
                "workflow_status": "failed",
                "errors": ["Missing TrainingVideoRequest in state."]
            }

        topic_clean = req.topic.strip() if req.topic else None
        source_clean = req.source_content.strip() if req.source_content else None

        if not (topic_clean or source_clean):
            return {
                "workflow_status": "failed",
                "errors": ["Request must include at least non-empty 'topic' or 'source_content'."]
            }

        if req.target_duration_seconds < 15 or req.target_duration_seconds > 3600:
            return {
                "workflow_status": "failed",
                "errors": [
                    f"Invalid target_duration_seconds ({req.target_duration_seconds}). Must be between 15 and 3600 seconds."
                ]
            }

        # Normalize and safely default fields
        normalized_req = TrainingVideoRequest(
            topic=topic_clean,
            source_content=source_clean,
            audience=req.audience.strip() if req.audience else "General Professional",
            base_language=req.base_language.strip() if req.base_language else "en-US",
            target_languages=[lang.strip() for lang in req.target_languages if lang.strip()] or [req.base_language],
            target_duration_seconds=req.target_duration_seconds,
            tone=req.tone.strip() if req.tone else "engaging and professional",
            difficulty_level=req.difficulty_level.strip() if req.difficulty_level else "intermediate",
            learning_objectives=[o.strip() for o in req.learning_objectives if o.strip()] if req.learning_objectives else None,
            locale=req.locale.strip() if req.locale else None
        )

        return {
            "request": normalized_req,
            "workflow_status": "processing"
        }

    def analyze_content(self, state: VideoScriptState) -> Dict[str, Any]:
        """
        Perform pedagogical content analysis using the abstract LLM provider.
        """
        logger.info("Executing node: analyze_content (LLM: %s)", self.llm_provider.model_name)
        req = state.request
        if req is None:
            return {"workflow_status": "failed", "errors": ["Cannot analyze content: request is None."]}

        prompt = build_content_analysis_prompt(req)
        try:
            analysis = self.llm_provider.generate_structured(
                prompt=prompt,
                schema=ContentAnalysis,
                system_prompt=SYSTEM_PROMPT_CONTENT_ANALYZER,
                temperature=0.2
            )
            return {"analysis": analysis}
        except Exception as e:
            logger.error("Error during content analysis: %s", str(e))
            return {
                "workflow_status": "failed",
                "errors": [f"Content analysis failed: {str(e)}"]
            }

    def generate_script(self, state: VideoScriptState) -> Dict[str, Any]:
        """
        Draft initial scene-by-scene instructional script using the abstract LLM provider.
        """
        logger.info("Executing node: generate_script (LLM: %s)", self.llm_provider.model_name)
        req = state.request
        analysis = state.analysis

        if not req or not analysis:
            return {
                "workflow_status": "failed",
                "errors": ["Cannot generate script: missing request or analysis in state."]
            }

        prompt = build_workflow_script_prompt(req, analysis)
        try:
            script_draft = self.llm_provider.generate_structured(
                prompt=prompt,
                schema=ScriptDraft,
                system_prompt=SYSTEM_PROMPT_SCRIPT_WRITER,
                temperature=0.3
            )
            normalize_script_durations(script_draft)
            return {"draft_script": script_draft}
        except Exception as e:
            logger.error("Error during script generation: %s", str(e))
            return {
                "workflow_status": "failed",
                "errors": [f"Script generation failed: {str(e)}"]
            }

    def validate_script(self, state: VideoScriptState) -> Dict[str, Any]:
        """
        Perform deterministic Python quality validation on the active draft script.
        """
        logger.info("Executing node: validate_script")
        draft = state.draft_script
        req = state.request

        if not draft or not req:
            return {
                "workflow_status": "failed",
                "errors": ["Cannot validate: draft_script or request is missing."]
            }

        validation_result = validate_script_draft(
            script=draft,
            target_duration_seconds=req.target_duration_seconds,
            analysis=state.analysis
        )

        logger.info(
            "Validation completed: is_valid=%s, issues=%d (Duration: %ds / Target: %ds)",
            validation_result.is_valid,
            len(validation_result.issues),
            validation_result.estimated_total_duration_seconds,
            req.target_duration_seconds
        )

        return {"validation": validation_result}

    def revise_script(self, state: VideoScriptState) -> Dict[str, Any]:
        """
        Repair draft script addressing specific validation issues.
        """
        current_rev = state.revision_count + 1
        logger.info("Executing node: revise_script (Attempt %d/%d)", current_rev, state.max_revisions)

        req = state.request
        analysis = state.analysis
        current_script = state.draft_script
        validation = state.validation

        if not (req and analysis and current_script and validation):
            return {
                "workflow_status": "failed",
                "errors": ["Missing prerequisites for script revision."]
            }

        prompt = build_script_revision_prompt(req, analysis, current_script, validation)
        try:
            revised_script = self.llm_provider.generate_structured(
                prompt=prompt,
                schema=ScriptDraft,
                system_prompt=SYSTEM_PROMPT_SCRIPT_REVISER,
                temperature=0.2
            )
            normalize_script_durations(revised_script)
            return {
                "draft_script": revised_script,
                "revision_count": current_rev
            }
        except Exception as e:
            logger.error("Error during script revision: %s", str(e))
            return {
                "workflow_status": "failed",
                "revision_count": current_rev,
                "errors": [f"Script revision failed: {str(e)}"]
            }

    def finalize_script(self, state: VideoScriptState) -> Dict[str, Any]:
        """
        Package approved draft script into a clean FinalScript data contract.
        """
        logger.info("Executing node: finalize_script")
        draft = state.draft_script
        req = state.request

        if not draft or not req:
            return {
                "workflow_status": "failed",
                "errors": ["Cannot finalize script: missing draft_script or request."]
            }

        final = FinalScript(
            title=draft.title,
            language=draft.language,
            audience=draft.audience,
            target_duration_seconds=req.target_duration_seconds,
            total_estimated_duration_seconds=draft.total_estimated_duration_seconds,
            opening_hook=draft.opening_hook,
            closing_summary=draft.closing_summary,
            learning_objectives=draft.learning_objectives or (state.analysis.learning_objectives if state.analysis else []),
            scenes=draft.scenes,
            metadata={
                "revision_count": state.revision_count,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "llm_model": self.llm_provider.model_name,
                "target_languages": req.target_languages,
                "base_language": req.base_language
            }
        )

        return {
            "final_script": final,
            "workflow_status": "completed"
        }

    def mark_needs_review(self, state: VideoScriptState) -> Dict[str, Any]:
        """
        Flag script as needing human review when revision threshold is exhausted.
        """
        logger.warning(
            "Executing node: mark_needs_review. Script failed validation after %d revisions.",
            state.revision_count
        )
        return {
            "workflow_status": "needs_review",
            "final_script": None
        }
