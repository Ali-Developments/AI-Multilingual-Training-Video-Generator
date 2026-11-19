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
from app.workflows.script_generation.staged_generator import StagedScriptGenerator


class ScriptWorkflowNodes:
    """Encapsulates LangGraph workflow nodes with injected LLMProvider dependency."""

    def __init__(self, llm_provider: LLMProvider, checkpoint=None):
        """
        Initialize workflow nodes.
        
        Args:
            llm_provider: Abstract LLMProvider instance (e.g. GroqProvider or test mock).
        """
        self.llm_provider = llm_provider
        self.checkpoint = checkpoint

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

        try:
            # Normalize and safely default fields (records non-blocking language_warnings automatically)
            normalized_req = TrainingVideoRequest(
                topic=topic_clean,
                source_content=source_clean,
                audience=req.audience.strip() if req.audience else "General Professional",
                source_language=getattr(req, "source_language", "auto") or "auto",
                base_language=req.base_language.strip() if req.base_language else "en-US",
                target_languages=[lang.strip() for lang in (req.target_languages or []) if lang and lang.strip()] or [req.base_language or "en-US"],
                target_duration_seconds=req.target_duration_seconds,
                tone=req.tone.strip() if req.tone else "engaging and professional",
                difficulty_level=req.difficulty_level.strip() if req.difficulty_level else "intermediate",
                learning_objectives=[o.strip() for o in req.learning_objectives if o.strip()] if req.learning_objectives else None,
                locale=req.locale.strip() if req.locale else None,
                avatar_provider=getattr(req, "avatar_provider", "mock") or "mock",
                ack_paid_credits=bool(getattr(req, "ack_paid_credits", False)),
                video_style=getattr(req, "video_style", "hybrid_presenter_broll") or "hybrid_presenter_broll",
                persistent_presenter=getattr(req, "persistent_presenter", None),
                branding=getattr(req, "branding", None),
            )
        except Exception as e:
            return {
                "workflow_status": "failed",
                "errors": [str(e)],
            }

        if normalized_req.language_warnings:
            for warn in normalized_req.language_warnings:
                logger.info("Non-blocking language advisory: %s", warn)

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

        cached = self.checkpoint.get("analysis", ContentAnalysis) if self.checkpoint else None
        if cached is not None:
            return {"analysis": cached}
        if self.checkpoint:
            self.checkpoint.event("analysis", "generation", "running")
        prompt = build_content_analysis_prompt(req)
        try:
            analysis = self.llm_provider.generate_structured(
                prompt=prompt,
                schema=ContentAnalysis,
                system_prompt=SYSTEM_PROMPT_CONTENT_ANALYZER,
                temperature=0.2
            )
            # Post-generation check: verify analysis text uses the canonical language
            from app.core.language import verify_output_language
            from app.services.localization.locale_utils import get_language_name

            analysis_text = " ".join(
                [analysis.topic_summary or ""]
                + [lo.description for lo in (analysis.learning_objectives or []) if lo.description]
            ).strip()
            lang_ok, lang_err = verify_output_language(analysis_text, req.base_language)
            if not lang_ok:
                canon_name = get_language_name(req.base_language)
                if self.checkpoint:
                    self.checkpoint.event("analysis", "language_repair", "running")
                logger.warning(
                    "ContentAnalysis language mismatch (%s). Executing bounded language correction into %s ('%s').",
                    lang_err, canon_name, req.base_language
                )
                correction_prompt = (
                    f"{prompt}\n\n"
                    f"CRITICAL CORRECTION: Your previous ContentAnalysis output was not written in {canon_name} ('{req.base_language}'). "
                    f"Rewrite topic_summary, key_concepts, learning_objectives descriptions, audience_notes, recommended_structure, "
                    f"and factual_constraints strictly in {canon_name} ('{req.base_language}') while preserving LO1, LO2 IDs and technical terms."
                )
                analysis = self.llm_provider.generate_structured(
                    prompt=correction_prompt,
                    schema=ContentAnalysis,
                    system_prompt=SYSTEM_PROMPT_CONTENT_ANALYZER,
                    temperature=0.1
                )
                corrected_text = " ".join([analysis.topic_summary] + [lo.description for lo in analysis.learning_objectives])
                if not verify_output_language(corrected_text, req.base_language)[0]:
                    raise ValueError(f"ContentAnalysis still has the wrong language after correction ({req.base_language}).")
            if self.checkpoint:
                self.checkpoint.put("analysis", analysis)
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
        Uses staged structured generation (Outline -> Scene-by-Scene -> Assembly -> Validation -> Targeted Repair)
        when the provider/model prefers staged generation (e.g., `openrouter/free` or `:free` models),
        or as an automatic fallback if monolithic generation is truncated or exceeds token limits.
        """
        logger.info("Executing node: generate_script (LLM: %s)", self.llm_provider.model_name)
        req = state.request
        analysis = state.analysis

        if not req or not analysis:
            return {
                "workflow_status": "failed",
                "errors": ["Cannot generate script: missing request or analysis in state."]
            }

        use_staged = bool(getattr(self.llm_provider, "prefers_staged_script_generation", False))
        staged_generator = StagedScriptGenerator(self.llm_provider, self.checkpoint)

        try:
            if use_staged:
                logger.info(
                    "Model '%s' prefers staged structured script generation. Running 5-stage pipeline.",
                    self.llm_provider.model_name,
                )
                script_draft = staged_generator.generate_script_draft(req, analysis)
            else:
                prompt = build_workflow_script_prompt(req, analysis)
                try:
                    script_draft = self.llm_provider.generate_structured(
                        prompt=prompt,
                        schema=ScriptDraft,
                        system_prompt=SYSTEM_PROMPT_SCRIPT_WRITER,
                        temperature=0.3
                    )
                except Exception as mono_err:
                    err_str = str(mono_err).lower()
                    is_recoverable_via_staged = any(
                        marker in err_str
                        for marker in (
                            "truncated",
                            "placeholder",
                            "validation failed for scriptdraft",
                            "model_compatibility_error",
                            "request too large",
                            "413",
                        )
                    )
                    if not is_recoverable_via_staged:
                        raise
                    logger.warning(
                        "Monolithic ScriptDraft generation failed (%s). Falling back to StagedScriptGenerator.",
                        mono_err,
                    )
                    try:
                        script_draft = staged_generator.generate_script_draft(req, analysis)
                    except Exception as staged_err:
                        if "unhandled mock schema" in str(staged_err).lower():
                            raise mono_err
                        raise staged_err from mono_err

            # ContentAnalysis is the canonical source of truth for learning objectives
            if analysis and analysis.learning_objectives:
                script_draft.learning_objectives = list(analysis.learning_objectives)
            normalize_script_durations(script_draft, language=req.base_language)
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
            analysis=state.analysis,
            language=req.base_language or draft.language
        )

        cov_rep = validation_result.coverage_report
        cov_summary = ""
        if cov_rep:
            cov_summary = f", Objective coverage: {cov_rep.get('covered_objectives', 0)}/{cov_rep.get('total_objectives', 0)}"

        logger.info(
            "Validation completed: is_valid=%s, issues=%d (Duration: %ds / Target: %ds%s)",
            validation_result.is_valid,
            len(validation_result.issues),
            validation_result.estimated_total_duration_seconds,
            req.target_duration_seconds,
            cov_summary
        )

        if cov_rep and cov_rep.get("uncovered_objectives"):
            uncovered_ids = [u["id"] for u in cov_rep["uncovered_objectives"]]
            logger.warning(
                "Uncovered learning objectives detected (%d): %s",
                len(uncovered_ids),
                uncovered_ids
            )

        return {"validation": validation_result}

    def revise_script(self, state: VideoScriptState) -> Dict[str, Any]:
        """
        Repair draft script addressing specific validation issues.
        Uses targeted scene-level repair when `prefers_staged_script_generation` is True
        or when monolithic revision fails due to token limits or truncation.
        """
        current_rev = state.revision_count + 1
        logger.info("Executing node: revise_script (Attempt %d/%d)", current_rev, state.max_revisions)
        if self.checkpoint:
            self.checkpoint.set_revision_count(current_rev)

        req = state.request
        analysis = state.analysis
        current_script = state.draft_script
        validation = state.validation

        if not (req and analysis and current_script and validation):
            return {
                "workflow_status": "failed",
                "errors": ["Missing prerequisites for script revision."]
            }

        use_staged = bool(getattr(self.llm_provider, "prefers_staged_script_generation", False))
        staged_generator = StagedScriptGenerator(self.llm_provider, self.checkpoint)

        try:
            if use_staged:
                logger.info(
                    "Model '%s' prefers staged generation: executing targeted scene-level revision.",
                    self.llm_provider.model_name,
                )
                revised_script = staged_generator.repair_targeted_scenes(
                    request=req,
                    analysis=analysis,
                    script_draft=current_script,
                    validation=validation,
                )
            else:
                prompt = build_script_revision_prompt(req, analysis, current_script, validation)
                try:
                    revised_script = self.llm_provider.generate_structured(
                        prompt=prompt,
                        schema=ScriptDraft,
                        system_prompt=SYSTEM_PROMPT_SCRIPT_REVISER,
                        temperature=0.2
                    )
                except Exception as mono_rev_err:
                    err_str = str(mono_rev_err).lower()
                    is_recoverable_via_staged = any(
                        marker in err_str
                        for marker in (
                            "truncated",
                            "placeholder",
                            "validation failed for scriptdraft",
                            "model_compatibility_error",
                            "request too large",
                            "413",
                        )
                    )
                    if not is_recoverable_via_staged:
                        raise
                    logger.warning(
                        "Monolithic script revision failed (%s). Falling back to targeted scene-level repair.",
                        mono_rev_err,
                    )
                    try:
                        revised_script = staged_generator.repair_targeted_scenes(
                            request=req,
                            analysis=analysis,
                            script_draft=current_script,
                            validation=validation,
                        )
                    except Exception as staged_err:
                        if "unhandled mock schema" in str(staged_err).lower():
                            raise mono_rev_err
                        raise staged_err from mono_rev_err

            # ContentAnalysis is the canonical source of truth for learning objectives
            if analysis and analysis.learning_objectives:
                revised_script.learning_objectives = list(analysis.learning_objectives)
            normalize_script_durations(revised_script, language=req.base_language)
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

        # ContentAnalysis.learning_objectives is the canonical source of truth
        canonical_objectives = (
            list(state.analysis.learning_objectives)
            if state.analysis and state.analysis.learning_objectives
            else list(draft.learning_objectives or [])
        )

        final = FinalScript(
            title=draft.title,
            language=req.base_language or draft.language,
            audience=draft.audience,
            target_duration_seconds=req.target_duration_seconds,
            total_estimated_duration_seconds=draft.total_estimated_duration_seconds,
            opening_hook=draft.opening_hook,
            closing_summary=draft.closing_summary,
            learning_objectives=canonical_objectives,
            scenes=draft.scenes,
            metadata={
                "revision_count": state.revision_count,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "llm_model": self.llm_provider.model_name,
                "target_languages": req.target_languages,
                "base_language": req.base_language,
                "canonical_language": req.base_language,
                "source_language": getattr(req, "source_language", "auto"),
                "detected_source_language": getattr(req, "detected_source_language", None),
                "language_warnings": list(getattr(req, "language_warnings", []) or []),
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
        err_details = [f"Script validation failed after {state.revision_count} revision(s)."]
        if state.validation and state.validation.issues:
            for issue in state.validation.issues:
                err_details.append(f"[{issue.code}] {issue.message}")
        new_errors = list(state.errors) + err_details
        return {
            "workflow_status": "needs_review",
            "final_script": None,
            "errors": new_errors
        }
