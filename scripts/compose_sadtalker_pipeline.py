import json
import os
import subprocess
import sys
import time
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import settings
from app.models.schemas import (
    LocalizedAvatarTrack,
    AvatarVideoAsset,
)

from app.services.composition.service import CompositionService
from app.services.composition.ffmpeg_provider import FFmpegCompositionProvider
from app.workflows.manifest import ProjectManifestManager

def main():
    print("=" * 60)
    print("SADTALKER INTEGRATED FULL PIPELINE COMPOSITION")
    print("=" * 60)

    project_id = "proj_real_e2e_phishing"
    locale = "ar-SA"

    manifest_mgr = ProjectManifestManager()
    manifest = manifest_mgr.load_manifest(project_id)
    if not manifest:
        print(f"Error: Manifest not found for project {project_id}")
        sys.exit(1)

    script = manifest.localization_bundle.localized_scripts[locale]
    audio_track = manifest.audio_tracks[locale]
    visual_track = manifest.visual_tracks.get(locale)
    subtitle_track = manifest.subtitle_tracks.get(locale)

    # Use the local SadTalker generated MP4 for scene_1
    sadtalker_avatar_file = Path(f"storage/projects/{project_id}/avatars/{locale}/scene_1_sadtalker.mp4").resolve()
    if not sadtalker_avatar_file.exists():
        print(f"Error: SadTalker avatar missing at {sadtalker_avatar_file}")
        sys.exit(1)

    print(f"Using SadTalker avatar for scene_1: {sadtalker_avatar_file} ({sadtalker_avatar_file.stat().st_size} bytes)")

    # Construct avatar track pointing to SadTalker scene_1 and mock/skipped for other scenes
    scene_avatars = []
    for sc in script.scenes:
        if sc.scene_id == "scene_1":
            scene_avatars.append(
                AvatarVideoAsset(
                    scene_id="scene_1",
                    locale=locale,
                    provider="sadtalker",
                    job_id="sadtalker_smoke_scene_1",
                    video_path=str(sadtalker_avatar_file),
                    duration_seconds=8.32,
                    status="completed",
                    avatar_id="local_presenter.png",
                )
            )
        else:
            scene_avatars.append(
                AvatarVideoAsset(
                    scene_id=sc.scene_id,
                    locale=locale,
                    provider="mock",
                    job_id="supporting_visual_workflow",
                    video_path=None,
                    duration_seconds=0.0,
                    status="skipped",
                    avatar_id=None,
                )
            )

    avatar_track = LocalizedAvatarTrack(
        locale=locale,
        scene_avatars=scene_avatars,
        status="completed",
        metadata={"provider": "sadtalker", "local_free": True},
    )

    print("\nComposing scenes with FFmpeg...")
    comp_provider = FFmpegCompositionProvider()
    comp_service = CompositionService(provider=comp_provider)

    t0 = time.time()
    # Force re-rendering of scenes to incorporate SadTalker
    scene_assets = comp_service.compose_locale_scenes(
        script=script,
        audio_track=audio_track,
        visual_track=visual_track,
        subtitle_track=subtitle_track,
        avatar_track=avatar_track,
        project_id=project_id,
        force_regenerate=True,
    )
    t1 = time.time()
    print(f"Composed {len(scene_assets)} scenes in {t1 - t0:.2f}s:")
    for sc in scene_assets:
        print(f"  [{sc.scene_id}] status={sc.status}, duration={sc.duration_seconds:.2f}s, avatar={sc.has_avatar}, sub={sc.has_subtitles}")

    final_output_path = Path(f"storage/projects/{project_id}/final/training_{locale}_sadtalker.mp4").resolve()
    print(f"\nConcatenating full video to: {final_output_path}...")
    final_video = comp_provider.concatenate_scenes(
        scene_videos=scene_assets,
        locale=locale,
        output_path=final_output_path,
    )
    t2 = time.time()
    print(f"\nConcatenation finished in {t2 - t1:.2f}s!")
    print(f"Final MP4: {final_video.video_path}")
    print(f"Measured Duration: {final_video.total_duration_seconds:.2f}s")


    # ffprobe inspection of final video
    print("\nRunning ffprobe on final composed video...")
    probe_cmd = [
        "ffprobe",
        "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        str(final_output_path),
    ]
    res = subprocess.run(probe_cmd, capture_output=True, text=True)
    if res.returncode == 0:
        meta = json.loads(res.stdout)
        v_stream = next((s for s in meta.get("streams", []) if s.get("codec_type") == "video"), {})
        a_stream = next((s for s in meta.get("streams", []) if s.get("codec_type") == "audio"), {})
        fmt = meta.get("format", {})
        
        print("\n" + "=" * 60)
        print("FINAL E2E VIDEO TECHNICAL VALIDATION:")
        print("=" * 60)
        print(f"Path: {final_output_path}")
        print(f"Size: {final_output_path.stat().st_size} bytes ({final_output_path.stat().st_size / 1024 / 1024:.2f} MB)")
        print(f"Duration: {float(fmt.get('duration', 0)):.2f}s")
        print(f"Width: {v_stream.get('width')}")
        print(f"Height: {v_stream.get('height')}")
        print(f"FPS: {v_stream.get('r_frame_rate')}")
        print(f"Video Codec: {v_stream.get('codec_name')}")
        print(f"Audio Codec: {a_stream.get('codec_name')}")
        print("=" * 60)

if __name__ == "__main__":
    main()
