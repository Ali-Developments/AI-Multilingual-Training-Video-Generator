"""Deterministic validation and structure normalization for localized scripts."""

from typing import List, Optional
from app.core.config import settings
from app.models.schemas import (
    FinalScript,
    LocalizedScript,
    ValidationIssue,
    LocalizationValidationResult,
)
from app.workflows.script_generation.validators import estimate_narration_duration_seconds
from app.services.localization.locale_utils import (
    normalize_locale,
    get_text_direction,
)


def normalize_localized_structure_and_durations(
    localized_script: LocalizedScript,
    source_script: FinalScript,
    target_locale: str,
    text_direction: str,
    words_per_minute: Optional[int] = None,
) -> LocalizedScript:
    """
    Deterministically restore protected structural fields from canonical source script
    and recalculate speech timing from localized narration.
    
    Protected fields restored:
    - scene_id
    - order
    - scene_type
    - learning_objective_ids
    - None-value preservation on on_screen_text
    - learning_objective IDs
    """
    wpm = words_per_minute or settings.SCRIPT_WORDS_PER_MINUTE
    norm_locale = normalize_locale(target_locale)

    # 1. Protect structural metadata at script root
    localized_script.source_language = source_script.language
    localized_script.locale = norm_locale
    localized_script.text_direction = text_direction
    localized_script.target_duration_seconds = source_script.target_duration_seconds

    # 2. Synchronize learning objectives: protect LO IDs
    if len(localized_script.learning_objectives) == len(source_script.learning_objectives):
        for idx, src_lo in enumerate(source_script.learning_objectives):
            localized_script.learning_objectives[idx].id = src_lo.id
    elif not localized_script.learning_objectives and source_script.learning_objectives:
        # Restore source LOs if LLM omitted them
        localized_script.learning_objectives = [
            lo.model_copy(deep=True) for lo in source_script.learning_objectives
        ]

    # 3. Synchronize scenes and restore protected fields if counts align
    if len(localized_script.scenes) == len(source_script.scenes):
        for idx, src_scene in enumerate(source_script.scenes):
            loc_scene = localized_script.scenes[idx]
            # Enforce immutable structural identifiers from source
            loc_scene.scene_id = src_scene.scene_id
            loc_scene.order = src_scene.order
            loc_scene.scene_type = src_scene.scene_type
            loc_scene.learning_objective_ids = list(src_scene.learning_objective_ids)

            # Preserve None on_screen_text from source
            if src_scene.on_screen_text is None:
                loc_scene.on_screen_text = None

            # Recalculate duration deterministically from localized narration word count
            loc_scene.estimated_duration_seconds = estimate_narration_duration_seconds(
                loc_scene.narration, words_per_minute=wpm
            )

    # 4. Total estimated duration strictly equals the sum of scene durations
    localized_script.total_estimated_duration_seconds = sum(
        s.estimated_duration_seconds for s in localized_script.scenes
    )

    # 5. Normalize cultural guidance locale if present
    if localized_script.cultural_guidance:
        localized_script.cultural_guidance.locale = norm_locale

    return localized_script


def validate_localized_script(
    localized_script: LocalizedScript,
    source_script: FinalScript,
    target_locale: str,
    tolerance_percent: Optional[int] = None,
    words_per_minute: Optional[int] = None,
) -> LocalizationValidationResult:
    """
    Perform deterministic validation on a localized educational script.
    
    Verifies:
    A. Structure (scene count, scene IDs, scene order, scene types)
    B. Completeness (title, hook, summary, narration, visual direction)
    C. Learning Objectives (all source IDs present, no unknown IDs, non-empty descriptions)
    D. On-screen text (None preserved, no whitespace-only strings)
    E. Timing (durations recalculated, target tolerance checked)
    F. Locale & Direction (matches normalized target and direction)
    G. Non-vendor guidance (no HeyGen or avatar IDs in cultural metadata)
    """
    tolerance = tolerance_percent if tolerance_percent is not None else settings.SCRIPT_DURATION_TOLERANCE_PERCENT
    wpm = words_per_minute or settings.SCRIPT_WORDS_PER_MINUTE
    norm_locale = normalize_locale(target_locale)
    expected_direction = get_text_direction(norm_locale)

    issues: List[ValidationIssue] = []

    # 1. Structure Normalization & Timing Recalculation
    normalize_localized_structure_and_durations(
        localized_script=localized_script,
        source_script=source_script,
        target_locale=norm_locale,
        text_direction=expected_direction,
        words_per_minute=wpm,
    )

    # 2. Scene Count Preservation
    if len(localized_script.scenes) != len(source_script.scenes):
        issues.append(
            ValidationIssue(
                code="LOCALIZATION_SCENE_COUNT_MISMATCH",
                severity="error",
                message=(
                    f"Localized scene count ({len(localized_script.scenes)}) does not match "
                    f"canonical source scene count ({len(source_script.scenes)})."
                ),
            )
        )
        return LocalizationValidationResult(
            is_valid=False,
            issues=issues,
            estimated_total_duration_seconds=localized_script.total_estimated_duration_seconds,
            duration_difference_seconds=localized_script.total_estimated_duration_seconds - source_script.target_duration_seconds,
            duration_difference_percent=round(
                (abs(localized_script.total_estimated_duration_seconds - source_script.target_duration_seconds) / source_script.target_duration_seconds) * 100,
                2
            ) if source_script.target_duration_seconds > 0 else 0.0,
        )

    # 3. Scene Alignment Checks
    for idx, (loc_s, src_s) in enumerate(zip(localized_script.scenes, source_script.scenes)):
        if loc_s.scene_id != src_s.scene_id:
            issues.append(
                ValidationIssue(
                    code="SCENE_ID_MISMATCH",
                    severity="error",
                    message=f"Scene {idx + 1} ID '{loc_s.scene_id}' does not match source ID '{src_s.scene_id}'.",
                    scene_id=loc_s.scene_id,
                )
            )

        if loc_s.order != src_s.order:
            issues.append(
                ValidationIssue(
                    code="SCENE_ORDER_MISMATCH",
                    severity="error",
                    message=f"Scene {loc_s.scene_id} order ({loc_s.order}) does not match source order ({src_s.order}).",
                    scene_id=loc_s.scene_id,
                )
            )

        if loc_s.scene_type != src_s.scene_type:
            issues.append(
                ValidationIssue(
                    code="SCENE_TYPE_MISMATCH",
                    severity="error",
                    message=f"Scene {loc_s.scene_id} scene_type '{loc_s.scene_type}' does not match source '{src_s.scene_type}'.",
                    scene_id=loc_s.scene_id,
                )
            )

        # Narration completeness
        if not loc_s.narration or not loc_s.narration.strip():
            issues.append(
                ValidationIssue(
                    code="MISSING_LOCALIZED_NARRATION",
                    severity="error",
                    message=f"Scene {loc_s.scene_id} narration is missing or empty.",
                    scene_id=loc_s.scene_id,
                )
            )

        # Visual direction completeness
        if not loc_s.visual_direction or not loc_s.visual_direction.strip():
            issues.append(
                ValidationIssue(
                    code="MISSING_LOCALIZED_VISUAL_DIRECTION",
                    severity="error",
                    message=f"Scene {loc_s.scene_id} visual direction guidance is missing or empty.",
                    scene_id=loc_s.scene_id,
                )
            )

        # On-screen text validation (whitespace-only is invalid)
        if loc_s.on_screen_text is not None and not loc_s.on_screen_text.strip():
            issues.append(
                ValidationIssue(
                    code="WHITESPACE_ON_SCREEN_TEXT",
                    severity="error",
                    message=f"Scene {loc_s.scene_id} on_screen_text contains only whitespace.",
                    scene_id=loc_s.scene_id,
                )
            )

    # 4. Root Script Completeness Checks
    if not localized_script.title or not localized_script.title.strip():
        issues.append(
            ValidationIssue(
                code="MISSING_LOCALIZED_TITLE",
                severity="error",
                message="Localized script title is missing or empty.",
            )
        )

    if not localized_script.opening_hook or not localized_script.opening_hook.strip():
        issues.append(
            ValidationIssue(
                code="MISSING_LOCALIZED_OPENING_HOOK",
                severity="error",
                message="Localized script opening hook is missing or empty.",
            )
        )

    if not localized_script.closing_summary or not localized_script.closing_summary.strip():
        issues.append(
            ValidationIssue(
                code="MISSING_LOCALIZED_CLOSING_SUMMARY",
                severity="error",
                message="Localized script closing summary is missing or empty.",
            )
        )

    # 5. Learning Objectives Verification
    src_lo_ids = {lo.id for lo in source_script.learning_objectives}
    loc_lo_ids = {lo.id for lo in localized_script.learning_objectives}

    missing_los = src_lo_ids - loc_lo_ids
    if missing_los:
        issues.append(
            ValidationIssue(
                code="MISSING_LEARNING_OBJECTIVE",
                severity="error",
                message=f"Source learning objective(s) missing from localized script: {sorted(list(missing_los))}",
            )
        )

    unknown_los = loc_lo_ids - src_lo_ids
    if unknown_los:
        issues.append(
            ValidationIssue(
                code="UNKNOWN_LEARNING_OBJECTIVE",
                severity="error",
                message=f"Unknown learning objective ID(s) introduced in localized script: {sorted(list(unknown_los))}",
            )
        )

    for lo in localized_script.learning_objectives:
        if not lo.description or not lo.description.strip():
            issues.append(
                ValidationIssue(
                    code="EMPTY_OBJECTIVE_DESCRIPTION",
                    severity="error",
                    message=f"Localized description for learning objective '{lo.id}' is empty.",
                )
            )

    # 6. Timing and Duration Tolerance
    target_sec = source_script.target_duration_seconds
    total_est = localized_script.total_estimated_duration_seconds
    diff_sec = total_est - target_sec
    diff_pct = (abs(diff_sec) / target_sec * 100) if target_sec > 0 else 0.0

    if diff_pct > tolerance:
        if diff_sec > 0:
            issues.append(
                ValidationIssue(
                    code="LOCALIZED_DURATION_TOO_LONG",
                    severity="error",
                    message=(
                        f"Localized spoken duration ({total_est}s) exceeds target ({target_sec}s) "
                        f"by {diff_pct:.1f}% (allowed tolerance: {tolerance}%)."
                    ),
                )
            )
        else:
            issues.append(
                ValidationIssue(
                    code="LOCALIZED_DURATION_TOO_SHORT",
                    severity="error",
                    message=(
                        f"Localized spoken duration ({total_est}s) is shorter than target ({target_sec}s) "
                        f"by {diff_pct:.1f}% (allowed tolerance: {tolerance}%)."
                    ),
                )
            )

    # 7. Locale and Text Direction Checks
    if localized_script.locale != norm_locale:
        issues.append(
            ValidationIssue(
                code="LOCALE_MISMATCH",
                severity="error",
                message=f"Script locale '{localized_script.locale}' does not match expected '{norm_locale}'.",
            )
        )

    if localized_script.text_direction != expected_direction:
        issues.append(
            ValidationIssue(
                code="TEXT_DIRECTION_MISMATCH",
                severity="error",
                message=f"Script text direction '{localized_script.text_direction}' does not match expected '{expected_direction}'.",
            )
        )

    # 8. Check Cultural Guidance for forbidden vendor parameters
    if localized_script.cultural_guidance:
        cg_text = localized_script.cultural_guidance.model_dump_json().lower()
        for forbidden in ["heygen", "avatar_id", "voice_id"]:
            if forbidden in cg_text:
                issues.append(
                    ValidationIssue(
                        code="VENDOR_ID_LEAK",
                        severity="error",
                        message=f"Cultural guidance metadata must not include vendor-specific ID '{forbidden}'.",
                    )
                )

    has_errors = any(i.severity == "error" for i in issues)

    return LocalizationValidationResult(
        is_valid=not has_errors,
        issues=issues,
        estimated_total_duration_seconds=total_est,
        duration_difference_seconds=diff_sec,
        duration_difference_percent=round(diff_pct, 2),
    )
