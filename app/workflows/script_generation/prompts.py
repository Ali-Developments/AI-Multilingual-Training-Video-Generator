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
    "with supporting visual guidance and on-screen text.\n"
    "Guidelines:\n"
    "- Write conversational, concise spoken narration.\n"
    "- Keep each scene focused on a single instructional idea.\n"
    "- Explicitly tag each scene with the learning objective IDs it fulfills (e.g. ['LO1']).\n"
    "- Provide clear visual direction describing graphics, slides, or animations (as text metadata).\n"
    "- Include relevant on-screen text overlays (key bullet, title, diagram label).\n"
    "- Choose appropriate scene types (intro, presenter, explanation, visual_demo, example, recap, outro).\n"
    "- Estimate spoken narration duration realistically (~140 words per minute).\n"
    "- Match the target video duration closely."
)

SYSTEM_PROMPT_SCRIPT_REVISER = (
    "You are a quality assurance editor for instructional video scripts. "
    "Your task is to fix specific defects identified by the automated validation layer, "
    "such as missing narration, duration discrepancies, or unaddressed learning objectives.\n"
    "Keep compliant scenes intact and repair only what is flagged in the validation report."
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
    objectives_text = "\n".join(f"- [{lo.id}] {lo.description}" for lo in analysis.learning_objectives)
    key_terms = ", ".join(analysis.important_terms) if analysis.important_terms else "None specified"
    structure = " -> ".join(analysis.recommended_structure) if analysis.recommended_structure else "Standard progression"

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
        f"Learning Objectives (must all be addressed in scene learning_objective_ids):\n"
        f"{objectives_text}\n\n"
        f"For each scene, provide:\n"
        f"- scene_id (e.g. 'scene_1', 'scene_2')\n"
        f"- order (1, 2, ...)\n"
        f"- title\n"
        f"- purpose\n"
        f"- scene_type (intro, presenter, explanation, visual_demo, example, recap, outro)\n"
        f"- narration (clear spoken presenter script)\n"
        f"- visual_direction (instructional visual guide text)\n"
        f"- on_screen_text (optional short text overlay)\n"
        f"- learning_objective_ids (subset of [{', '.join(lo.id for lo in analysis.learning_objectives)}])\n"
        f"- estimated_duration_seconds\n"
    )

def build_script_revision_prompt(
    request: TrainingVideoRequest,
    analysis: ContentAnalysis,
    current_script: ScriptDraft,
    validation: ScriptValidationResult
) -> str:
    """Build the prompt to revise a script draft addressing validation defects."""
    issues_text = "\n".join(
        f"- [{issue.code}] (Scene: {issue.scene_id or 'General'}) {issue.message}"
        for issue in validation.issues
    )

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
        f"IMPORTANT: Spoken durations are calculated deterministically from your narration word count (~140 WPM). "
        f"Do NOT simply alter numeric duration numbers; you MUST adjust the actual text length and word count of the spoken narration.\n\n"
        f"Please repair and regenerate the complete ScriptDraft so that all validation issues are resolved. "
        f"Ensure non-empty opening_hook, valid opening scene, and full learning objective coverage."
    )
