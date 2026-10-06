"""Prompt templates and utilities for educational video script generation."""

from typing import Optional, List

SYSTEM_PROMPT_EDUCATIONAL_SCRIPT = (
    "You are a world-class instructional designer and educational scriptwriter. "
    "Your objective is to produce concise, highly engaging, modular video scripts designed for "
    "AI avatar presentations with supporting visuals and clear narration.\n"
    "Guidelines:\n"
    "- Write conversational, clear, and professional spoken narration.\n"
    "- Break content into distinct, logical scenes (intro, core concepts, practical examples, summary/outro).\n"
    "- Provide clear visual descriptions for each scene that an AI or video editor can interpret.\n"
    "- Estimate the spoken narration duration realistically (average 130-150 words per minute).\n"
    "- Always output valid, parseable JSON conforming to the requested schema."
)


def build_script_generation_prompt(
    topic: str,
    target_audience: str = "General Professional / Adult Learner",
    duration_minutes: int = 2,
    learning_objectives: Optional[List[str]] = None,
    language: str = "en-US"
) -> str:
    """Build the user prompt requesting an instructional script in JSON format."""
    objectives_clause = ""
    if learning_objectives:
        formatted_objs = "\n".join(f"- {obj}" for obj in learning_objectives)
        objectives_clause = f"\nSpecific Learning Objectives:\n{formatted_objs}\n"

    target_total_seconds = duration_minutes * 60

    return (
        f"Create an educational training video script on the following topic:\n"
        f"Topic: {topic}\n"
        f"Target Audience: {target_audience}\n"
        f"Language Code: {language}\n"
        f"Target Total Duration: ~{target_total_seconds} seconds ({duration_minutes} minutes)\n"
        f"{objectives_clause}\n"
        f"Format your response as a JSON object with this exact structure:\n"
        f"{{\n"
        f'  "title": "Module Title",\n'
        f'  "target_audience": "{target_audience}",\n'
        f'  "language": "{language}",\n'
        f'  "scenes": [\n'
        f"    {{\n"
        f'      "scene_number": 1,\n'
        f'      "title": "Scene Title",\n'
        f'      "narration": "Exact text to be spoken by the presenter...",\n'
        f'      "visual_description": "Description of background, diagram, or text overlay...",\n'
        f'      "estimated_duration_seconds": 15\n'
        f"    }}\n"
        f"  ],\n"
        f'  "total_estimated_duration_seconds": {target_total_seconds}\n'
        f"}}\n"
    )
