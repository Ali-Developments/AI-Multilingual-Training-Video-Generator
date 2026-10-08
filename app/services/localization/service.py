"""Production-grade localization service and multi-locale bundle orchestrator."""

from typing import List, Optional, Tuple, Dict, Any
from app.core.config import settings
from app.core.logging import logger
from app.models.schemas import (
    FinalScript,
    LocalizedScript,
    LocalizedScene,
    CulturalGuidance,
    LocalizationRequest,
    LocalizationValidationResult,
    LocalizationBundle,
    TerminologyEntry,
)
from app.services.llm.base import LLMProvider
from app.services.llm.factory import get_llm_provider
from app.services.localization.locale_utils import (
    normalize_locale,
    get_text_direction,
    get_language_name,
    get_region_name,
)
from app.services.localization.prompts import (
    SYSTEM_PROMPT_LOCALIZER,
    SYSTEM_PROMPT_LOCALIZATION_REVISER,
    SYSTEM_PROMPT_POST_TTS_DURATION_REVISER,
    build_localization_prompt,
    build_localization_revision_prompt,
    build_post_tts_duration_revision_prompt,
)
from app.services.localization.validators import (
    normalize_localized_structure_and_durations,
    validate_localized_script,
)
from app.workflows.script_generation.validators import estimate_narration_duration_seconds


class LocalizationService:
    """
    Vendor-agnostic script localization and cultural adaptation service.
    
    Consumes canonical FinalScript (Step 3) and produces structurally aligned
    LocalizedScript instances for requested locales while strictly preserving:
    - Source script immutability
    - Scene identity (scene_id, order, scene_type)
    - Learning objective alignment
    - Pedagogical factual fidelity
    """

    def __init__(
        self,
        llm_provider: Optional[LLMProvider] = None,
        max_revisions: Optional[int] = None,
    ) -> None:
        """
        Initialize the LocalizationService.
        
        Args:
            llm_provider: Vendor-agnostic LLM provider abstraction (GroqProvider, MockLLMProvider, etc.)
            max_revisions: Maximum revision attempts per locale upon validation failure.
        """
        self.llm_provider = llm_provider or get_llm_provider()
        self.max_revisions = (
            max_revisions
            if max_revisions is not None
            else settings.LOCALIZATION_MAX_REVISIONS
        )

    def localize(
        self,
        request: LocalizationRequest,
    ) -> Tuple[Optional[LocalizedScript], LocalizationValidationResult, str]:
        """
        Execute localized script generation and controlled validation loop for a single locale.
        
        Returns:
            Tuple of (localized_script, validation_result, workflow_status)
            workflow_status is one of: "completed", "needs_review", "failed"
        """
        # Ensure canonical source script immutability
        source = request.source_script.model_copy(deep=True)
        norm_locale = normalize_locale(request.target_locale)
        text_direction = get_text_direction(norm_locale)

        logger.info(
            "Starting script localization: source='%s' -> target='%s' (direction=%s, level=%s)",
            source.language,
            norm_locale,
            text_direction,
            request.adaptation_level,
        )

        # Optimization: if target locale matches source language, avoid unnecessary LLM call
        try:
            norm_source = normalize_locale(source.language)
        except Exception:
            norm_source = source.language.strip()

        if norm_locale.lower() == norm_source.lower():
            logger.info("Target locale '%s' matches source '%s'; mirroring canonical script without LLM call.", norm_locale, norm_source)
            localized_scenes = [
                LocalizedScene(
                    scene_id=s.scene_id,
                    order=s.order,
                    title=s.title,
                    purpose=s.purpose,
                    narration=s.narration,
                    estimated_duration_seconds=s.estimated_duration_seconds,
                    visual_direction=s.visual_direction,
                    on_screen_text=s.on_screen_text,
                    learning_objective_ids=list(s.learning_objective_ids),
                    scene_type=s.scene_type,
                )
                for s in source.scenes
            ]
            mirror_script = LocalizedScript(
                title=source.title,
                source_language=source.language,
                language=source.language,
                locale=norm_locale,
                text_direction=text_direction,
                audience=source.audience,
                learning_objectives=[lo.model_copy(deep=True) for lo in source.learning_objectives],
                opening_hook=source.opening_hook,
                scenes=localized_scenes,
                closing_summary=source.closing_summary,
                target_duration_seconds=source.target_duration_seconds,
                total_estimated_duration_seconds=source.total_estimated_duration_seconds,
                cultural_guidance=CulturalGuidance(
                    locale=norm_locale,
                    language_name=get_language_name(norm_locale),
                    region_name=get_region_name(norm_locale),
                    cultural_notes=["Canonical base script used directly without translation."],
                ),
                metadata={
                    "is_canonical_source": True,
                    "skipped_llm_call": True,
                    "adaptation_level": request.adaptation_level,
                    "revision_count": 0,
                },
            )
            val = validate_localized_script(mirror_script, source, norm_locale)
            return mirror_script, val, "completed"

        # Generate initial localized script draft
        prompt = build_localization_prompt(request, norm_locale, text_direction)
        try:
            script_candidate = self.llm_provider.generate_structured(
                prompt=prompt,
                schema=LocalizedScript,
                system_prompt=SYSTEM_PROMPT_LOCALIZER,
                temperature=0.2,
            )
        except Exception as e:
            logger.error("LLM generation failed for locale '%s': %s", norm_locale, str(e))
            raise RuntimeError(f"LLM localization generation failed for locale '{norm_locale}': {str(e)}") from e

        # Python normalizes structure and recalculates narration durations
        normalize_localized_structure_and_durations(
            localized_script=script_candidate,
            source_script=source,
            target_locale=norm_locale,
            text_direction=text_direction,
        )

        validation = validate_localized_script(
            localized_script=script_candidate,
            source_script=source,
            target_locale=norm_locale,
        )

        if validation.is_valid:
            logger.info("Script for locale '%s' passed initial validation on first attempt.", norm_locale)
            script_candidate.metadata.update({
                "revision_count": 0,
                "llm_model": self.llm_provider.model_name,
                "adaptation_level": request.adaptation_level,
            })
            return script_candidate, validation, "completed"

        # Revision Loop
        current_script = script_candidate
        revisions = 0
        while not validation.is_valid and revisions < self.max_revisions:
            revisions += 1
            logger.warning(
                "Localized script for '%s' failed validation (%d errors). Triggering revision attempt %d/%d.",
                norm_locale,
                len([i for i in validation.issues if i.severity == "error"]),
                revisions,
                self.max_revisions,
            )

            rev_prompt = build_localization_revision_prompt(request, current_script, validation)
            try:
                revised_script = self.llm_provider.generate_structured(
                    prompt=rev_prompt,
                    schema=LocalizedScript,
                    system_prompt=SYSTEM_PROMPT_LOCALIZATION_REVISER,
                    temperature=0.2,
                )
            except Exception as e:
                logger.error("LLM revision failed for locale '%s': %s", norm_locale, str(e))
                break

            normalize_localized_structure_and_durations(
                localized_script=revised_script,
                source_script=source,
                target_locale=norm_locale,
                text_direction=text_direction,
            )

            validation = validate_localized_script(
                localized_script=revised_script,
                source_script=source,
                target_locale=norm_locale,
            )

            current_script = revised_script
            if validation.is_valid:
                logger.info("Script for locale '%s' succeeded on revision attempt %d.", norm_locale, revisions)
                current_script.metadata.update({
                    "revision_count": revisions,
                    "llm_model": self.llm_provider.model_name,
                    "adaptation_level": request.adaptation_level,
                })
                return current_script, validation, "completed"

        # Reached revision ceiling while still invalid
        logger.warning(
            "Script for locale '%s' remained invalid after %d revision(s); marked 'needs_review'.",
            norm_locale,
            revisions,
        )
        current_script.metadata.update({
            "revision_count": revisions,
            "llm_model": self.llm_provider.model_name,
            "adaptation_level": request.adaptation_level,
            "validation_errors": [i.model_dump() for i in validation.issues],
        })
        return current_script, validation, "needs_review"

    def localize_bundle(
        self,
        source_script: FinalScript,
        target_locales: Optional[List[str]] = None,
        adaptation_level: str = "cultural_adaptation",
        preserve_terms: Optional[List[str]] = None,
        terminology_entries: Optional[List[TerminologyEntry]] = None,
        additional_context: Optional[str] = None,
    ) -> LocalizationBundle:
        """
        Orchestrate multi-locale script localization with strict error isolation.
        
        Features:
        - Source script immutability preserved.
        - Target locales normalized and deduplicated.
        - Empty target list gracefully handled without error.
        - Independent per-locale execution (failure in locale A does not fail locale B).
        """
        # Ensure source immutability
        source_copy = source_script.model_copy(deep=True)

        # Resolve requested locales
        raw_locales = target_locales
        if raw_locales is None:
            raw_locales = source_script.metadata.get("target_languages", [])

        # Graceful handling of empty target list
        if not raw_locales:
            logger.info("No target locales provided; returning empty localization bundle.")
            return LocalizationBundle(
                source_script=source_copy,
                localized_scripts={},
                failed_locales={},
                metadata={
                    "message": "No target locales specified. Canonical source script remains active.",
                    "total_locales_requested": 0,
                    "successful_count": 0,
                    "failed_count": 0,
                },
            )

        # Deduplicate and validate normalized locales
        normalized_targets: List[str] = []
        failed_locales: Dict[str, Dict[str, Any]] = {}
        localized_scripts: Dict[str, LocalizedScript] = {}

        for raw in raw_locales:
            try:
                norm = normalize_locale(raw)
                if norm not in normalized_targets:
                    normalized_targets.append(norm)
            except ValueError as ve:
                logger.warning("Rejecting invalid locale format '%s': %s", raw, str(ve))
                failed_locales[raw] = {
                    "status": "failed",
                    "error": str(ve),
                }

        # Process each valid target independently (Error Isolation)
        for target_loc in normalized_targets:
            try:
                req = LocalizationRequest(
                    source_script=source_copy,
                    target_locale=target_loc,
                    adaptation_level=adaptation_level,
                    preserve_terms=preserve_terms,
                    terminology_entries=terminology_entries,
                    additional_context=additional_context,
                )
                script, val, status = self.localize(req)
                if status == "completed" and script:
                    localized_scripts[target_loc] = script
                else:
                    failed_locales[target_loc] = {
                        "status": status,
                        "issues": [i.model_dump() for i in val.issues],
                        "script": script.model_dump() if script else None,
                    }
            except Exception as e:
                logger.error("Localization failed with unhandled error for locale '%s': %s", target_loc, str(e))
                failed_locales[target_loc] = {
                    "status": "failed",
                    "error": str(e),
                }

        bundle = LocalizationBundle(
            source_script=source_copy,
            localized_scripts=localized_scripts,
            failed_locales=failed_locales,
            metadata={
                "total_locales_requested": len(raw_locales),
                "unique_locales_count": len(normalized_targets),
                "successful_count": len(localized_scripts),
                "failed_count": len(failed_locales),
                "adaptation_level": adaptation_level,
            },
        )
        return bundle

    def reconcile_post_tts_duration(
        self,
        current_script: LocalizedScript,
        measured_audio_track: Any,
        target_duration_seconds: float,
        tolerance_percent: Optional[float] = None,
    ) -> Tuple[LocalizedScript, bool, str]:
        """
        Evaluate measured TTS audio duration against target duration.
        If actual speech duration overruns target by more than tolerance_percent,
        invoke LLM to intelligently shorten spoken narration while strictly
        preserving learning objectives, scene structure, and pedagogical fidelity.

        Returns:
            Tuple of (reconciled_script, was_reconciled, summary_message)
        """
        tolerance_pct = (
            tolerance_percent
            if tolerance_percent is not None
            else settings.POST_TTS_TOLERANCE_PERCENT
        )
        measured_total = (
            getattr(measured_audio_track, "total_audio_duration_seconds", None)
            or getattr(measured_audio_track, "total_duration_seconds", 0.0)
        )
        if measured_total <= 0.0:
            return current_script, False, "No valid measured audio duration found."

        allowed_diff = target_duration_seconds * (tolerance_pct / 100.0)
        diff = measured_total - target_duration_seconds

        # Only trigger reconciliation if audio genuinely overruns target beyond tolerance
        if abs(diff) <= allowed_diff:
            logger.info(
                "Post-TTS timing check passed for locale '%s': measured=%.2fs, target=%.1fs (diff=%.2fs <= %.2fs tolerance)",
                current_script.locale,
                measured_total,
                target_duration_seconds,
                diff,
                allowed_diff,
            )
            return (
                current_script,
                False,
                f"Audio duration ({measured_total:.2f}s) is within {tolerance_pct}% of target ({target_duration_seconds:.1f}s)",
            )

        logger.warning(
            "Post-TTS duration overrun for locale '%s': measured=%.2fs vs target=%.1fs (diff=%.2fs > %.2fs tolerance). Initiating condensation revision.",
            current_script.locale,
            measured_total,
            target_duration_seconds,
            diff,
            allowed_diff,
        )

        audio_items = (
            getattr(measured_audio_track, "scene_audio", None)
            or getattr(measured_audio_track, "scene_audios", [])
        )
        scene_durations = {
            sa.scene_id: sa.duration_seconds
            for sa in audio_items
        }

        prompt = build_post_tts_duration_revision_prompt(
            current_script=current_script,
            measured_total_seconds=measured_total,
            target_duration_seconds=target_duration_seconds,
            scene_durations=scene_durations,
        )

        try:
            raw_revised = self.llm_provider.generate_structured(
                prompt=prompt,
                schema=LocalizedScript,
                system_prompt=SYSTEM_PROMPT_POST_TTS_DURATION_REVISER,
            )

            # Preserve immutable structural fields from current_script
            revised = current_script.model_copy(deep=True)
            revised.title = raw_revised.title or current_script.title
            revised.opening_hook = raw_revised.opening_hook or current_script.opening_hook
            revised.closing_summary = raw_revised.closing_summary or current_script.closing_summary
            revised.target_duration_seconds = target_duration_seconds

            # Align scenes
            if len(raw_revised.scenes) == len(current_script.scenes):
                for idx, src_s in enumerate(current_script.scenes):
                    rev_s = raw_revised.scenes[idx]
                    # Retain structural IDs
                    revised.scenes[idx].scene_id = src_s.scene_id
                    revised.scenes[idx].order = src_s.order
                    revised.scenes[idx].scene_type = src_s.scene_type
                    revised.scenes[idx].learning_objective_ids = src_s.learning_objective_ids
                    # Apply shortened narration
                    if rev_s.narration and rev_s.narration.strip():
                        revised.scenes[idx].narration = rev_s.narration.strip()
                    if rev_s.title:
                        revised.scenes[idx].title = rev_s.title
                    if rev_s.purpose:
                        revised.scenes[idx].purpose = rev_s.purpose
                    if rev_s.visual_direction:
                        revised.scenes[idx].visual_direction = rev_s.visual_direction
                    if src_s.on_screen_text is None:
                        revised.scenes[idx].on_screen_text = None
                    elif rev_s.on_screen_text:
                        revised.scenes[idx].on_screen_text = rev_s.on_screen_text

                    # Recalculate honest estimated duration
                    est_dur = estimate_narration_duration_seconds(
                        revised.scenes[idx].narration,
                        locale=current_script.locale,
                    )
                    revised.scenes[idx].estimated_duration_seconds = est_dur
            else:
                logger.warning(
                    "Post-TTS revised script scene count mismatch (%d vs %d); falling back to existing script.",
                    len(raw_revised.scenes),
                    len(current_script.scenes),
                )
                return current_script, False, "Revision produced scene count mismatch"

            revised.total_estimated_duration_seconds = sum(
                s.estimated_duration_seconds for s in revised.scenes
            )

            logger.info(
                "Post-TTS duration reconciliation complete for locale '%s': condensed text estimated at %.2fs (down from measured %.2fs)",
                current_script.locale,
                revised.total_estimated_duration_seconds,
                measured_total,
            )
            return (
                revised,
                True,
                f"Condensed narration from measured {measured_total:.2f}s towards target {target_duration_seconds:.1f}s",
            )
        except Exception as e:
            logger.error("Failed post-TTS duration reconciliation LLM call: %s", e)
            return current_script, False, f"Reconciliation error: {e}"
