"""Staged structured script generation and targeted scene-level repair pipeline.

Designed to make `ScriptDraft` generation reliable on smaller and free models
(e.g., `openrouter/free`, `nvidia/nemotron-3.5-super-vl:free`, `recursive/flint-v1.0:free`)
that frequently hit output token limits (`finish_reason='length'`) or emit placeholder
ellipses (`{...}`, `[...]`) when asked to generate a multi-scene `ScriptDraft` in one call.

Pipeline Stages:
- Stage 1 (Script Outline): Generate a compact `ScriptOutline` (title, language, hooks, scene summaries).
- Stage 2 (Scene Generation): Generate each `SceneDraft` independently with a compact schema & word-count budget.
- Stage 3 (Assembly): Combine the outline and generated scenes into a complete `ScriptDraft` with V2 media plans.
- Stage 4 (Validation): Validate the assembled `ScriptDraft` using Pydantic and `validate_script_draft`.
- Stage 5 (Targeted Repair): Regenerate only the specific scene(s) that failed validation or duration calibration.
"""

from typing import Dict, List, Optional, Set
from app.core import language as language_checks
from app.core.logging import logger
from app.models.schemas import (
    ContentAnalysis,
    LearningObjective,
    SceneDraft,
    SceneOutlineItem,
    ScriptDraft,
    ScriptOutline,
    ScriptValidationResult,
    TrainingVideoRequest,
)
from app.services.llm.base import LLMProvider
from app.services.localization.locale_utils import get_language_name
from app.workflows.script_generation.prompts import (
    SYSTEM_PROMPT_SCRIPT_REVISER,
    SYSTEM_PROMPT_SCRIPT_WRITER,
)
from app.workflows.script_generation.validators import (
    LocaleDurationEstimator,
    estimate_narration_duration_seconds,
    normalize_script_durations,
    validate_script_draft,
)


def _allocate_scene_durations(total_duration_seconds: int, scene_count: int) -> List[int]:
    """Deterministically distribute `total_duration_seconds` across `scene_count` scenes."""
    count = max(1, scene_count)
    base, extra = divmod(total_duration_seconds, count)
    return [base + int(index < extra) for index in range(count)]


def _scene_count(request: TrainingVideoRequest, analysis: ContentAnalysis) -> int:
    return max(1, min(analysis.recommended_scene_count or 4, 8, request.target_duration_seconds // 4))


def _outline_issue(outline: ScriptOutline, count: int, language: str) -> Optional[str]:
    if len(outline.scene_outlines) != count:
        return f"Expected exactly {count} outline scenes."
    fields = [outline.title, outline.opening_hook, outline.closing_summary]
    for item in outline.scene_outlines:
        fields.extend((item.title, item.purpose))
    for field in fields:
        valid, reason = language_checks.verify_output_language(field, language)
        if not field.strip() or not valid:
            return reason or "Outline contains an empty title, hook, summary or scene purpose."
    return None


def _normalize_and_repair_outline(
    outline: ScriptOutline,
    request: TrainingVideoRequest,
    analysis: ContentAnalysis,
) -> ScriptOutline:
    """
    Deterministically enforce structural invariants on a Stage 1 `ScriptOutline`:
    - Canonical language code (`request.base_language`)
    - Canonical `learning_objectives` from `ContentAnalysis`
    - Sequential `scene_1..scene_N` IDs and `order = 1..N`
    - Opening scene `scene_type` is never 'outro' or 'recap'
    - 100% of `analysis.learning_objectives` IDs are assigned across `scene_outlines`
    - Scene `target_duration_seconds` sum to `request.target_duration_seconds`
    """
    canonical_lang = request.base_language or "en-US"
    outline.language = canonical_lang
    if analysis.learning_objectives:
        outline.learning_objectives = list(analysis.learning_objectives)

    valid_obj_ids = [lo.id for lo in (analysis.learning_objectives or [])]
    valid_obj_set = set(valid_obj_ids)

    n_scenes = len(outline.scene_outlines)
    allocated_durations = _allocate_scene_durations(request.target_duration_seconds, n_scenes)

    covered_ids: Set[str] = set()
    for idx, item in enumerate(outline.scene_outlines, start=1):
        item.order = idx
        item.scene_id = f"scene_{idx}"
        item.target_duration_seconds = allocated_durations[idx - 1]
        if idx == 1 and (item.scene_type or "").lower() not in ("presenter", "intro"):
            item.scene_type = "intro"
        filtered_ids = [oid for oid in (item.learning_objective_ids or []) if oid in valid_obj_set]
        item.learning_objective_ids = filtered_ids
        covered_ids.update(filtered_ids)

    # Ensure every required learning objective is assigned to at least one scene
    missing_ids = [oid for oid in valid_obj_ids if oid not in covered_ids]
    for m_idx, oid in enumerate(missing_ids):
        target_scene = outline.scene_outlines[m_idx % n_scenes]
        if oid not in target_scene.learning_objective_ids:
            target_scene.learning_objective_ids.append(oid)

    return outline


def build_stage1_outline_prompt(request: TrainingVideoRequest, analysis: ContentAnalysis) -> str:
    """Build a compact prompt for Stage 1 (`ScriptOutline`)."""
    canonical_lang = request.base_language or "en-US"
    canonical_lang_name = get_language_name(canonical_lang)
    scene_count = _scene_count(request, analysis)
    allocated = _allocate_scene_durations(request.target_duration_seconds, scene_count)

    objectives_list = "\n".join(
        f"- [{lo.id}] {lo.description}" for lo in (analysis.learning_objectives or [])
    )
    all_obj_ids = [lo.id for lo in (analysis.learning_objectives or [])]
    structure_str = " -> ".join(analysis.recommended_structure or []) or "Intro -> Demonstration -> Summary"
    source_excerpt = (request.source_content or "").strip()
    if len(source_excerpt) > 1500:
        source_excerpt = source_excerpt[:1500]

    return (
        f"Create a compact Stage 1 ScriptOutline in {canonical_lang_name} ('{canonical_lang}') "
        f"for an instructional training video.\n\n"
        f"Topic: {request.topic or analysis.topic_summary}\n"
        f"Topic Summary: {analysis.topic_summary}\n"
        f"Target Audience: {request.audience}\n"
        f"Tone: {request.tone}\n"
        f"Canonical Output Language: {canonical_lang} ({canonical_lang_name})\n"
        f"Target Total Duration: {request.target_duration_seconds} seconds\n"
        f"Target Scene Count: {scene_count} scenes (durations: {allocated})\n"
        f"Recommended Narrative Structure: {structure_str}\n"
        f"Source Material Context:\n{source_excerpt or 'Use topic summary and learning objectives.'}\n\n"
        f"Learning Objectives to Cover Across Scenes ({all_obj_ids}):\n{objectives_list}\n\n"
        f"REQUIREMENTS:\n"
        f"1. Write 'title', 'audience', 'opening_hook', 'closing_summary', and every scene outline's 'title' and 'purpose' "
        f"strictly in {canonical_lang_name} ('{canonical_lang}').\n"
        f"2. Include exactly {scene_count} items in 'scene_outlines' with sequential IDs 'scene_1'..'scene_{scene_count}'.\n"
        f"3. Assign every objective ID in {all_obj_ids} to at least one scene's 'learning_objective_ids'.\n"
        f"4. Scene 1 must have scene_type 'intro' or 'presenter' (never 'outro' or 'recap')."
    )


def build_stage2_scene_prompt(
    request: TrainingVideoRequest,
    analysis: ContentAnalysis,
    outline: ScriptOutline,
    scene_item: SceneOutlineItem,
    previous_scenes: List[SceneDraft],
    extra_repair_guidance: Optional[str] = None,
) -> str:
    """Build a focused prompt to generate a single `SceneDraft` in Stage 2 (or Stage 5 repair)."""
    canonical_lang = request.base_language or "en-US"
    canonical_lang_name = get_language_name(canonical_lang)
    wpm = LocaleDurationEstimator.get_wpm_for_locale(canonical_lang)
    target_dur = max(4, scene_item.target_duration_seconds)
    target_words = max(6, round((target_dur / 60.0) * wpm))
    min_words = max(4, round(target_words * 0.85))
    max_words = max(min_words + 3, round(target_words * 1.15))

    obj_map = {lo.id: lo.description for lo in (analysis.learning_objectives or [])}
    assigned_objs_text = "\n".join(
        f"- [{oid}] {obj_map.get(oid, '')}" for oid in scene_item.learning_objective_ids
    ) or "- General instructional progression"

    outline_overview = "\n".join(
        f"  {it.order}. [{it.scene_id}] {it.title} ({it.scene_type}, ~{it.target_duration_seconds}s)"
        for it in outline.scene_outlines
    )

    prev_context = "None (this is the opening scene)."
    if previous_scenes:
        last_sc = previous_scenes[-1]
        prev_context = f"Previous Scene ({last_sc.scene_id} - {last_sc.title}): \"{last_sc.narration}\""

    source_excerpt = (request.source_content or "").strip()
    if len(source_excerpt) > 1200:
        source_excerpt = source_excerpt[:1200]

    repair_block = f"\nSPECIFIC CORRECTION REQUIRED:\n{extra_repair_guidance}\n" if extra_repair_guidance else ""

    return (
        f"Generate ONLY Scene {scene_item.order} ('{scene_item.scene_id}') as a single `SceneDraft` JSON object "
        f"written strictly in {canonical_lang_name} ('{canonical_lang}').\n\n"
        f"VIDEO CONTEXT:\n"
        f"- Video Title: {outline.title}\n"
        f"- Canonical Language: {canonical_lang} ({canonical_lang_name})\n"
        f"- Audience: {outline.audience}\n"
        f"- Full Video Scene Plan:\n{outline_overview}\n"
        f"- Source Material Reference:\n{source_excerpt or analysis.topic_summary}\n"
        f"- {prev_context}\n\n"
        f"TARGET SCENE SPECIFICATION:\n"
        f"- scene_id: '{scene_item.scene_id}'\n"
        f"- order: {scene_item.order}\n"
        f"- title: '{scene_item.title}' (in {canonical_lang_name})\n"
        f"- purpose: '{scene_item.purpose}'\n"
        f"- scene_type: '{scene_item.scene_type}'\n"
        f"- learning_objective_ids: {scene_item.learning_objective_ids}\n"
        f"  Assigned Objectives to Teach in This Scene:\n{assigned_objs_text}\n\n"
        f"MANDATORY NARRATION & VISUAL REQUIREMENTS:\n"
        f"1. Write 'title', 'purpose', 'narration', 'visual_direction', and 'on_screen_text' strictly in {canonical_lang_name} ('{canonical_lang}').\n"
        f"2. Spoken Duration Budget: Target {target_dur} seconds (~{wpm} words/minute in {canonical_lang_name}). "
        f"Write approximately {target_words} words (between {min_words} and {max_words} words) of natural, fluent spoken narration.\n"
        f"3. Provide concrete 'visual_direction' (what viewers see on screen) and 'motion_description' / 'camera_movement'.\n"
        f"4. Provide a concise 'on_screen_text' overlay in {canonical_lang_name} (or null).\n"
        f"{repair_block}"
    )


def _sanitize_and_align_scene(
    scene: SceneDraft,
    scene_item: SceneOutlineItem,
    valid_obj_set: Set[str],
    language: str,
) -> SceneDraft:
    """Enforce deterministic scene identity, objective IDs, on_screen_text, and WPM duration."""
    scene.order = scene_item.order
    scene.scene_id = scene_item.scene_id
    scene.scene_number = scene_item.order

    if scene_item.order == 1 and (scene.scene_type or "").lower() not in ("presenter", "intro"):
        scene.scene_type = "intro"
    elif not scene.scene_type:
        scene.scene_type = scene_item.scene_type or "presenter"

    # Preserve required objective IDs from outline and strip any unknown IDs
    merged_ids: List[str] = []
    for oid in list(scene_item.learning_objective_ids) + list(scene.learning_objective_ids or []):
        if oid in valid_obj_set and oid not in merged_ids:
            merged_ids.append(oid)
    scene.learning_objective_ids = merged_ids

    if scene.on_screen_text is not None and not scene.on_screen_text.strip():
        scene.on_screen_text = None

    if not scene.visual_direction or not scene.visual_direction.strip():
        scene.visual_direction = scene.visual_description or scene.purpose or scene.title

    scene.estimated_duration_seconds = estimate_narration_duration_seconds(
        narration=scene.narration,
        language=language,
    )
    return SceneDraft.model_validate(scene.model_dump())


class StagedScriptGenerator:
    """
    Executes the 5-stage structured script generation and targeted scene repair pipeline.
    """

    def __init__(self, llm_provider: LLMProvider, checkpoint=None) -> None:
        self.llm_provider = llm_provider
        self.checkpoint = checkpoint

    def generate_script_draft(
        self,
        request: TrainingVideoRequest,
        analysis: ContentAnalysis,
    ) -> ScriptDraft:
        """
        Execute Stages 1 -> 5 to produce a complete, validated `ScriptDraft`.
        """
        canonical_lang = request.base_language or "en-US"
        canonical_lang_name = get_language_name(canonical_lang)
        valid_obj_set = {lo.id for lo in (analysis.learning_objectives or [])}

        # ===================================================================
        # Stage 1: Script Outline Generation
        # ===================================================================
        logger.info(
            "Staged Script Generation [Stage 1/5]: Generating ScriptOutline (model: %s, lang: %s)",
            self.llm_provider.model_name,
            canonical_lang,
        )
        outline_prompt = build_stage1_outline_prompt(request, analysis)
        outline = self.checkpoint.get("outline", ScriptOutline) if self.checkpoint else None
        if outline is None:
            if self.checkpoint:
                self.checkpoint.event("outline", "generation", "running")
            outline = self.llm_provider.generate_structured(
                prompt=outline_prompt,
                schema=ScriptOutline,
                system_prompt=SYSTEM_PROMPT_SCRIPT_WRITER,
                temperature=0.2,
                max_tokens=2048,
            )

            # Verify outline language compliance (bounded 1-call language correction if needed)
            expected_count = _scene_count(request, analysis)
            lang_err = _outline_issue(outline, expected_count, canonical_lang)
            if lang_err:
                if self.checkpoint:
                    self.checkpoint.event("outline", "language_repair", "running")
                logger.warning(
                    "Stage 1 ScriptOutline language mismatch (%s). Executing bounded language correction into %s.",
                    lang_err,
                    canonical_lang_name,
                )
                outline = self.llm_provider.generate_structured(
                    prompt=(
                        f"{outline_prompt}\n\n"
                        f"Correct this outline issue: {lang_err} Rewrite ALL fields ('title', 'opening_hook', "
                        f"'closing_summary', and scene titles/purposes) strictly in {canonical_lang_name} ('{canonical_lang}')."
                    ),
                    schema=ScriptOutline,
                    system_prompt=SYSTEM_PROMPT_SCRIPT_WRITER,
                    temperature=0.1,
                    max_tokens=2048,
                )
                remaining_issue = _outline_issue(outline, expected_count, canonical_lang)
                if remaining_issue:
                    raise ValueError(f"ScriptOutline failed correction. {remaining_issue}")

            outline = _normalize_and_repair_outline(outline, request, analysis)
            if self.checkpoint:
                self.checkpoint.put("outline", outline)

        # ===================================================================
        # Stage 2: Independent Scene Generation
        # ===================================================================
        generated_scenes: List[SceneDraft] = []
        total_scenes = len(outline.scene_outlines)
        if self.checkpoint:
            self.checkpoint.pending([item.scene_id for item in outline.scene_outlines])
        pending_repairs = self.checkpoint.pending_repair_tasks() if self.checkpoint else {}
        for scene_item in outline.scene_outlines:
            logger.info(
                "Staged Script Generation [Stage 2/5]: Generating scene %d/%d ('%s', target=%ds)",
                scene_item.order,
                total_scenes,
                scene_item.scene_id,
                scene_item.target_duration_seconds,
            )
            scene_draft = self.checkpoint.get(scene_item.scene_id, SceneDraft) if self.checkpoint else None
            if scene_draft is None:
                saved_task = pending_repairs.get(scene_item.scene_id) or {}
                saved_guidance = saved_task.get("guidance") if isinstance(saved_task, dict) else None
                scene_draft = self._generate_single_scene_with_targeted_repair(
                    request=request,
                    analysis=analysis,
                    outline=outline,
                    scene_item=scene_item,
                    previous_scenes=generated_scenes,
                    valid_obj_set=valid_obj_set,
                    extra_repair_guidance=saved_guidance,
                )
            generated_scenes.append(scene_draft)

        # ===================================================================
        # Stage 3: Assembly into Complete ScriptDraft
        # ===================================================================
        logger.info("Staged Script Generation [Stage 3/5]: Assembling complete ScriptDraft (%d scenes)", len(generated_scenes))
        script_draft = ScriptDraft(
            title=outline.title,
            language=canonical_lang,
            audience=outline.audience or request.audience,
            learning_objectives=list(analysis.learning_objectives or outline.learning_objectives),
            opening_hook=outline.opening_hook,
            closing_summary=outline.closing_summary,
            scenes=generated_scenes,
        )
        normalize_script_durations(script_draft, language=canonical_lang)

        # ===================================================================
        # Stage 4 & Stage 5: Validation & Targeted Scene-Level Repair
        # ===================================================================
        validation = validate_script_draft(
            script=script_draft,
            target_duration_seconds=request.target_duration_seconds,
            analysis=analysis,
            language=canonical_lang,
        )
        if not validation.is_valid:
            logger.info(
                "Staged Script Generation [Stage 5/5]: Executing targeted scene repair for %d validation issue(s).",
                len(validation.issues),
            )
            script_draft = self.repair_targeted_scenes(
                request=request,
                analysis=analysis,
                script_draft=script_draft,
                validation=validation,
                outline=outline,
            )

        return script_draft

    def _generate_single_scene_with_targeted_repair(
        self,
        request: TrainingVideoRequest,
        analysis: ContentAnalysis,
        outline: ScriptOutline,
        scene_item: SceneOutlineItem,
        previous_scenes: List[SceneDraft],
        valid_obj_set: Set[str],
        extra_repair_guidance: Optional[str] = None,
    ) -> SceneDraft:
        """Generate a single `SceneDraft` and perform at most 1 targeted scene repair if narration/language is invalid."""
        canonical_lang = request.base_language or "en-US"
        canonical_lang_name = get_language_name(canonical_lang)

        scene_prompt = build_stage2_scene_prompt(
            request=request,
            analysis=analysis,
            outline=outline,
            scene_item=scene_item,
            previous_scenes=previous_scenes,
            extra_repair_guidance=extra_repair_guidance,
        )
        if self.checkpoint:
            self.checkpoint.event(scene_item.scene_id, "targeted_repair" if extra_repair_guidance else "generation", "running")
        scene = self.llm_provider.generate_structured(
            prompt=scene_prompt,
            schema=SceneDraft,
            system_prompt=SYSTEM_PROMPT_SCRIPT_WRITER,
            temperature=0.25,
            max_tokens=1536,
        )
        scene = _sanitize_and_align_scene(scene, scene_item, valid_obj_set, canonical_lang)

        # Check scene-level narration language & completeness
        lang_ok, lang_err = language_checks.verify_output_language(scene.narration, canonical_lang)
        if not lang_ok or not scene.narration.strip() or not scene.visual_direction.strip():
            logger.warning(
                "Scene '%s' failed initial language/content check (%s). Regenerating only scene '%s'.",
                scene_item.scene_id,
                lang_err or "empty narration/visual_direction",
                scene_item.scene_id,
            )
            repaired_scene_prompt = build_stage2_scene_prompt(
                request=request,
                analysis=analysis,
                outline=outline,
                scene_item=scene_item,
                previous_scenes=previous_scenes,
                extra_repair_guidance=(
                    f"Your previous output for scene '{scene_item.scene_id}' was invalid ({lang_err or 'missing narration'}). "
                    f"Write non-empty 'title', 'narration', and 'visual_direction' strictly in {canonical_lang_name} ('{canonical_lang}')."
                ),
            )
            if self.checkpoint:
                self.checkpoint.event(scene_item.scene_id, "language_repair", "running")
            scene = self.llm_provider.generate_structured(
                prompt=repaired_scene_prompt,
                schema=SceneDraft,
                system_prompt=SYSTEM_PROMPT_SCRIPT_REVISER,
                temperature=0.15,
                max_tokens=1536,
            )
            scene = _sanitize_and_align_scene(scene, scene_item, valid_obj_set, canonical_lang)
            lang_ok, _ = language_checks.verify_output_language(scene.narration, canonical_lang)
            if not lang_ok or not scene.narration.strip() or not scene.visual_direction.strip():
                raise ValueError(f"SceneDraft {scene_item.scene_id} still lacks usable {canonical_lang} narration or visuals.")

        if self.checkpoint:
            self.checkpoint.put(scene_item.scene_id, scene)
        return scene

    def repair_targeted_scenes(
        self,
        request: TrainingVideoRequest,
        analysis: ContentAnalysis,
        script_draft: ScriptDraft,
        validation: ScriptValidationResult,
        outline: Optional[ScriptOutline] = None,
    ) -> ScriptDraft:
        """
        Stage 5 — Targeted Scene-Level Repair:
        Instead of regenerating the entire multi-scene `ScriptDraft` (which causes token truncation on free models),
        identify and regenerate ONLY the specific scene(s) responsible for validation or duration issues.
        """
        canonical_lang = request.base_language or script_draft.language or "en-US"
        canonical_lang_name = get_language_name(canonical_lang)
        valid_obj_set = {lo.id for lo in (analysis.learning_objectives or [])}
        wpm = LocaleDurationEstimator.get_wpm_for_locale(canonical_lang)

        if outline is None:
            allocated = _allocate_scene_durations(request.target_duration_seconds, len(script_draft.scenes))
            outline = ScriptOutline(
                title=script_draft.title,
                language=canonical_lang,
                audience=script_draft.audience or request.audience,
                opening_hook=script_draft.opening_hook or script_draft.title,
                closing_summary=script_draft.closing_summary or script_draft.title,
                learning_objectives=list(analysis.learning_objectives or script_draft.learning_objectives),
                scene_outlines=[
                    SceneOutlineItem(
                        scene_id=s.scene_id,
                        order=s.order,
                        title=s.title,
                        purpose=s.purpose,
                        scene_type=s.scene_type,
                        learning_objective_ids=list(s.learning_objective_ids),
                        target_duration_seconds=allocated[i],
                    )
                    for i, s in enumerate(script_draft.scenes)
                ],
            )
            outline = _normalize_and_repair_outline(outline, request, analysis)

        # Ensure opening_hook is non-empty
        if not script_draft.opening_hook or not script_draft.opening_hook.strip():
            script_draft.opening_hook = outline.opening_hook or script_draft.title

        # Map scene_id -> SceneOutlineItem and repair instructions
        outline_by_id: Dict[str, SceneOutlineItem] = {it.scene_id: it for it in outline.scene_outlines}
        scenes_to_repair: Dict[str, List[str]] = {}

        # 1. Scene-specific validation issues
        for issue in validation.issues:
            if issue.scene_id and issue.scene_id in outline_by_id:
                scenes_to_repair.setdefault(issue.scene_id, []).append(f"[{issue.code}] {issue.message}")
            elif issue.code == "SCRIPT_LANGUAGE_MISMATCH":
                # Check which individual scenes failed language verification
                for s in script_draft.scenes:
                    s_ok, s_err = language_checks.verify_output_language(f"{s.title} {s.narration}", canonical_lang)
                    if not s_ok:
                        scenes_to_repair.setdefault(s.scene_id, []).append(
                            f"Rewrite this scene's title, narration, and visual_direction strictly in {canonical_lang_name} ('{canonical_lang}'): {s_err}"
                        )

        # 2. Uncovered learning objectives: assign to a target scene and mark that scene for regeneration
        cov_rep = validation.coverage_report or {}
        for uncov in cov_rep.get("uncovered_objectives", []):
            oid = uncov["id"]
            odesc = uncov["description"]
            target_sc = script_draft.scenes[-1]
            if oid not in target_sc.learning_objective_ids:
                target_sc.learning_objective_ids.append(oid)
            if target_sc.scene_id in outline_by_id and oid not in outline_by_id[target_sc.scene_id].learning_objective_ids:
                outline_by_id[target_sc.scene_id].learning_objective_ids.append(oid)
            scenes_to_repair.setdefault(target_sc.scene_id, []).append(
                f"Substantively teach learning objective [{oid}] ({odesc}) in this scene's narration and visual_direction."
            )

        # 3. Duration out of tolerance: adjust the 1-2 scenes with the largest duration gap
        has_duration_issue = any(i.code == "DURATION_OUT_OF_TOLERANCE" for i in validation.issues)
        if has_duration_issue and script_draft.scenes:
            diff_seconds = request.target_duration_seconds - script_draft.total_estimated_duration_seconds
            # Rank scenes by how far they are from their outline target duration
            scored_scenes = sorted(
                script_draft.scenes,
                key=lambda s: (
                    (outline_by_id[s.scene_id].target_duration_seconds - s.estimated_duration_seconds)
                    if diff_seconds > 0
                    else (s.estimated_duration_seconds - outline_by_id[s.scene_id].target_duration_seconds)
                ),
                reverse=True,
            )
            # Adjust at most 2 scenes to keep API calls bounded
            target_adjust_scenes = scored_scenes[: min(2, len(scored_scenes))]
            per_scene_delta = diff_seconds / len(target_adjust_scenes)
            for sc in target_adjust_scenes:
                new_target_dur = max(4, round(sc.estimated_duration_seconds + per_scene_delta))
                new_target_words = max(6, round((new_target_dur / 60.0) * wpm))
                outline_by_id[sc.scene_id].target_duration_seconds = new_target_dur
                action_word = "EXPAND" if diff_seconds > 0 else "SHORTEN"
                scenes_to_repair.setdefault(sc.scene_id, []).append(
                    f"DURATION CALIBRATION: {action_word} the spoken narration for this scene to approximately "
                    f"{new_target_words} words (~{new_target_dur} seconds at {wpm} WPM in {canonical_lang_name}). "
                    f"Current scene narration has {len(sc.narration.split())} words ({sc.estimated_duration_seconds}s)."
                )

        # Persist pending repair tasks BEFORE regenerating any scene so interruptions never fall back to stale scenes
        if self.checkpoint and scenes_to_repair:
            for sc_id, issue_msgs in scenes_to_repair.items():
                if sc_id in outline_by_id:
                    self.checkpoint.begin_repair(
                        sc_id,
                        outline_by_id[sc_id],
                        "\n".join(f"- {msg}" for msg in issue_msgs),
                    )

        # Regenerate only the flagged scenes (bounded to at most len(scenes) calls, typically 1-2)
        updated_scenes: List[SceneDraft] = []
        for sc in script_draft.scenes:
            if sc.scene_id in scenes_to_repair:
                scene_item = outline_by_id[sc.scene_id]
                guidance = "\n".join(f"- {msg}" for msg in scenes_to_repair[sc.scene_id])
                logger.info(
                    "Targeted Scene Repair: Regenerating scene '%s' (order=%d) for %d issue(s).",
                    sc.scene_id,
                    sc.order,
                    len(scenes_to_repair[sc.scene_id]),
                )
                repaired_sc = self._generate_single_scene_with_targeted_repair(
                    request=request,
                    analysis=analysis,
                    outline=outline,
                    scene_item=scene_item,
                    previous_scenes=updated_scenes,
                    valid_obj_set=valid_obj_set,
                    extra_repair_guidance=guidance,
                )
                updated_scenes.append(repaired_sc)
            else:
                updated_scenes.append(sc)

        script_draft.scenes = updated_scenes
        if analysis.learning_objectives:
            script_draft.learning_objectives = list(analysis.learning_objectives)
        normalize_script_durations(script_draft, language=canonical_lang)
        return script_draft

