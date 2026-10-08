"""Local Non-Paid End-to-End Pipeline Verification Script.

Executes:
Real Groq -> Localization -> Real Edge-TTS -> Mock Avatar -> Local Visuals -> Subtitles -> FFmpeg -> Final MP4
"""

import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Force UTF-8 stdout/stderr
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from app.models.schemas import TrainingVideoRequest
from app.services.llm.groq_provider import GroqProvider
from app.services.tts.edge_tts_provider import EdgeTTSProvider
from app.services.avatar.mock_avatar_provider import MockAvatarProvider
from app.services.visuals.local_provider import LocalVisualProvider
from app.services.composition.ffmpeg_provider import FFmpegCompositionProvider
from app.workflows.orchestrator import ProjectOrchestrator
from app.services.localization.service import LocalizationService
from app.services.tts.service import TTSService
from app.services.avatar.service import AvatarService
from app.services.visuals.service import VisualService
from app.services.subtitles.service import SubtitleService
from app.services.composition.service import CompositionService


def run():
    print("=== STARTING NON-PAID REAL E2E PIPELINE ===")
    groq_prov = GroqProvider()
    tts_prov = EdgeTTSProvider()
    avatar_prov = MockAvatarProvider()
    visual_prov = LocalVisualProvider()
    ffmpeg_prov = FFmpegCompositionProvider()

    orchestrator = ProjectOrchestrator(
        llm_provider=groq_prov,
        localization_service=LocalizationService(llm_provider=groq_prov),
        tts_service=TTSService(provider=tts_prov),
        avatar_service=AvatarService(provider=avatar_prov),
        visual_service=VisualService(provider=visual_prov),
        subtitle_service=SubtitleService(),
        composition_service=CompositionService(provider=ffmpeg_prov),
    )

    req = TrainingVideoRequest(
        topic="Workplace Phishing Defense Essentials",
        audience="Corporate Employees in Saudi Arabia",
        base_language="en-US",
        target_languages=["ar-SA"],
        target_duration_seconds=30,
        tone="professional",
        difficulty_level="beginner",
        avatar_provider="mock",
        ack_paid_credits=False,
    )

    project_id = "proj_real_e2e_phishing"
    manifest = orchestrator.run_project(project_id=project_id, request=req, force_regenerate=True)

    print("\n=== PIPELINE EXECUTION SUMMARY ===")
    print(f"Overall Status: {manifest.status}")
    print(f"Script Status: {manifest.script_status}")
    print(f"Localization Status: {manifest.localization_status}")
    print(f"Audio Status: {manifest.audio_status}")
    print(f"Avatar Status: {manifest.avatar_status}")
    print(f"Visual Status: {manifest.visual_status}")
    print(f"Subtitle Status: {manifest.subtitle_status}")
    print(f"Composition Status: {manifest.composition_status}")

    if manifest.status != "completed":
        print(f"FAILED ERRORS: {manifest.errors}")
        sys.exit(1)

    for loc, v in manifest.final_videos.items():
        print(f"\nLocale Output: {loc}")
        print(f"  Final MP4: {v.video_path}")
        print(f"  Duration: {v.total_duration_seconds:.2f}s")
        print(f"  Scenes: {v.scene_count}")
        v_path = Path(v.video_path)
        assert v_path.exists(), f"MP4 does not exist: {v_path}"
        assert v_path.stat().st_size > 0, f"MP4 is empty: {v_path}"
        print(f"  File Size: {v_path.stat().st_size} bytes")

    print("\nSUCCESS: End-to-end non-paid pipeline completed with final MP4 rendered!")


if __name__ == "__main__":
    run()
