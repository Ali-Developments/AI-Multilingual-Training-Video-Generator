"""Instructional prompt templates for script generation workflow nodes."""

from typing import Optional
from app.models.schemas import TrainingVideoRequest, ContentAnalysis, ScriptDraft, ScriptValidationResult

SYSTEM_PROMPT_CONTENT_ANALYZER = (
    "You are an expert instructional designer and curriculum architect. "
    "Your objective is to analyze educational topics or source materials and create a structured "
    "pedagogical analysis blueprint for video production.\n"
    "Guidelines:\n"
    "- Assign stable, clean IDs to learning objectives (e.g., 'LO1', 'LO2', 'LO3').\n"
    "- Identify critical domain terminology that must remain precise.\n"
    "- Recommend a logical scene count and structure suited to the target duration.\n"
    "- Output valid JSON matching the ContentAnalysis schema."
)

SYSTEM_PROMPT_SCRIPT_WRITER = (
    "You are a master educational video scriptwriter. "
    "Your objective is to produce engaging, modular, video-ready scripts for an AI presenter "
    "with supporting visual guidance, camera/motion directions, and on-screen text.\n"
    "Pedagogical & Structural Guidelines:\n"
    "- Complete Objective Coverage: 100% of the defined learning objectives MUST be addressed. Every single objective must be taught in at least one instructional scene.\n"
    "- Meaningful Instruction: Teach each objective through substantive spoken narration and concrete visual direction. Avoid generic filler scenes that do not contribute to educational outcomes.\n"
    "- Objective Tagging: Explicitly assign the correct learning objective IDs (e.g. ['LO1']) to the scenes that teach them. Multiple objectives may be legitimately assigned to a single scene when conceptually unified.\n"
    "- Conversational & Concise: Write natural, engaging spoken narration suited to the target audience and tone.\n"
    "- Clear Visual & Motion Direction: Provide concrete guidance for graphics, diagrams, slides, cinematic B-roll, or demonstrations (as text metadata), including subject dynamics and camera movement (e.g. static, slow zoom-in, pan right, tracking).\n"
    "- Scene Composition: Select appropriate scene types (intro, presenter, explanation, visual_demo, example, recap, outro, quiz) and include concise on-screen text overlays when helpful.\n"
    "- Deterministic Pacing: Match the target duration closely based on ~140 words per minute (~2.3 words/second)."
)

SYSTEM_PROMPT_SCRIPT_REVISER = (
    "You are a master educational quality assurance editor for instructional video scripts. "
    "Your task is to fix specific defects identified by the automated validation layer, "
    "including uncovered learning objectives, duration discrepancies, and scene integrity defects.\n"
    "Revision Rules:\n"
    "- Objective Remediation: When learning objectives are uncovered, you must substantively teach them by adding new scenes or expanding relevant existing scenes with targeted narration and visual direction. Never simply attach missing objective IDs to unrelated scenes without updating narration.\n"
    "- Preserve Compliant Content: Keep valid, compliant scenes intact to maintain pedagogical and narrative continuity.\n"
    "- Complete Coverage: Ensure 100% of required learning objectives are represented in scene learning_objective_ids.\n"
    "- Duration Calibration: Adjust spoken narration word counts (~140 WPM) so total runtime matches the target duration."
)


def build_content_analysis_prompt(request: TrainingVideoRequest) -> str:
    """Build the prompt for pedagogical content analysis."""
    content_clause = ""
    if request.topic:
        content_clause += f"Topic: {request.topic}\n"
    if request.source_content:
        content_clause += f"Source Material / Outline:\n{request.source_content}\n"

    objectives_clause = ""
    if request.learning_objectives:
        formatted = "\n".join(f"- {o}" for o in request.learning_objectives)
        objectives_clause = f"User Requested Objectives:\n{formatted}\n"

    target_mins = round(request.target_duration_seconds / 60, 1)

    return (
        f"Perform an instructional design analysis for an educational video with the following requirements:\n"
        f"{content_clause}"
        f"Target Audience: {request.audience}\n"
        f"Base Language: {request.base_language}\n"
        f"Target Total Duration: {request.target_duration_seconds} seconds (~{target_mins} minutes)\n"
        f"Desired Tone: {request.tone}\n"
        f"Difficulty Level: {request.difficulty_level or 'intermediate'}\n"
        f"{objectives_clause}\n"
        f"Analyze this material and generate a structured ContentAnalysis blueprint. "
        f"Ensure every learning objective is assigned a clean ID (LO1, LO2, etc.)."
    )


def build_workflow_script_prompt(request: TrainingVideoRequest, analysis: ContentAnalysis) -> str:
    """Build the prompt to draft a complete video-ready script."""
    objectives_list = "\n".join(f"- [{lo.id}] {lo.description}" for lo in analysis.learning_objectives)
    all_obj_ids = [lo.id for lo in analysis.learning_objectives]
    obj_ids_formatted = ", ".join(f"'{oid}'" for oid in all_obj_ids)
    key_terms = ", ".join(analysis.important_terms) if analysis.important_terms else "None specified"
    structure = " -> ".join(analysis.recommended_structure) if analysis.recommended_structure else "Standard progression"

    coverage_instructions = (
        f"MANDATORY LEARNING OBJECTIVES COVERAGE:\n"
        f"Every learning objective listed below MUST be covered by at least one instructional scene:\n"
        f"{objectives_list}\n\n"
        f"Coverage Requirements:\n"
        f"1. Complete Coverage: Across all scenes, every objective ID in [{obj_ids_formatted}] must be assigned to at least one scene's 'learning_objective_ids'. Do NOT omit any objective.\n"
        f"2. Meaningful Instruction: Ensure each objective is genuinely taught through substantive spoken narration and concrete visual direction. Avoid generating generic scenes that do not contribute to educational outcomes.\n"
        f"3. Multi-Objective Scenes: A single scene may legitimately cover multiple objectives when conceptually unified (e.g. learning_objective_ids=['LO1', 'LO2']).\n"
        f"4. Valid IDs Only: Only use valid IDs from [{obj_ids_formatted}]. Do not reference unknown or hallucinated objective IDs."
    )

    return (
        f"Generate a canonical, scene-by-scene instructional video script based on the following analysis:\n\n"
        f"Topic Summary: {analysis.topic_summary}\n"
        f"Target Audience: {request.audience}\n"
        f"Tone: {request.tone}\n"
        f"Language: {request.base_language}\n"
        f"Target Total Duration: {request.target_duration_seconds} seconds\n"
        f"Recommended Scene Count: {analysis.recommended_scene_count}\n"
        f"Recommended Structure: {structure}\n"
        f"Key Terminology to Preserve: {key_terms}\n\n"
        f"{coverage_instructions}\n\n"
        f"For each scene, provide:\n"
        f"- scene_id (e.g. 'scene_1', 'scene_2')\n"
        f"- order (1, 2, ...)\n"
        f"- title\n"
        f"- purpose\n"
        f"- scene_type (intro, presenter, explanation, visual_demo, example, recap, outro, quiz)\n"
        f"- narration (clear spoken presenter script)\n"
        f"- visual_direction (instructional visual guide text)\n"
        f"- motion_description (cinematic camera or subject movement guidance)\n"
        f"- camera_movement (e.g. 'static', 'slow zoom-in', 'pan right', 'tracking')\n"
        f"- on_screen_text (optional short text overlay)\n"
        f"- learning_objective_ids (subset of [{obj_ids_formatted}])\n"
        f"- estimated_duration_seconds\n"
    )

def build_script_revision_prompt(
    request: TrainingVideoRequest,
    analysis: ContentAnalysis,
    current_script: ScriptDraft,
    validation: ScriptValidationResult
) -> str:
    """Build the prompt to revise a script draft addressing validation defects."""
    from app.workflows.script_generation.validators import assess_learning_objective_coverage

    issues_text = "\n".join(
        f"- [{issue.code}] (Scene: {issue.scene_id or 'General'}) {issue.message}"
        for issue in validation.issues
    )

    # Use existing coverage report or compute deterministically
    cov_rep = validation.coverage_report or assess_learning_objective_coverage(current_script, analysis)

    remediation_blocks = []
    if cov_rep and cov_rep.get("uncovered_objectives"):
        for uncov in cov_rep["uncovered_objectives"]:
            remediation_blocks.append(
                f"  * Uncovered Objective ID: '{uncov['id']}'\n"
                f"    Full Description: {uncov['description']}\n"
                f"    Action Required: Add a dedicated scene or expand a relevant existing scene with meaningful spoken narration "
                f"and visual direction that directly teaches this objective, and assign '{uncov['id']}' to that scene's learning_objective_ids."
            )

    objective_remediation_guidance = ""
    if remediation_blocks:
        objective_remediation_guidance = (
            f"\nTARGETED LEARNING OBJECTIVE REMEDIATION:\n"
            f"The following required learning objective(s) are NOT addressed in any scene:\n"
            + "\n".join(remediation_blocks) +
            f"\n\nCRITICAL REMEDIATION RULES:\n"
            f"- You MUST provide substantive instructional content (narration and visual direction) for every missing objective.\n"
            f"- Do NOT simply attach missing objective IDs to arbitrary scenes without teaching the concepts in narration.\n"
            f"- Preserve valid existing scenes whenever possible to maintain script coherence.\n"
        )

    # Existing scenes and their assigned objectives
    scene_breakdown_lines = []
    for s in current_script.scenes:
        obj_tags = ", ".join(f"'{oid}'" for oid in s.learning_objective_ids) if s.learning_objective_ids else "None"
        scene_breakdown_lines.append(
            f"  - Scene {s.order} ('{s.scene_id}'): \"{s.title}\" [{s.scene_type}, ~{s.estimated_duration_seconds}s] "
            f"-> Assigned Objectives: [{obj_tags}]"
        )
    existing_scenes_text = "\n".join(scene_breakdown_lines) if scene_breakdown_lines else "  No scenes present."

    # Canonical objectives reference
    canonical_objectives_text = "\n".join(
        f"  - [{lo.id}] {lo.description}" for lo in analysis.learning_objectives
    ) if analysis and analysis.learning_objectives else "  None specified."

    duration_guidance = ""
    target_words = round((request.target_duration_seconds / 60) * 140)
    if validation.duration_difference_seconds < -5:
        duration_guidance = (
            f"\nDURATION GUIDANCE: The narration is TOO SHORT by {abs(validation.duration_difference_seconds)} seconds. "
            f"You MUST EXPAND the spoken narration across scenes with deeper explanations, clear practical examples, and richer phrasing "
            f"to reach approximately {target_words} total words (~{request.target_duration_seconds} seconds).\n"
        )
    elif validation.duration_difference_seconds > 5:
        duration_guidance = (
            f"\nDURATION GUIDANCE: The narration is TOO LONG by {validation.duration_difference_seconds} seconds. "
            f"You MUST SHORTEN, condense, and tighten the spoken narration across scenes "
            f"to reach approximately {target_words} total words (~{request.target_duration_seconds} seconds).\n"
        )

    return (
        f"The current script draft failed automated quality validation with the following issues:\n"
        f"{issues_text}\n\n"
        f"Current Script Summary:\n"
        f"Title: {current_script.title}\n"
        f"Target Duration: {request.target_duration_seconds}s | Current Estimate: {validation.estimated_total_duration_seconds}s "
        f"(Deviation: {validation.duration_difference_seconds}s / {validation.duration_difference_percent:.1f}%)\n"
        f"{duration_guidance}\n"
        f"{objective_remediation_guidance}\n"
        f"Existing Scenes & Assigned Objectives:\n"
        f"{existing_scenes_text}\n\n"
        f"Canonical Learning Objectives Reference:\n"
        f"{canonical_objectives_text}\n\n"
        f"REVISION INSTRUCTIONS:\n"
        f"1. Preserve valid existing scenes whenever possible.\n"
        f"2. Add or improve instructional content (spoken narration and visual direction) addressing each missing objective.\n"
        f"3. Spoken durations are calculated deterministically from your narration word count (~140 WPM). "
        f"Do NOT simply alter numeric duration numbers; you MUST adjust the actual text length and word count of the spoken narration.\n"
        f"4. Please repair and regenerate the complete ScriptDraft so that all validation issues are resolved. "
        f"Ensure non-empty opening_hook, valid opening scene, and 100% learning objective coverage."
    )
