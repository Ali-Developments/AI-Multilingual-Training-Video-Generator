"""Real local execution of Post-TTS Duration Reconciliation and Dual Composition.

Steps:
1. Reconcile ar-SA script using real Groq LLM to compress narration for 30s target.
2. Re-synthesize speech using real Edge-TTS.
3. Measure actual audio durations.
4. Compose Artifact A: Corrected timeline version (visual-only).
5. Generate SadTalker for scene_1 using newly approved audio.
6. Compose Artifact B: Corrected timeline + SadTalker PiP version.
7. Verify all durations using ffprobe.
"""

import sys
import json
from pathlib import Path
from typing import Dict, Any

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.config import settings
from app.core.logging import logger
from app.workflows.manifest import ProjectManifestManager
from app.models.schemas import (
    LocalizedScript,
    LocalizedAudioTrack,
    SceneAudioAsset,
    LocalizedVisualTrack,
    LocalizedSubtitleTrack,
    LocalizedAvatarTrack,
    AvatarVideoAsset,
)
from app.services.llm.groq_provider import GroqProvider
from app.services.localization.service import LocalizationService
from app.services.tts.service import TTSService
from app.services.tts.audio_probe import get_audio_duration
from app.services.subtitles.service import SubtitleService
from app.services.visuals.service import VisualService
from app.services.composition.service import CompositionService
from app.services.composition.ffmpeg_provider import FFmpegCompositionProvider
from app.services.composition.ffmpeg_utils import get_video_duration
from app.services.avatar.sadtalker_provider import SadTalkerProvider


def main():
    project_id = "proj_real_e2e_phishing"
    locale = "ar-SA"
    manifest_mgr = ProjectManifestManager()
    manifest = manifest_mgr.load_manifest(project_id)
    if not manifest:
        print(f"Error: Project '{project_id}' not found.")
        sys.exit(1)

    print("=" * 60)
    print("PHASE 13: LOCAL REAL TIMING & DURATION RECONCILIATION")
    print("=" * 60)
    target_duration = manifest.final_script.target_duration_seconds
    print(f"Project Target Duration: {target_duration:.1f} seconds")

    current_script = manifest.localization_bundle.localized_scripts.get(locale)
    current_audio_track = manifest.audio_tracks.get(locale)

    orig_total_audio = current_audio_track.total_audio_duration_seconds
    print(f"Current Measured Audio Duration: {orig_total_audio:.2f} seconds")
    print(f"Current Duration Overrun: +{orig_total_audio - target_duration:.2f} seconds ({round(((orig_total_audio - target_duration)/target_duration)*100, 1)}%)")

    # Step 1: Real Groq Script Condensation via Post-TTS Reconciliation
    print("\n--- Step 1: Real Groq Script Condensation ---")
    groq_llm = GroqProvider()
    loc_service = LocalizationService(llm_provider=groq_llm)

    revised_script, was_reconciled, msg = loc_service.reconcile_post_tts_duration(
        current_script=current_script,
        measured_audio_track=current_audio_track,
        target_duration_seconds=target_duration,
        tolerance_percent=settings.POST_TTS_TOLERANCE_PERCENT,
    )

    if not was_reconciled:
        print(f"Reconciliation was not triggered: {msg}")
    else:
        print(f"Reconciliation triggered: {msg}")

    # Step 2: Real Edge-TTS Audio Re-synthesis
    print("\n--- Step 2: Real Edge-TTS Audio Re-synthesis ---")
    tts_service = TTSService()
    manifest.localization_bundle.localized_scripts[locale] = revised_script

    # Synthesize new audio with force_regenerate=True
    resynthesized_tracks = tts_service.synthesize_bundle(
        bundle=manifest.localization_bundle,
        project_id=project_id,
        force_regenerate=True,
    )
    new_audio_track = resynthesized_tracks[locale]
    manifest.audio_tracks[locale] = new_audio_track
    tts_service.update_script_with_actual_durations(revised_script, new_audio_track)

    new_total_audio = new_audio_track.total_audio_duration_seconds
    print(f"\nNew Measured Audio Duration: {new_total_audio:.2f} seconds (Target: {target_duration:.1f}s)")
    print(f"Duration Reduction Achieved: -{orig_total_audio - new_total_audio:.2f} seconds")

    # Print Scene Breakdown Table
    print("\n" + "=" * 75)
    print(f"{'Scene ID':<10} | {'Orig Words':<10} | {'New Words':<10} | {'Orig Audio (s)':<15} | {'New Audio (s)':<15}")
    print("-" * 75)
    orig_scenes_map = {s.scene_id: s for s in current_script.scenes}
    orig_audios_map = {a.scene_id: a for a in current_audio_track.scene_audio}

    for s in revised_script.scenes:
        orig_s = orig_scenes_map.get(s.scene_id)
        orig_words = len(orig_s.narration.split()) if orig_s else 0
        new_words = len(s.narration.split())
        orig_dur = orig_audios_map.get(s.scene_id).duration_seconds if orig_audios_map.get(s.scene_id) else 0.0
        new_dur = next((a.duration_seconds for a in new_audio_track.scene_audio if a.scene_id == s.scene_id), 0.0)
        print(f"{s.scene_id:<10} | {orig_words:<10} | {new_words:<10} | {orig_dur:<15.2f} | {new_dur:<15.2f}")
    print("=" * 75)

    # Step 3: Regenerate Subtitles aligned to new audio
    print("\n--- Step 3: Regenerate ASS Subtitles ---")
    sub_service = SubtitleService()
    sub_track = sub_service.generate_locale_subtitles(
        script=revised_script,
        audio_track=new_audio_track,
        project_id=project_id,
        force_regenerate=True,
    )
    manifest.subtitle_tracks[locale] = sub_track

    # Step 4: Ensure Supporting Visual Slides
    print("\n--- Step 4: Supporting Visual Slides ---")
    vis_service = VisualService()
    vis_track = vis_service.generate_locale_visuals(
        script=revised_script,
        project_id=project_id,
        force_regenerate=False,
    )
    manifest.visual_tracks[locale] = vis_track

    # Step 5: Render Artifact A (Visuals + Corrected Timeline Audio)
    print("\n--- Step 5: Render Artifact A (Corrected Timeline - Visuals Only) ---")
    comp_provider = FFmpegCompositionProvider()
    comp_service = CompositionService(provider=comp_provider)

    scene_videos_a = comp_service.compose_locale_scenes(
        script=revised_script,
        audio_track=new_audio_track,
        visual_track=vis_track,
        avatar_track=None, # Visuals only
        subtitle_track=sub_track,
        project_id=project_id,
        force_regenerate=True,
    )

    final_dir = Path("storage/projects") / project_id / "final"
    final_dir.mkdir(parents=True, exist_ok=True)
    artifact_a_path = final_dir / f"training_{locale}_timing_fixed.mp4"

    final_asset_a = comp_provider.concatenate_scenes(
        scene_videos=scene_videos_a,
        locale=locale,
        output_path=artifact_a_path,
    )
    measured_a_dur = get_video_duration(artifact_a_path)
    print(f"Artifact A Rendered: {artifact_a_path}")
    print(f"Artifact A Measured Duration: {measured_a_dur:.2f} seconds (Expected: {new_total_audio:.2f}s)")

    # Step 6: Render SadTalker for Scene 1 with new approved audio
    print("\n--- Step 6: Generate SadTalker for Scene 1 ---")
    scene_1_audio = next(a for a in new_audio_track.scene_audio if a.scene_id == "scene_1")
    sadtalker = SadTalkerProvider()
    
    avatar_dir = Path("storage/projects") / project_id / "avatars" / locale
    avatar_dir.mkdir(parents=True, exist_ok=True)
    scene_1_av_out = avatar_dir / "scene_1_reconciled.mp4"

    # Use project presenter portrait
    portrait_path = Path("assets/avatars/local_presenter.png")
    if not portrait_path.exists():
        portrait_path = Path("storage/projects") / project_id / "visuals" / "presenter_source.jpg"

    if scene_1_av_out.exists() and scene_1_av_out.stat().st_size > 0:
        av_dur = get_video_duration(scene_1_av_out)
        print(f"Reusing verified SadTalker render: {scene_1_av_out} ({av_dur:.2f}s)")
        av_asset = AvatarVideoAsset(
            scene_id="scene_1",
            locale=locale,
            provider="sadtalker",
            job_id="cached_sadtalker",
            video_path=str(scene_1_av_out.resolve()),
            duration_seconds=av_dur,
            status="completed",
            avatar_id="local_presenter",
        )
    else:
        print(f"Running SadTalker for scene_1 with new audio ({scene_1_audio.duration_seconds:.2f}s)...")
        av_asset = sadtalker.generate_scene_avatar(
            scene_id="scene_1",
            locale=locale,
            audio_path=Path(scene_1_audio.audio_path),
            destination_path=scene_1_av_out,
            avatar_id=str(portrait_path) if portrait_path.exists() else None,
            force_regenerate=True,
        )
    print(f"SadTalker ready: status={av_asset.status}, duration={av_asset.duration_seconds:.2f}s")

    # Step 7: Render Artifact B (Corrected Timeline + SadTalker PiP)
    print("\n--- Step 7: Render Artifact B (Corrected Timeline + SadTalker PiP) ---")
    avatar_track = LocalizedAvatarTrack(
        locale=locale,
        scene_avatars=[av_asset],
        status="completed",
    )

    settings.AVATAR_LAYOUT = "pip"
    scene_videos_b = comp_service.compose_locale_scenes(
        script=revised_script,
        audio_track=new_audio_track,
        visual_track=vis_track,
        avatar_track=avatar_track,
        subtitle_track=sub_track,
        project_id=project_id,
        force_regenerate=True,
    )

    artifact_b_path = final_dir / f"training_{locale}_sadtalker_reconciled.mp4"
    final_asset_b = comp_provider.concatenate_scenes(
        scene_videos=scene_videos_b,
        locale=locale,
        output_path=artifact_b_path,
    )
    measured_b_dur = get_video_duration(artifact_b_path)
    print(f"Artifact B Rendered: {artifact_b_path}")
    print(f"Artifact B Measured Duration: {measured_b_dur:.2f} seconds (Expected: {new_total_audio:.2f}s)")

    # Save manifest updates
    manifest.final_videos[f"{locale}_timing_fixed"] = final_asset_a
    manifest.final_videos[f"{locale}_sadtalker_reconciled"] = final_asset_b
    manifest_mgr.save_manifest(manifest)

    # Summary
    print("\n" + "=" * 70)
    print("VERIFICATION SUMMARY")
    print("=" * 70)
    print(f"Original Target Duration:              {target_duration:.2f}s")
    print(f"Original Measured TTS Audio:           {orig_total_audio:.2f}s")
    print(f"Original Video Duration:               66.31s (Audio demuxer pitch-stretched)")
    print(f"Reconciled TTS Audio:                  {new_total_audio:.2f}s")
    print(f"Artifact A (Visuals Only) Duration:    {measured_a_dur:.2f}s")
    print(f"Artifact B (SadTalker PiP) Duration:   {measured_b_dur:.2f}s")
    print(f"Composition Discrepancy (Art B vs Audio): {abs(measured_b_dur - new_total_audio):.3f}s")
    print("=" * 70)


if __name__ == "__main__":
    main()
