"""Real E2E Acceptance Test for ar-SA ONLY Pipeline Verification.

Topic: Phishing Email Awareness for Employees
Base Language: en-US
Target Language: ar-SA ONLY (Zero bn-BD)
Target Duration: 30 seconds
Avatar Engine: SadTalker Local (.sadtalker-venv on CUDA)
TTS: Edge-TTS (ar-SA-HamedNeural)
LLM: Groq (openai/gpt-oss-20b with strict json_schema mode)
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
from typing import Dict, Any

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
    project_id = "proj_real_ar_sa_only_verification"
    locale = "ar-SA"
    target_duration = 30.0

    print("=" * 75)
    print("REAL LOCAL E2E VERIFICATION: ar-SA ONLY")
    print(f"Project ID: {project_id}")
    print("Target Duration: 30.0s | Target Locales: ['ar-SA'] STRICTLY")
    print("Avatar Provider: SadTalker Local | LLM: openai/gpt-oss-20b")
    print("=" * 75)

    # 1. Verify SadTalker readiness
    sadtalker_prov = SadTalkerProvider()
    readiness = sadtalker_prov.check_readiness()
    print(f"SadTalker Readiness: {readiness['ready']}")
    if not readiness["ready"]:
        print(f"SadTalker not ready! Details: {readiness}")
        sys.exit(1)

    # 2. Initialize Core Services
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

    # STRICTLY ar-SA ONLY
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
    print("\n--- Executing Full Pipeline ---")
    manifest = orchestrator.run_project(project_id=project_id, request=req, force_regenerate=True)
    t_end = time.time()
    elapsed = t_end - t_start

    print("\n" + "=" * 75)
    print("EXECUTION COMPLETED")
    print(f"Total Pipeline Runtime: {elapsed:.2f}s")
    print(f"Manifest Status: {manifest.status}")
    print(f"Localization Status: {manifest.localization_status}")
    print(f"Requested Target Locales: {manifest.source_request.target_languages}")
    assert manifest.source_request.target_languages == ["ar-SA"], "Target languages must be strictly ar-SA!"

    # Verify localized scripts on disk and manifest
    localized_keys = list(manifest.localization_bundle.localized_scripts.keys()) if manifest.localization_bundle else []
    print(f"Executed Localized Locales: {localized_keys}")
    assert "bn-BD" not in localized_keys, "CRITICAL ERROR: bn-BD was unexpectedly executed!"
    assert localized_keys == ["ar-SA"], f"Expected only ['ar-SA'], got {localized_keys}"

    # Verify final MP4 exists
    final_video_path = Path("storage/projects") / project_id / "final" / f"training_{locale}.mp4"
    print(f"Final MP4 Path: {final_video_path} (Exists: {final_video_path.is_file()})")
    assert final_video_path.is_file(), f"Final MP4 not found at {final_video_path}"

    # Probe final MP4
    probe = probe_media_file(final_video_path)
    fmt = probe.get("format", {})
    streams = probe.get("streams", [])
    v_stream = next((s for s in streams if s.get("codec_type") == "video"), {})
    a_stream = next((s for s in streams if s.get("codec_type") == "audio"), {})

    final_duration = float(fmt.get("duration", 0.0))
    print(f"\nFinal Video Metrics:")
    print(f"  Duration: {final_duration:.2f}s (Requested: {target_duration}s, Delta: {abs(final_duration - target_duration):.2f}s)")
    print(f"  Resolution: {v_stream.get('width')}x{v_stream.get('height')}")
    print(f"  Video Codec: {v_stream.get('codec_name')} | FPS: {v_stream.get('r_frame_rate')}")
    print(f"  Audio Codec: {a_stream.get('codec_name')} | Sample Rate: {a_stream.get('sample_rate')} Hz | Channels: {a_stream.get('channels')}")

    assert 27.0 <= final_duration <= 33.0, f"Duration {final_duration}s out of acceptable ±3.0s window"
    assert v_stream.get("width") == 1920 and v_stream.get("height") == 1080
    assert a_stream.get("sample_rate") == "48000"
    assert a_stream.get("channels") == 2

    # Save summary report
    report = {
        "project_id": project_id,
        "status": manifest.status,
        "requested_locales": manifest.source_request.target_languages,
        "localized_locales": localized_keys,
        "final_duration": final_duration,
        "final_mp4": str(final_video_path),
        "resolution": f"{v_stream.get('width')}x{v_stream.get('height')}",
        "sample_rate": a_stream.get("sample_rate"),
        "channels": a_stream.get("channels"),
        "pipeline_runtime_seconds": elapsed,
    }
    report_path = Path("storage/projects") / project_id / "real_run_report.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nReport written to: {report_path}")
    print("\nSUCCESS: REAL ar-SA ONLY RUN FULLY VERIFIED!")


if __name__ == "__main__":
    main()
