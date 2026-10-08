"""Verification Script for Phase 37: Saudi Kabsa Preparation Basics Storyboard Demo.

Validates that StoryboardPlanner and Script Generation generalize to culinary/procedural
topics with sensible presenter and demonstration/B-roll allocation rather than PPT slides.
"""

import sys
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.models.schemas import TrainingVideoRequest, VideoStyle
from app.services.llm.groq_provider import GroqProvider
from app.workflows.manifest import ProjectManifestManager
from app.workflows.storyboard_planner import StoryboardPlanner
from app.workflows.script_generation import create_script_workflow
from app.workflows.orchestrator import ProjectOrchestrator
from app.services.localization.service import LocalizationService
from app.services.tts.service import TTSService
from app.services.avatar.mock_avatar_provider import MockAvatarProvider
from app.services.avatar.service import AvatarService
from app.services.visuals.service import VisualService
from app.services.subtitles.service import SubtitleService
from app.services.composition.service import CompositionService
from app.services.composition.ffmpeg_provider import FFmpegCompositionProvider

def main():
    print("=" * 70)
    print("RUNNING PHASE 37: SAUDI KABSA STORYBOARD DEMO")
    print("=" * 70)

    project_id = "proj_kabsa_storyboard_demo"
    manifest_mgr = ProjectManifestManager()
    groq_llm = GroqProvider()
    
    # 1. Initialize orchestrator (audio/video not required for storyboard-only test)
    orchestrator = ProjectOrchestrator(
        manifest_manager=manifest_mgr,
        llm_provider=groq_llm,
        localization_service=LocalizationService(llm_provider=groq_llm),
        tts_service=TTSService(),
        avatar_service=AvatarService(provider=MockAvatarProvider()),
        visual_service=VisualService(),
        subtitle_service=SubtitleService(),
        composition_service=CompositionService(provider=FFmpegCompositionProvider()),
    )

    req = TrainingVideoRequest(
        topic="Saudi Kabsa Preparation Basics",
        source_content="""
        Welcome to traditional Saudi Kabsa preparation.
        First, prepare long-grain basmati rice by washing and soaking.
        Next, sauté chopped onions in ghee until golden brown, then brown the chicken pieces.
        Add the authentic Kabsa whole spices: cardamom, cloves, cinnamon sticks, dried black lime (loomi), and tomato puree.
        Simmer the chicken in rich fragrant broth until tender.
        Add the drained rice directly into the seasoned chicken broth and simmer on low heat.
        Garnish the beautifully cooked rice with toasted almonds and raisins, serving the golden chicken on top.
        Enjoy your authentic Saudi Kabsa with spicy daqqoos sauce.
        """.strip(),
        audience="New culinary students and home cooks",
        base_language="en-US",
        target_languages=["ar-SA"],
        target_duration_seconds=45.0,
        video_style=VideoStyle.DEMONSTRATION_TUTORIAL,
    )

    print(f"Generating canonical script and storyboard for: {req.topic}")
    manifest = orchestrator.create_project(req, project_id=project_id)
    workflow = create_script_workflow(llm_provider=groq_llm)
    state = workflow.invoke({"request": req})
    final_script = state.get("final_script")
    if not final_script and state.get("draft_script"):
        from app.models.schemas import FinalScript
        draft = state.get("draft_script")
        final_script = FinalScript(
            title=draft.title,
            language=draft.language,
            audience=draft.audience,
            target_duration_seconds=req.target_duration_seconds,
            total_estimated_duration_seconds=draft.total_estimated_duration_seconds,
            opening_hook=draft.opening_hook,
            closing_summary=draft.closing_summary,
            learning_objectives=draft.learning_objectives or [],
            scenes=draft.scenes,
        )
    assert final_script is not None, "Script workflow failed to produce final script or draft"
    
    StoryboardPlanner.plan_storyboard(final_script, req)
    manifest.final_script = final_script
    manifest_mgr.save_manifest(manifest)
    scenes = final_script.scenes
    print(f"\nGenerated {len(scenes)} Scenes for Demonstration/Tutorial Style:")
    print("-" * 70)
    
    def get_val(val):
        return val.value if hasattr(val, "value") else str(val)

    media_counts = {}
    for sc in scenes:
        mt_val = get_val(sc.media_type)
        lo_val = get_val(sc.layout_type)
        media_counts[mt_val] = media_counts.get(mt_val, 0) + 1
        print(f"Scene {sc.order:02d} | [{sc.scene_type:10s}] | Media: {mt_val:15s} | Layout: {lo_val:18s} | Avatar: {str(sc.avatar_enabled):5s}")
        print(f"         Prompt: {sc.visual_prompt[:60]}...")
        if sc.media_search_terms:
            print(f"         Terms:  {', '.join(sc.media_search_terms)}")
        print()

    # Validate culinary demonstration allocation
    assert len(scenes) >= 4, "Expected at least 4 planned scenes"
    assert get_val(scenes[0].media_type) in ["presenter", "title"], "First scene should be presenter or title intro"
    
    # Verify B-roll / media / motion visual presence for process scenes
    body_scenes = scenes[1:-1]
    has_broll_or_media = any(get_val(s.media_type) in ["broll", "motion_visual", "uploaded_video", "uploaded_image"] for s in body_scenes)
    print("-" * 70)
    print(f"Summary Media Breakdown: {json.dumps(media_counts, indent=2)}")
    print(f"Has Action/B-Roll/Motion Media in Body: {has_broll_or_media}")
    assert has_broll_or_media, "Expected B-roll or motion visual scenes in culinary demonstration"
    print("\nPHASE 37 KABSA DEMO: SUCCESSFUL! Planner prioritized demonstration media scenes over slides.")
    print("=" * 70)

if __name__ == "__main__":
    main()
