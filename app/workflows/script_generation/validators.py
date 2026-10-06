"""Deterministic validation rules for video script drafts.

Performs rule-based checks on duration, structure, scene data, and learning objective coverage
without consuming LLM tokens.
"""

from typing import List, Optional
import math

from app.core.config import settings
from app.models.schemas import (
    ScriptDraft,
    ContentAnalysis,
    ValidationIssue,
    ScriptValidationResult,
)


def estimate_narration_duration_seconds(
    narration: str,
    words_per_minute: Optional[int] = None
) -> int:
    """
    Estimate spoken narration duration in seconds based on word count.
    
    Formula: max(2, round((len(narration.split()) / wpm) * 60))
    NOTE: This is a pre-TTS estimate. Actual timing will be determined by
    the TTS provider in Step 5.
    """
    wpm = words_per_minute or settings.SCRIPT_WORDS_PER_MINUTE
    words = len(narration.split())
    if words == 0:
        return 0
    return max(2, round((words / wpm) * 60))


def normalize_script_durations(
    script: ScriptDraft,
    words_per_minute: Optional[int] = None
) -> ScriptDraft:
    """
    Deterministically recalculate and normalize estimated_duration_seconds for each scene
    from its narration word count, eliminating LLM-hallucinated duration figures.
    
    Also recalculates total_estimated_duration_seconds as the strict sum of scene durations.
    """
    wpm = words_per_minute or settings.SCRIPT_WORDS_PER_MINUTE
    for scene in script.scenes:
        scene.estimated_duration_seconds = estimate_narration_duration_seconds(scene.narration, wpm)
    script.total_estimated_duration_seconds = sum(s.estimated_duration_seconds for s in script.scenes)
    return script


def validate_script_draft(
    script: ScriptDraft,
    target_duration_seconds: int,
    analysis: Optional[ContentAnalysis] = None,
    tolerance_percent: Optional[int] = None,
    words_per_minute: Optional[int] = None
) -> ScriptValidationResult:
    """
    Perform deterministic validation on a generated script draft.
    
    Args:
        script: The candidate ScriptDraft to validate.
        target_duration_seconds: Target video length in seconds.
        analysis: Pedagogical analysis against which objective coverage is verified.
        tolerance_percent: Maximum allowable duration deviation percentage.
        words_per_minute: Optional speech rate override for narration estimation.
    """
    tolerance = tolerance_percent if tolerance_percent is not None else settings.SCRIPT_DURATION_TOLERANCE_PERCENT
    wpm = words_per_minute or settings.SCRIPT_WORDS_PER_MINUTE
    issues: List[ValidationIssue] = []

    # 1. Normalize scene durations deterministically before validation
    normalize_script_durations(script, words_per_minute=wpm)

    # 2. Basic Scene Presence
    if not script.scenes:
        issues.append(
            ValidationIssue(
                code="NO_SCENES",
                severity="error",
                message="Script draft contains zero scenes."
            )
        )
        return ScriptValidationResult(
            is_valid=False,
            issues=issues,
            estimated_total_duration_seconds=0,
            duration_difference_seconds=-target_duration_seconds,
            duration_difference_percent=100.0
        )

    # 3. Opening Hook Check
    if not script.opening_hook or not script.opening_hook.strip():
        issues.append(
            ValidationIssue(
                code="MISSING_OPENING_HOOK",
                severity="error",
                message="Script is missing a non-empty opening_hook statement to engage the learner."
            )
        )

    # 4. Opening Scene Structural Type Check
    if script.scenes and script.scenes[0].scene_type in ["outro", "recap"]:
        issues.append(
            ValidationIssue(
                code="INVALID_OPENING_SCENE",
                severity="error",
                message=f"Opening scene '{script.scenes[0].scene_id}' cannot have scene_type '{script.scenes[0].scene_type}'.",
                scene_id=script.scenes[0].scene_id
            )
        )

    # 5. Scene Uniqueness, Order, and Content Integrity
    seen_ids = set()
    for idx, scene in enumerate(script.scenes, start=1):
        # Unique Scene ID
        if scene.scene_id in seen_ids:
            issues.append(
                ValidationIssue(
                    code="DUPLICATE_SCENE_ID",
                    severity="error",
                    message=f"Duplicate scene_id '{scene.scene_id}' detected.",
                    scene_id=scene.scene_id
                )
            )
        seen_ids.add(scene.scene_id)

        # Scene Order Check
        if scene.order != idx:
            issues.append(
                ValidationIssue(
                    code="INVALID_SCENE_ORDER",
                    severity="error",
                    message=f"Scene '{scene.scene_id}' has order {scene.order}, expected sequential order {idx}.",
                    scene_id=scene.scene_id
                )
            )

        # Scene Narration Quality
        if not scene.narration or not scene.narration.strip():
            issues.append(
                ValidationIssue(
                    code="MISSING_NARRATION",
                    severity="error",
                    message=f"Scene '{scene.scene_id}' has empty narration.",
                    scene_id=scene.scene_id
                )
            )

        # Scene Visual Direction
        if not scene.visual_direction or not scene.visual_direction.strip():
            issues.append(
                ValidationIssue(
                    code="MISSING_VISUAL_DIRECTION",
                    severity="error",
                    message=f"Scene '{scene.scene_id}' has empty visual_direction guidance.",
                    scene_id=scene.scene_id
                )
            )

        # Duration Integrity
        if scene.estimated_duration_seconds <= 0:
            issues.append(
                ValidationIssue(
                    code="INVALID_DURATION",
                    severity="error",
                    message=f"Scene '{scene.scene_id}' has non-positive duration ({scene.estimated_duration_seconds}s).",
                    scene_id=scene.scene_id
                )
            )

        # Check for malformed on_screen_text (whitespace-only when provided)
        if scene.on_screen_text is not None and not scene.on_screen_text.strip():
            issues.append(
                ValidationIssue(
                    code="MALFORMED_ON_SCREEN_TEXT",
                    severity="error",
                    message=f"Scene '{scene.scene_id}' contains whitespace-only on_screen_text. Provide text or set to null.",
                    scene_id=scene.scene_id
                )
            )

    # 6. Total Duration Calculation and Tolerance Verification
    estimated_total = script.total_estimated_duration_seconds
    diff_seconds = estimated_total - target_duration_seconds
    diff_percent = (abs(diff_seconds) / target_duration_seconds) * 100 if target_duration_seconds > 0 else 0.0

    if diff_percent > tolerance:
        direction = "longer" if diff_seconds > 0 else "shorter"
        issues.append(
            ValidationIssue(
                code="DURATION_OUT_OF_TOLERANCE",
                severity="error",
                message=(
                    f"Calculated total narration duration ({estimated_total}s) is {abs(diff_seconds)}s {direction} than target ({target_duration_seconds}s), "
                    f"deviating by {diff_percent:.1f}% (exceeds allowable {tolerance}% tolerance limit)."
                )
            )
        )

    # 7. Learning Objectives Coverage Checks
    if analysis and analysis.learning_objectives:
        valid_objective_ids = {lo.id for lo in analysis.learning_objectives}
        covered_objective_ids = set()

        for scene in script.scenes:
            for obj_id in scene.learning_objective_ids:
                if obj_id not in valid_objective_ids:
                    issues.append(
                        ValidationIssue(
                            code="UNKNOWN_OBJECTIVE_ID",
                            severity="error",
                            message=f"Scene '{scene.scene_id}' references unknown learning objective ID '{obj_id}'.",
                            scene_id=scene.scene_id
                        )
                    )
                else:
                    covered_objective_ids.add(obj_id)

        # Check for unrepresented required objectives
        uncovered = valid_objective_ids - covered_objective_ids
        for missing_id in sorted(uncovered):
            issues.append(
                ValidationIssue(
                    code="UNCOVERED_LEARNING_OBJECTIVE",
                    severity="error",
                    message=f"Required learning objective '{missing_id}' is not addressed in any scene."
                )
            )

    # 8. Structural Checks (Outro placement)
    if len(script.scenes) > 1:
        for scene in script.scenes[:-1]:
            if scene.scene_type == "outro":
                issues.append(
                    ValidationIssue(
                        code="OUTRO_PREMATURE",
                        severity="error",
                        message=f"Outro scene '{scene.scene_id}' appears before the end of the script.",
                        scene_id=scene.scene_id
                    )
                )

    has_errors = any(issue.severity == "error" for issue in issues)

    return ScriptValidationResult(
        is_valid=not has_errors,
        issues=issues,
        estimated_total_duration_seconds=estimated_total,
        duration_difference_seconds=diff_seconds,
        duration_difference_percent=round(diff_percent, 2)
    )
