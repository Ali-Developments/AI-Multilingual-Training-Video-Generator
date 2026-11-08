"""Dedicated post-TTS duration reconciliation and scene budgeting service."""

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

from app.core.config import settings
from app.core.logging import logger
from app.models.schemas import LocalizedScript, LocalizedAudioTrack, LocalizedScene, SceneDraft
from app.services.llm.base import LLMProvider
from app.services.duration.models import (
    SceneDurationBudget,
    DurationRevisionAttempt,
    DurationReconciliationResult,
)
from app.services.localization.prompts import (
    SYSTEM_PROMPT_POST_TTS_DURATION_REVISER,
)
from app.services.localization.validators import estimate_narration_duration_seconds


# Pedagogical importance weights for scene duration budgeting
SCENE_TYPE_WEIGHTS: Dict[str, float] = {
    "intro": 0.8,
    "concept": 1.2,
    "example": 1.4,
    "quiz": 1.1,
    "summary": 0.8,
    "outro": 0.8,
}


def allocate_scene_duration_budgets(
    scenes: List[Any],
    scene_durations: Dict[str, float],
    target_total_seconds: float,
) -> List[SceneDurationBudget]:
    """
    Deterministically allocate duration budget across scenes based on pedagogical weight
    and initial measured durations.
    
    Guarantees sum(allocated_budget_seconds) ≈ target_total_seconds.
    Intro/outro receive tighter budgets; core instructional scenes (concept, example) receive more.
    """
    if not scenes:
        return []

    # Calculate weighted contributions
    weighted_scores: Dict[str, float] = {}
    for s in scenes:
        w = SCENE_TYPE_WEIGHTS.get(s.scene_type.lower(), 1.0)
        curr_dur = scene_durations.get(s.scene_id, s.estimated_duration_seconds or 6.0)
        # Combine instructional weight with current duration footprint
        weighted_scores[s.scene_id] = w * max(curr_dur, 1.0)

    total_weighted = sum(weighted_scores.values())
    total_weighted = total_weighted if total_weighted > 0 else 1.0

    budgets: List[SceneDurationBudget] = []
    accumulated = 0.0
    for idx, s in enumerate(scenes):
        w = SCENE_TYPE_WEIGHTS.get(s.scene_type.lower(), 1.0)
        curr_dur = scene_durations.get(s.scene_id, s.estimated_duration_seconds or 6.0)
        
        if idx == len(scenes) - 1:
            # Allocate remainder to last scene to guarantee exact mathematical sum
            budget = max(1.5, round(target_total_seconds - accumulated, 2))
        else:
            proportion = (weighted_scores[s.scene_id] / total_weighted) if total_weighted > 0 else (1.0 / max(len(scenes), 1))
            budget = max(2.0, round(target_total_seconds * proportion, 2))
            accumulated += budget

        budgets.append(
            SceneDurationBudget(
                scene_id=s.scene_id,
                scene_type=s.scene_type,
                measured_duration_seconds=round(curr_dur, 2),
                allocated_budget_seconds=round(budget, 2),
                weight=w,
            )
        )

    return budgets


def build_duration_condensation_prompt(
    current_script: LocalizedScript,
    measured_total_seconds: float,
    target_duration_seconds: float,
    compression_ratio: float,
    scene_budgets: List[SceneDurationBudget],
) -> str:
    """Build high-fidelity condensation prompt with scene budgets and compression requirements."""
    scenes_payload = []
    budget_map = {b.scene_id: b for b in scene_budgets}

    for s in current_script.scenes:
        b = budget_map.get(s.scene_id)
        current_dur = b.measured_duration_seconds if b else s.estimated_duration_seconds
        scene_count = max(len(current_script.scenes), 1)
        budget_dur = b.allocated_budget_seconds if b else (target_duration_seconds / scene_count)
        word_count = len(s.narration.split()) if s.narration else 0
        target_words = max(4, int(word_count * compression_ratio))

        scenes_payload.append({
            "scene_id": s.scene_id,
            "order": s.order,
            "scene_type": s.scene_type,
            "learning_objective_ids": s.learning_objective_ids,
            "current_measured_duration_seconds": round(current_dur, 2),
            "allocated_target_duration_seconds": round(budget_dur, 2),
            "current_word_count": word_count,
            "suggested_target_word_count": target_words,
            "current_narration": s.narration,
        })

    prompt_data = {
        "instruction": (
            "The measured audio duration exceeds the target video duration. "
            "You MUST condense the narration of the scenes to match the target duration budget "
            "while strictly preserving pedagogical meaning, technical terminology, safety/compliance requirements, "
            "and natural Arabic phrasing."
        ),
        "target_total_duration_seconds": target_duration_seconds,
        "measured_total_duration_seconds": round(measured_total_seconds, 2),
        "required_compression_ratio": round(compression_ratio, 3),
        "locale": current_script.locale,
        "scenes": scenes_payload,
        "strict_rules": [
            "Do NOT remove or alter scene_id, order, scene_type, or learning_objective_ids.",
            "Shorten the narration text by eliminating filler words, redundant explanations, and verbose phrases.",
            "Prioritize shortening the scenes with the largest duration overrun relative to their allocated budget.",
            "Maintain instructional clarity and factual correctness.",
            "Return valid JSON conforming to the LocalizedScript schema.",
        ]
    }
    return json.dumps(prompt_data, ensure_ascii=False, indent=2)


class DurationReconciliationService:
    """
    Dedicated service for post-TTS duration reconciliation.
    
    Guarantees:
    - Real measured TTS audio is the authoritative source of truth.
    - Deterministic scene duration budget allocation.
    - Condenses script via LLM when audio deviates beyond tolerance.
    - Enforces maximum revision attempts (default 2) to eliminate infinite loops.
    - Re-synthesizes TTS and re-measures duration on each iteration.
    - Strictly isolates avatar generation (avatar is NEVER called during duration reconciliation).
    """

    def __init__(
        self,
        llm_provider: Optional[LLMProvider] = None,
        max_revisions: Optional[int] = None,
        tolerance_seconds: Optional[float] = None,
    ) -> None:
        if llm_provider is None:
            try:
                from app.services.llm.factory import get_llm_provider
                llm_provider = get_llm_provider()
            except Exception as e:
                logger.warning("Could not auto-initialize LLM provider for DurationReconciliationService: %s", e)
        self.llm_provider = llm_provider
        self.max_revisions = max_revisions or getattr(settings, "MAX_POST_TTS_REVISIONS", 2)
        self.tolerance_seconds = tolerance_seconds or getattr(settings, "POST_TTS_DURATION_TOLERANCE_SECONDS", 2.0)

    def reconcile_locale_duration(
        self,
        current_script: LocalizedScript,
        measured_audio_track: LocalizedAudioTrack,
        target_duration_seconds: float,
        tts_service: Any,
        project_id: str,
        tolerance_seconds: Optional[float] = None,
        max_revisions: Optional[int] = None,
    ) -> Tuple[LocalizedScript, LocalizedAudioTrack, DurationReconciliationResult]:
        """
        Execute end-to-end multi-round duration reconciliation for a single locale.
        
        Returns:
            (final_script, final_audio_track, reconciliation_result)
        """
        tol_sec = tolerance_seconds if tolerance_seconds is not None else self.tolerance_seconds
        percent_tol = target_duration_seconds * (settings.POST_TTS_TOLERANCE_PERCENT / 100.0)
        tol_sec = max(tol_sec, percent_tol)
        max_rev = max_revisions or self.max_revisions

        measured_total = getattr(measured_audio_track, "total_audio_duration_seconds", None) or getattr(measured_audio_track, "total_duration_seconds", 0.0)
        diff = abs(measured_total - target_duration_seconds)

        initial_dur = measured_total
        history: List[DurationRevisionAttempt] = []

        logger.info(
            "Evaluating post-TTS duration for locale '%s': measured=%.2fs vs target=%.1fs (diff=%.2fs, tolerance=±%.2fs)",
            current_script.locale,
            measured_total,
            target_duration_seconds,
            diff,
            tol_sec,
        )

        # Baseline check 1: Zero or invalid duration cannot be reconciled
        if measured_total <= 0.0 or target_duration_seconds <= 0.0:
            logger.warning(
                "Post-TTS duration reconciliation skipped for locale '%s': measured audio duration (%.2fs) or target duration (%.1fs) is non-positive.",
                current_script.locale,
                measured_total,
                target_duration_seconds,
            )
            result = DurationReconciliationResult(
                locale=current_script.locale,
                target_duration_seconds=target_duration_seconds,
                tolerance_seconds=tol_sec,
                initial_duration_seconds=measured_total,
                final_duration_seconds=measured_total,
                revisions_attempted=0,
                max_revisions=max_rev,
                is_approved=False,
                status="needs_review",
                message=f"Audio synthesis failed or has zero duration (measured={measured_total:.2f}s, target={target_duration_seconds:.1f}s) for locale '{current_script.locale}'. Cannot reconcile duration.",
            )
            return current_script, measured_audio_track, result

        # Baseline check 2: already within tolerance?
        if diff <= tol_sec:
            result = DurationReconciliationResult(
                locale=current_script.locale,
                target_duration_seconds=target_duration_seconds,
                tolerance_seconds=tol_sec,
                initial_duration_seconds=initial_dur,
                final_duration_seconds=measured_total,
                revisions_attempted=0,
                max_revisions=max_rev,
                is_approved=True,
                status="within_tolerance",
                message=f"Audio duration ({measured_total:.2f}s) is within tolerance (±{tol_sec:.1f}s) of target ({target_duration_seconds:.1f}s)",
            )
            return current_script, measured_audio_track, result

        # If LLM provider not available, cannot condense
        if not self.llm_provider:
            logger.warning("No LLM provider available for post-TTS condensation. Retaining current audio.")
            result = DurationReconciliationResult(
                locale=current_script.locale,
                target_duration_seconds=target_duration_seconds,
                tolerance_seconds=tol_sec,
                initial_duration_seconds=initial_dur,
                final_duration_seconds=measured_total,
                revisions_attempted=0,
                max_revisions=max_rev,
                is_approved=False,
                status="needs_review",
                message=f"Duration overrun (+{diff:.2f}s) but no LLM provider configured for condensation.",
            )
            return current_script, measured_audio_track, result

        working_script = current_script.model_copy(deep=True)
        working_audio_track = measured_audio_track
        current_measured = measured_total
        revision_count = 0

        while revision_count < max_rev:
            revision_count += 1
            if current_measured <= 0.0 or target_duration_seconds <= 0.0:
                logger.warning(
                    "Post-TTS duration revision %d aborted for '%s': non-positive duration (measured=%.2fs, target=%.1fs)",
                    revision_count,
                    working_script.locale,
                    current_measured,
                    target_duration_seconds,
                )
                break

            current_diff = abs(current_measured - target_duration_seconds)
            compression_ratio = max(0.5, min(1.0, (target_duration_seconds / current_measured) if current_measured > 0 else 1.0))

            logger.warning(
                "Post-TTS duration revision %d/%d for '%s': measured=%.2fs vs target=%.1fs (compression_ratio=%.3f)",
                revision_count,
                max_rev,
                working_script.locale,
                current_measured,
                target_duration_seconds,
                compression_ratio,
            )

            # Extract per-scene measured durations
            audio_items = getattr(working_audio_track, "scene_audio", None) or getattr(working_audio_track, "scene_audios", [])
            scene_durations = {sa.scene_id: sa.duration_seconds for sa in audio_items}

            # Allocate deterministic scene budgets
            scene_budgets = allocate_scene_duration_budgets(
                scenes=working_script.scenes,
                scene_durations=scene_durations,
                target_total_seconds=target_duration_seconds,
            )

            prompt = build_duration_condensation_prompt(
                current_script=working_script,
                measured_total_seconds=current_measured,
                target_duration_seconds=target_duration_seconds,
                compression_ratio=compression_ratio,
                scene_budgets=scene_budgets,
            )

            try:
                raw_revised = self.llm_provider.generate_structured(
                    prompt=prompt,
                    schema=LocalizedScript,
                    system_prompt=SYSTEM_PROMPT_POST_TTS_DURATION_REVISER,
                )

                # Merge shortened narration while strictly preserving scene structure
                condensed_script = working_script.model_copy(deep=True)
                condensed_script.target_duration_seconds = target_duration_seconds

                if len(raw_revised.scenes) == len(working_script.scenes):
                    for idx, src_s in enumerate(working_script.scenes):
                        rev_s = raw_revised.scenes[idx]
                        condensed_script.scenes[idx].scene_id = src_s.scene_id
                        condensed_script.scenes[idx].order = src_s.order
                        condensed_script.scenes[idx].scene_type = src_s.scene_type
                        condensed_script.scenes[idx].learning_objective_ids = src_s.learning_objective_ids

                        if rev_s.narration and rev_s.narration.strip():
                            condensed_script.scenes[idx].narration = rev_s.narration.strip()
                        if rev_s.title:
                            condensed_script.scenes[idx].title = rev_s.title
                        if rev_s.purpose:
                            condensed_script.scenes[idx].purpose = rev_s.purpose
                        if rev_s.visual_direction:
                            condensed_script.scenes[idx].visual_direction = rev_s.visual_direction
                        if src_s.on_screen_text is None:
                            condensed_script.scenes[idx].on_screen_text = None
                        elif rev_s.on_screen_text:
                            condensed_script.scenes[idx].on_screen_text = rev_s.on_screen_text

                        est_dur = estimate_narration_duration_seconds(
                            condensed_script.scenes[idx].narration,
                            locale=working_script.locale,
                        )
                        condensed_script.scenes[idx].estimated_duration_seconds = est_dur

                    condensed_script.total_estimated_duration_seconds = sum(
                        s.estimated_duration_seconds for s in condensed_script.scenes
                    )
                else:
                    logger.warning(
                        "LLM revision produced scene count mismatch (%d vs %d); aborting further revisions.",
                        len(raw_revised.scenes),
                        len(working_script.scenes),
                    )
                    break

                # Re-synthesize audio for revised script
                logger.info("Re-synthesizing TTS audio for revised script (Revision %d)...", revision_count)
                new_track = tts_service.synthesize_locale(
                    script=condensed_script,
                    project_id=project_id,
                    force_regenerate=True,
                )
                tts_service.update_script_with_actual_durations(condensed_script, new_track)

                new_measured = getattr(new_track, "total_audio_duration_seconds", None) or getattr(new_track, "total_duration_seconds", 0.0)

                attempt = DurationRevisionAttempt(
                    revision_number=revision_count,
                    measured_duration_before=current_measured,
                    estimated_duration_after=condensed_script.total_estimated_duration_seconds,
                    measured_duration_after=new_measured,
                    compression_ratio=compression_ratio,
                    delta_seconds=round(abs(new_measured - target_duration_seconds), 2),
                )
                history.append(attempt)

                working_script = condensed_script
                working_audio_track = new_track
                current_measured = new_measured

                # Check if now within tolerance
                if abs(current_measured - target_duration_seconds) <= tol_sec:
                    logger.info(
                        "Duration approved at revision %d: measured=%.2fs is within ±%.2fs of target %.1fs",
                        revision_count,
                        current_measured,
                        tol_sec,
                        target_duration_seconds,
                    )
                    result = DurationReconciliationResult(
                        locale=working_script.locale,
                        target_duration_seconds=target_duration_seconds,
                        tolerance_seconds=tol_sec,
                        initial_duration_seconds=initial_dur,
                        final_duration_seconds=current_measured,
                        revisions_attempted=revision_count,
                        max_revisions=max_rev,
                        is_approved=True,
                        status="approved",
                        history=history,
                        scene_budgets=scene_budgets,
                        message=f"Duration reconciled and approved at revision {revision_count}: {current_measured:.2f}s (target: {target_duration_seconds:.1f}s)",
                    )
                    return working_script, working_audio_track, result

            except Exception as e:
                logger.error("Duration condensation failed at revision %d: %s", revision_count, str(e))
                break

        # Revisions exhausted or aborted; evaluate final state
        final_diff = abs(current_measured - target_duration_seconds)
        approved = final_diff <= tol_sec
        final_status = "approved" if approved else "needs_review"
        msg = (
            f"Reconciliation completed in {revision_count} revisions: final={current_measured:.2f}s vs target={target_duration_seconds:.1f}s "
            f"({'approved' if approved else 'needs_review: diff ' + str(round(final_diff, 2)) + 's > ' + str(tol_sec) + 's'})"
        )

        result = DurationReconciliationResult(
            locale=working_script.locale,
            target_duration_seconds=target_duration_seconds,
            tolerance_seconds=tol_sec,
            initial_duration_seconds=initial_dur,
            final_duration_seconds=current_measured,
            revisions_attempted=revision_count,
            max_revisions=max_rev,
            is_approved=approved,
            status=final_status,
            history=history,
            scene_budgets=scene_budgets if 'scene_budgets' in locals() else [],
            message=msg,
        )
        return working_script, working_audio_track, result
