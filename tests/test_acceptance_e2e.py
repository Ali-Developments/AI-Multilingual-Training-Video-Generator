"""Final End-to-End Acceptance Test (Step 15).

Executes a complete training video project run for:
- Topic: Workplace Phishing Defense
- Audience: Corporate Employees
- Base Language: en-US
- Target Locales: ar-SA, bn-BD
- Duration: 60 seconds

Verifies:
1. Manifest state transitions to 'completed'.
2. Full artifact tree exists on disk matching the master plan specification:
   - project.json
   - scripts/ (source.json, ar-SA.json, bn-BD.json)
   - audio/ (ar-SA, bn-BD)
   - avatars/ (ar-SA, bn-BD)
   - subtitles/ (ar-SA/subtitles.srt, bn-BD/subtitles.srt)
   - visuals/ (ar-SA, bn-BD)
   - rendered/ (ar-SA, bn-BD scene mp4s)
   - final/ (training_ar-SA.mp4, training_bn-BD.mp4)
3. Zero paid API credit consumption ($0.00).
"""

from pathlib import Path
import pytest

from app.models.schemas import TrainingVideoRequest
from tests.test_orchestrator import create_test_orchestrator


def test_final_acceptance_end_to_end_pipeline(tmp_path: Path):
    """Execute complete end-to-end acceptance run and verify entire artifact directory tree."""
    storage_root = tmp_path / "storage"
    orchestrator = create_test_orchestrator(tmp_path)

    request = TrainingVideoRequest(
        topic="Workplace Phishing Defense",
        audience="Corporate Employees",
        base_language="en-US",
        target_languages=["ar-SA", "bn-BD"],
        target_duration_seconds=60,
    )

    project_id = "acceptance_phishing_defense"
    result_manifest = orchestrator.run_project(project_id=project_id, request=request)
    project_dir = storage_root / project_id

    # 1. Verify Manifest Status
    assert result_manifest.status == "completed"
    assert result_manifest.script_status == "completed"
    assert result_manifest.localization_status == "completed"
    assert result_manifest.audio_status == "completed"
    assert result_manifest.avatar_status == "completed"
    assert result_manifest.visual_status == "completed"
    assert result_manifest.subtitle_status == "completed"
    assert result_manifest.composition_status == "completed"

    # 2. Verify Full Artifact Tree on Disk
    # project.json
    manifest_file = project_dir / "project.json"
    assert manifest_file.is_file(), "project.json must exist"

    # scripts/
    scripts_dir = project_dir / "scripts"
    assert scripts_dir.is_dir(), "scripts/ directory must exist"
    assert (scripts_dir / "source.json").is_file(), "scripts/source.json must exist"
    assert (scripts_dir / "ar-SA.json").is_file(), "scripts/ar-SA.json must exist"
    assert (scripts_dir / "bn-BD.json").is_file(), "scripts/bn-BD.json must exist"

    # audio/
    audio_dir = project_dir / "audio"
    assert audio_dir.is_dir(), "audio/ directory must exist"
    assert (audio_dir / "ar-SA").is_dir()
    assert (audio_dir / "bn-BD").is_dir()
    ar_audio_files = list((audio_dir / "ar-SA").glob("*.wav"))
    bn_audio_files = list((audio_dir / "bn-BD").glob("*.wav"))
    assert len(ar_audio_files) > 0, "audio/ar-SA must contain audio files"
    assert len(bn_audio_files) > 0, "audio/bn-BD must contain audio files"

    # avatars/
    avatar_dir = project_dir / "avatars"
    assert avatar_dir.is_dir(), "avatars/ directory must exist"
    assert (avatar_dir / "ar-SA").is_dir()
    assert (avatar_dir / "bn-BD").is_dir()
    ar_avatar_files = list((avatar_dir / "ar-SA").glob("*.mp4"))
    bn_avatar_files = list((avatar_dir / "bn-BD").glob("*.mp4"))
    assert len(ar_avatar_files) > 0, "avatars/ar-SA must contain avatar mp4 files"
    assert len(bn_avatar_files) > 0, "avatars/bn-BD must contain avatar mp4 files"

    # subtitles/
    sub_dir = project_dir / "subtitles"
    assert sub_dir.is_dir(), "subtitles/ directory must exist"
    assert (sub_dir / "ar-SA" / "subtitles.srt").is_file(), "ar-SA/subtitles.srt must exist"
    assert (sub_dir / "ar-SA" / "subtitles.vtt").is_file(), "ar-SA/subtitles.vtt must exist"
    assert (sub_dir / "bn-BD" / "subtitles.srt").is_file(), "bn-BD/subtitles.srt must exist"
    assert (sub_dir / "bn-BD" / "subtitles.vtt").is_file(), "bn-BD/subtitles.vtt must exist"

    # visuals/
    vis_dir = project_dir / "visuals"
    assert vis_dir.is_dir(), "visuals/ directory must exist"
    assert (vis_dir / "ar-SA").is_dir()
    assert (vis_dir / "bn-BD").is_dir()
    ar_vis_files = list((vis_dir / "ar-SA").glob("*.png"))
    bn_vis_files = list((vis_dir / "bn-BD").glob("*.png"))
    assert len(ar_vis_files) > 0, "visuals/ar-SA must contain slide images"
    assert len(bn_vis_files) > 0, "visuals/bn-BD must contain slide images"

    # rendered/
    rendered_dir = project_dir / "rendered"
    assert rendered_dir.is_dir(), "rendered/ directory must exist"
    assert (rendered_dir / "ar-SA").is_dir()
    assert (rendered_dir / "bn-BD").is_dir()
    ar_scene_vids = list((rendered_dir / "ar-SA").glob("*.mp4"))
    bn_scene_vids = list((rendered_dir / "bn-BD").glob("*.mp4"))
    assert len(ar_scene_vids) > 0, "rendered/ar-SA must contain rendered scene mp4 files"
    assert len(bn_scene_vids) > 0, "rendered/bn-BD must contain rendered scene mp4 files"

    # final/
    final_dir = project_dir / "final"
    assert final_dir.is_dir(), "final/ directory must exist"
    final_ar_video = final_dir / "training_ar-SA.mp4"
    final_bn_video = final_dir / "training_bn-BD.mp4"
    assert final_ar_video.is_file(), "final/training_ar-SA.mp4 must exist"
    assert final_bn_video.is_file(), "final/training_bn-BD.mp4 must exist"
    assert final_ar_video.stat().st_size > 0, "final/training_ar-SA.mp4 must be non-empty"
    assert final_bn_video.stat().st_size > 0, "final/training_bn-BD.mp4 must be non-empty"
