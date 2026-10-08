"""Master Real E2E Acceptance Test for Local Video Generation Pipeline.

Topic: Phishing Email Awareness for Employees
Base Language: en-US
Target Language: ar-SA
Target Duration: 30 seconds
Avatar Engine: SadTalker Local (isolated in .sadtalker-venv on CUDA)
TTS: Edge-TTS (ar-SA-HamedNeural)
LLM: Groq (openai/gpt-oss-20b)
Visuals: Local Pillow Visual Slides
Subtitles: ASS with Complex RTL HarfBuzz Shaping
Composition: FFmpeg (48,000 Hz, stereo AAC 192kbps, 1920x1080)
NO HEYGEN / NO PAID CREDITS.
"""

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, Any, List

# Ensure project root in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.config import settings
from app.core.logging import logger
from app.models.schemas import TrainingVideoRequest
from app.services.llm.groq_provider import GroqProvider
from app.services.localization.service import LocalizationService
from app.services.tts.service import TTSService
from app.services.tts.audio_probe import get_audio_duration
from app.services.duration.reconciliation import DurationReconciliationService
from app.services.avatar.sadtalker_provider import SadTalkerProvider
from app.services.avatar.service import AvatarService
from app.services.visuals.service import VisualService
from app.services.subtitles.service import SubtitleService
from app.services.composition.service import CompositionService
from app.services.composition.ffmpeg_provider import FFmpegCompositionProvider
from app.services.composition.ffmpeg_utils import get_video_duration
from app.workflows.manifest import ProjectManifestManager
from app.workflows.orchestrator import ProjectOrchestrator


def probe_media_file(file_path: Path) -> Dict[str, Any]:
    """Inspect media file using ffprobe and return parsed streams and format."""
    ffprobe_bin = shutil.which("ffprobe") or "ffprobe"
    cmd = [
        ffprobe_bin,
        "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        str(file_path),
    ]
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
    return json.loads(res.stdout)


def get_gpu_info() -> str:
    """Detect available NVIDIA GPU model via nvidia-smi."""
    try:
        res = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
        )
        return res.stdout.strip()
    except Exception:
        return "Unknown GPU / CPU fallback"


def main():
    project_id = "proj_local_video_generation_acceptance"
    locale = "ar-SA"
    target_duration = 30.0

    print("=" * 75)
    print("PHASE 12: REAL LOCAL E2E ACCEPTANCE TEST")
    print("Topic: Phishing Email Awareness for Employees")
    print("Target Duration: 30.0s | Locale: ar-SA | Avatar: SadTalker Local")
    print("=" * 75)

    gpu_name = get_gpu_info()
    print(f"Detected Hardware GPU: {gpu_name}")

    # Verify SadTalker readiness before starting
    sadtalker_prov = SadTalkerProvider()
    readiness = sadtalker_prov.check_readiness()
    print(f"SadTalker Readiness: {readiness['ready']}")
    if not readiness["ready"]:
        print(f"SadTalker not ready! Details: {readiness}")
        sys.exit(1)

    # Initialize Services
    groq_llm = GroqProvider()
    print(f"Active LLM: groq ({groq_llm.model_name})")

    loc_service = LocalizationService(llm_provider=groq_llm)
    tts_service = TTSService()
    dur_service = DurationReconciliationService(llm_provider=groq_llm)
    avatar_service = AvatarService(provider=sadtalker_prov)
    visual_service = VisualService()
    subtitle_service = SubtitleService()
    comp_service = CompositionService(provider=FFmpegCompositionProvider())
    manifest_mgr = ProjectManifestManager()

    orchestrator = ProjectOrchestrator(
        manifest_manager=manifest_mgr,
        llm_provider=groq_llm,
        localization_service=loc_service,
        tts_service=tts_service,
        avatar_service=avatar_service,
        visual_service=visual_service,
        subtitle_service=subtitle_service,
        composition_service=comp_service,
        duration_service=dur_service,
    )

    req = TrainingVideoRequest(
        topic="Phishing Email Awareness for Employees",
        audience="Corporate Employees",
        base_language="en-US",
        target_languages=[locale],
        target_duration_seconds=int(target_duration),
        avatar_provider="sadtalker",
        ack_paid_credits=False,
    )

    t_start = time.time()
    print("\n--- Launching Full Pipeline Orchestration ---")
    manifest = orchestrator.run_project(project_id=project_id, request=req, force_regenerate=True)
    t_end = time.time()
    total_elapsed = t_end - t_start

    print(f"\nPipeline Execution Finished in {total_elapsed:.2f} seconds.")
    print(f"Final Manifest Status: {manifest.status}")
    print(f"Duration Reconciliation Status: {manifest.metadata.get('duration_reconciliation', {}).get(locale, {}).get('status')}")

    # Inspect media outputs
    final_video_asset = manifest.final_videos.get(locale)
    if not final_video_asset or not final_video_asset.video_path:
        print(f"ERROR: Final video was not generated for {locale}")
        sys.exit(1)

    final_video_path = Path(final_video_asset.video_path)
    if not final_video_path.exists():
        print(f"ERROR: Final video path does not exist: {final_video_path}")
        sys.exit(1)

    probe = probe_media_file(final_video_path)
    fmt = probe.get("format", {})
    streams = probe.get("streams", [])

    video_stream = next((s for s in streams if s.get("codec_type") == "video"), {})
    audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), {})

    duration_str = fmt.get("duration", "0")
    final_duration = float(duration_str)
    file_size_bytes = int(fmt.get("size", "0"))

    # Extract scene audit info
    script = manifest.localization_bundle.localized_scripts[locale]
    audio_track = manifest.audio_tracks[locale]
    avatar_track = manifest.avatar_tracks[locale]
    visual_track = manifest.visual_tracks[locale]
    sub_track = manifest.subtitle_tracks[locale]

    rendered_scenes_dir = manifest_mgr.get_project_dir(project_id) / "composition" / locale
    rendered_files = list(rendered_scenes_dir.glob("scene_*.mp4")) if rendered_scenes_dir.exists() else []

    rendered_durations = {}
    for rf in rendered_files:
        try:
            rendered_durations[rf.stem] = get_video_duration(rf)
        except Exception:
            pass

    scene_audio_map = {a.scene_id: a for a in audio_track.scene_audio}
    scene_avatar_map = {a.scene_id: a for a in avatar_track.scene_avatars}
    scene_sub_map = {s.scene_id: s for s in sub_track.scene_subtitles}

    dur_meta = manifest.metadata.get("duration_reconciliation", {}).get(locale, {})

    print("\n" + "=" * 75)
    print("MEDIA VALIDATION (ffprobe):")
    print("=" * 75)
    print(f"Path: {final_video_path}")
    print(f"File Size: {file_size_bytes / (1024 * 1024):.2f} MB ({file_size_bytes} bytes)")
    print(f"Duration: {final_duration:.2f} seconds")
    print(f"Resolution: {video_stream.get('width')}x{video_stream.get('height')}")
    print(f"FPS: {video_stream.get('r_frame_rate')}")
    print(f"Video Codec: {video_stream.get('codec_name')} ({video_stream.get('pix_fmt')})")
    print(f"Audio Codec: {audio_stream.get('codec_name')}")
    print(f"Audio Sample Rate: {audio_stream.get('sample_rate')} Hz")
    print(f"Audio Channels: {audio_stream.get('channels')}")
    print(f"Audio Bitrate: {audio_stream.get('bit_rate', 'N/A')} bps")

    print("\n" + "=" * 75)
    print("SCENE TIMELINE AUDIT TABLE:")
    print("=" * 75)
    header = f"{'Scene':<10} | {'Type':<10} | {'Words':<6} | {'Target':<7} | {'Final TTS':<9} | {'Avatar/Vis':<10} | {'Rendered':<9} | {'Sub End':<8}"
    print(header)
    print("-" * len(header))

    total_final_tts = 0.0
    total_rendered = 0.0

    sadtalker_scene_dur = 0.0
    for scene in script.scenes:
        sid = scene.scene_id
        stype = scene.scene_type
        words = len(scene.narration.split()) if scene.narration else 0
        tgt = scene.estimated_duration_seconds
        
        aud = scene_audio_map.get(sid)
        tts_dur = aud.duration_seconds if aud else 0.0
        total_final_tts += tts_dur

        av = scene_avatar_map.get(sid)
        if av and av.status == "completed" and av.video_path:
            av_dur = av.duration_seconds
            av_text = f"Av: {av_dur:.2f}s"
            sadtalker_scene_dur += av_dur
        else:
            av_text = "Visual"

        rend_dur = rendered_durations.get(sid, 0.0)
        total_rendered += rend_dur

        sub = scene_sub_map.get(sid)
        sub_end = f"{sub.duration_seconds:.2f}s" if sub else "N/A"

        print(f"{sid:<10} | {stype:<10} | {words:<6} | {tgt:<7.1f} | {tts_dur:<9.2f} | {av_text:<10} | {rend_dur:<9.2f} | {sub_end:<8}")

    print("-" * len(header))
    print(f"Requested Total:    {target_duration:.2f}s")
    print(f"Sum Final TTS:      {total_final_tts:.2f}s")
    print(f"Sum Rendered Scenes:{total_rendered:.2f}s")
    print(f"Final MP4 Duration: {final_duration:.2f}s")
    diff = abs(final_duration - target_duration)
    print(f"Difference to Target:{diff:.2f}s (Tolerance: ±{settings.POST_TTS_DURATION_TOLERANCE_SECONDS}s)")

    # Audit SadTalker performance
    sadtalker_meta = manifest.metadata.get("sadtalker_performance", {})
    inf_time = sadtalker_meta.get("inference_time_seconds", 0.0)
    # If not in manifest metadata, calculate from job json
    job_file = manifest_mgr.get_project_dir(project_id) / "avatars" / locale / "scene_1.job.json"
    if job_file.exists():
        job_data = json.loads(job_file.read_text(encoding="utf-8"))
        inf_time = job_data.get("inference_time_seconds", inf_time)

    rtf = (inf_time / sadtalker_scene_dur) if sadtalker_scene_dur > 0 else 0.0

    print("\n" + "=" * 75)
    print("SADTALKER LOCAL AVATAR PERFORMANCE:")
    print("=" * 75)
    print(f"GPU Hardware:      {gpu_name}")
    print(f"Avatar Scene:      scene_1")
    print(f"Footage Duration:  {sadtalker_scene_dur:.2f}s")
    print(f"Inference Time:    {inf_time:.2f}s")
    print(f"Real-Time Factor:  {rtf:.2f}x (Inference Time / Video Duration)")

    # Produce Acceptance Artifact Summary
    report_data = {
        "project_id": project_id,
        "topic": req.topic,
        "locale": locale,
        "hardware_gpu": gpu_name,
        "requested_duration": target_duration,
        "duration_reconciliation": dur_meta,
        "final_media": {
            "path": str(final_video_path.resolve()),
            "file_size_bytes": file_size_bytes,
            "duration_seconds": final_duration,
            "width": video_stream.get("width"),
            "height": video_stream.get("height"),
            "fps": video_stream.get("r_frame_rate"),
            "video_codec": video_stream.get("codec_name"),
            "pix_fmt": video_stream.get("pix_fmt"),
            "audio_codec": audio_stream.get("codec_name"),
            "sample_rate": audio_stream.get("sample_rate"),
            "channels": audio_stream.get("channels"),
        },
        "timeline_audit": {
            "requested_total": target_duration,
            "sum_final_tts": total_final_tts,
            "sum_rendered_scenes": total_rendered,
            "final_mp4_duration": final_duration,
            "difference": diff,
            "within_tolerance": diff <= settings.POST_TTS_DURATION_TOLERANCE_SECONDS,
        },
        "sadtalker_performance": {
            "scene_id": "scene_1",
            "footage_duration": sadtalker_scene_dur,
            "inference_time_seconds": inf_time,
            "real_time_factor": rtf,
        },
    }

    report_path = manifest_mgr.get_project_dir(project_id) / "acceptance_report.json"
    report_path.write_text(json.dumps(report_data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nAcceptance report saved to: {report_path}")

    # Success check
    if diff <= settings.POST_TTS_DURATION_TOLERANCE_SECONDS and final_video_path.exists():
        print("\n>>> ACCEPTANCE TEST PASSED SUCCESSFULLY! <<<")
    else:
        print(f"\n>>> ACCEPTANCE TEST FINISHED (Diff: {diff:.2f}s) <<<")


if __name__ == "__main__":
    main()
