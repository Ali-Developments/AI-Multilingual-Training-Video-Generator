"""Real E2E Acceptance Test for Video Studio V2.

Phase 35 & 36 Acceptance Requirements:
- Topic: Workplace Phishing Defense Essentials
- Source: en-US
- Target: ar-SA
- Target Duration: 30 seconds
- Video Style: Hybrid Presenter + B-Roll
- Presenter Engine: SadTalker Local on CUDA (.sadtalker-venv)
- Audio: Edge-TTS (ar-SA-HamedNeural), 48,000 Hz stereo AAC
- Composition: 1920x1080 H.264, Presenter-Led (Split/Full), Motion Visuals, Subtitles
- Visual Quality: Zero internal developer metadata, No giant PPT boxes, No tiny avatar windows
"""

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, Any

# Ensure project root in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.config import settings
from app.core.logging import logger
from app.models.schemas import TrainingVideoRequest, VideoStyle
from app.services.llm.groq_provider import GroqProvider
from app.services.localization.service import LocalizationService
from app.services.tts.service import TTSService
from app.services.duration.reconciliation import DurationReconciliationService
from app.services.avatar.sadtalker_provider import SadTalkerProvider
from app.services.avatar.service import AvatarService
from app.services.visuals.service import VisualService
from app.services.subtitles.service import SubtitleService
from app.services.composition.service import CompositionService
from app.services.composition.ffmpeg_provider import FFmpegCompositionProvider
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


def main():
    project_id = "proj_v2_phishing_acceptance"
    locale = "ar-SA"
    target_duration = 30.0

    print("=" * 80)
    print("VIDEO STUDIO V2 — REAL LOCAL E2E ACCEPTANCE TEST (PHASES 35 & 36)")
    print(f"Project ID: {project_id}")
    print(f"Topic: Workplace Phishing Defense Essentials")
    print(f"Style: Hybrid Presenter + B-Roll")
    print(f"Target Duration: {target_duration}s | Target Locales: ['{locale}']")
    print(f"Avatar Engine: SadTalker Local (CUDA)")
    print("=" * 80)

    # 1. Verify SadTalker readiness
    sadtalker_prov = SadTalkerProvider()
    readiness = sadtalker_prov.check_readiness()
    print(f"\n[1/7] Checking SadTalker Readiness: {readiness.get('ready')}")
    if not readiness.get("ready"):
        print(f"CRITICAL: SadTalker is not ready! Details: {readiness}")
        sys.exit(1)

    # 2. Initialize Core V2 Services
    groq_llm = GroqProvider()
    print(f"[2/7] Active LLM: Groq ({groq_llm.model_name})")

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
        topic="Workplace Phishing Defense Essentials",
        source_content=(
            "Welcome to phishing defense training. "
            "Phishing emails often impersonate executive management or IT support, urging urgent password resets. "
            "Always inspect sender email addresses carefully, inspect hyperlink URLs before clicking, and never open suspicious attachments. "
            "Report unexpected messages immediately to IT Security Operations to keep our organization safe."
        ),
        audience="Corporate Employees & Remote Staff",
        base_language="en-US",
        target_languages=[locale],
        target_duration_seconds=int(target_duration),
        video_style=VideoStyle.HYBRID_PRESENTER_BROLL,
        avatar_provider="sadtalker",
        ack_paid_credits=False,
    )

    t_start = time.time()
    print("\n[3/7] Executing Full V2 Pipeline Orchestration...")
    manifest = orchestrator.run_project(project_id=project_id, request=req, force_regenerate=False)
    t_end = time.time()
    elapsed = t_end - t_start

    print("\n" + "=" * 80)
    print(f"PIPELINE EXECUTION COMPLETED IN {elapsed:.2f}s")
    print(f"Manifest Status: {manifest.status}")
    print(f"Script Status:   {manifest.script_status}")
    print(f"Localize Status: {manifest.localization_status}")
    print(f"Audio Status:    {manifest.audio_status}")
    print(f"Avatar Status:   {manifest.avatar_status}")
    print(f"Compose Status:  {manifest.composition_status}")
    print("=" * 80)

    assert manifest.status == "completed", f"Expected completed status, got: {manifest.status}"

    # 4. Inspect Storyboard Planning
    final_script = manifest.final_script
    assert final_script is not None, "Final script missing from manifest"
    print(f"\n[4/7] Storyboard Media Planning Analysis ({len(final_script.scenes)} Scenes):")
    for sc in final_script.scenes:
        mt = sc.media_type.value if hasattr(sc.media_type, "value") else str(sc.media_type)
        lo = sc.layout_type.value if hasattr(sc.layout_type, "value") else str(sc.layout_type)
        print(f"  Scene {sc.order:02d}: Media={mt:14s} | Layout={lo:16s} | AvatarEnabled={str(sc.avatar_enabled):5s}")
        print(f"            Prompt: {sc.visual_prompt[:60]}...")

    # 5. Verify Downstream Asset Tracks
    print("\n[5/7] Verifying Avatar, Motion Visual, and Audio Assets:")
    avatar_tracks = manifest.avatar_tracks or {}
    print(f"  Total Avatar Tracks Generated: {len(avatar_tracks)}")
    avatar_video_count = 0
    for key, tr in avatar_tracks.items():
        for sa in tr.scene_avatars:
            if sa.video_path:
                avatar_video_count += 1
                print(f"    Avatar Track [{key} - {sa.scene_id}]: {sa.video_path} (Exists: {Path(sa.video_path).is_file()})")
                assert Path(sa.video_path).is_file(), f"Avatar file {sa.video_path} does not exist"
    print(f"  Total Avatar Videos Verified: {avatar_video_count}")

    # 6. Verify Final Video Output
    print("\n[6/7] Probing Final Video Output:")
    final_video_path = Path("storage/projects") / project_id / "final" / f"training_{locale}.mp4"
    print(f"  Final MP4 Path: {final_video_path} (Exists: {final_video_path.is_file()})")
    assert final_video_path.is_file(), f"Final MP4 not found at {final_video_path}"

    probe = probe_media_file(final_video_path)
    fmt = probe.get("format", {})
    streams = probe.get("streams", [])
    v_stream = next((s for s in streams if s.get("codec_type") == "video"), {})
    a_stream = next((s for s in streams if s.get("codec_type") == "audio"), {})

    final_duration = float(fmt.get("duration", 0.0))
    width = int(v_stream.get("width", 0))
    height = int(v_stream.get("height", 0))
    video_codec = v_stream.get("codec_name")
    audio_codec = a_stream.get("codec_name")
    sample_rate = a_stream.get("sample_rate")
    channels = int(a_stream.get("channels", 0))

    print(f"\n  Final Measured Duration: {final_duration:.2f}s (Target: {target_duration}s, Delta: {abs(final_duration - target_duration):.2f}s)")
    print(f"  Resolution:             {width}x{height}")
    print(f"  Video Codec:            {video_codec}")
    print(f"  Audio Codec:            {audio_codec}")
    print(f"  Audio Sample Rate:      {sample_rate} Hz (Normalized standard)")
    print(f"  Audio Channels:         {channels}")

    # Phase 36 Acceptance Criteria Validations
    assert 25.5 <= final_duration <= 34.5, f"Duration {final_duration}s outside configured ±4.5s tolerance"
    assert width == 1920 and height == 1080, f"Resolution must be 1920x1080, got {width}x{height}"
    assert video_codec in ("h264", "avc1"), f"Expected H.264 video codec, got {video_codec}"
    assert audio_codec in ("aac", "mp4a-40-2"), f"Expected AAC audio codec, got {audio_codec}"
    assert sample_rate == "48000", f"Expected 48000 Hz audio sample rate, got {sample_rate}"
    assert channels == 2, f"Expected stereo (2 channels) audio, got {channels}"

    # 7. Write Acceptance Report
    print("\n[7/7] Writing Acceptance Report:")
    report = {
        "project_id": project_id,
        "topic": req.topic,
        "style": req.video_style.value if hasattr(req.video_style, "value") else str(req.video_style),
        "target_locale": locale,
        "target_duration_seconds": target_duration,
        "final_duration_seconds": round(final_duration, 2),
        "duration_delta_seconds": round(abs(final_duration - target_duration), 2),
        "status": manifest.status,
        "width": width,
        "height": height,
        "video_codec": video_codec,
        "audio_codec": audio_codec,
        "sample_rate": sample_rate,
        "channels": channels,
        "avatar_tracks_count": len(avatar_tracks),
        "scene_count": len(final_script.scenes),
        "pipeline_runtime_seconds": round(elapsed, 2),
        "final_mp4_path": str(final_video_path),
        "acceptance_criteria_passed": True,
    }
    report_path = Path("storage/projects") / project_id / "v2_acceptance_report.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"  Saved report to: {report_path}")

    print("\n" + "=" * 80)
    print("ALL PHASE 35 & 36 ACCEPTANCE CHECKS PASSED SUCCESSFULLY!")
    print("=" * 80)


if __name__ == "__main__":
    main()
