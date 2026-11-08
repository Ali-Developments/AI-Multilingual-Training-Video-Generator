"""Tests for Audit Remediation Phase C:
- ISSUE-007: Bidirectional Arabic / RTL & Multilingual Subtitle Robustness (.ass generation, complex shaping)
- ISSUE-008: Local Manifest Concurrency, Per-Project Locking & Atomic File Replacement
"""

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import pytest

from app.core.config import settings
from app.models.schemas import (
    TrainingVideoRequest,
    ProjectManifest,
    SubtitleChunk,
)
from app.services.subtitles.formatter import (
    format_timestamp_ass,
    serialize_ass,
    serialize_srt,
    split_narration_into_chunks,
)
from app.services.subtitles.deterministic_provider import DeterministicSubtitleProvider
from app.services.composition.ffmpeg_utils import (
    escape_ffmpeg_filter_path,
    check_ffmpeg_available,
)
from app.workflows.manifest import ProjectManifestManager


# =====================================================================
# ISSUE-007: Subtitle Formatting and FFmpeg Complex Shaping
# =====================================================================


def test_issue_007_format_timestamp_ass():
    """Verify ASS centisecond timestamp formatting (H:MM:SS.cc)."""
    assert format_timestamp_ass(0.0) == "0:00:00.00"
    assert format_timestamp_ass(1.234) == "0:00:01.23"
    assert format_timestamp_ass(65.5) == "0:01:05.50"
    assert format_timestamp_ass(3661.05) == "1:01:01.05"


def test_issue_007_serialize_ass_multilingual_fonts():
    """Verify serialize_ass generates valid ASS header, style, and events with locale font selection."""
    chunks = [
        SubtitleChunk(index=1, start_seconds=0.0, end_seconds=2.5, text="مرحبا بكم في التدريب"),
        SubtitleChunk(index=2, start_seconds=2.5, end_seconds=5.0, text="الأمن السيبراني ضروري"),
    ]

    # Arabic locale ASS output
    ar_ass = serialize_ass(chunks, locale="ar-SA")
    assert "[Script Info]" in ar_ass
    assert "[V4+ Styles]" in ar_ass
    assert "[Events]" in ar_ass
    assert "Segoe UI" in ar_ass or "Arial" in ar_ass
    assert "Dialogue: 0,0:00:00.00,0:00:02.50,Default,,0,0,0,,مرحبا بكم في التدريب" in ar_ass
    assert "Dialogue: 0,0:00:02.50,0:00:05.00,Default,,0,0,0,,الأمن السيبراني ضروري" in ar_ass

    # Bengali locale ASS output
    bn_chunks = [
        SubtitleChunk(index=1, start_seconds=0.0, end_seconds=3.0, text="সাইবার নিরাপত্তা প্রশিক্ষণ"),
    ]
    bn_ass = serialize_ass(bn_chunks, locale="bn-BD")
    assert "Nirmala UI" in bn_ass or "Arial" in bn_ass
    assert "সাইবার নিরাপত্তা প্রশিক্ষণ" in bn_ass

    # English locale ASS output
    en_chunks = [
        SubtitleChunk(index=1, start_seconds=0.0, end_seconds=2.0, text="Welcome to training."),
    ]
    en_ass = serialize_ass(en_chunks, locale="en-US")
    assert "Arial" in en_ass
    assert "Welcome to training." in en_ass


def test_issue_007_deterministic_provider_generates_all_formats(tmp_path: Path):
    """Verify DeterministicSubtitleProvider generates .srt, .vtt, and .ass files."""
    provider = DeterministicSubtitleProvider()
    narration = "هذا نص تدريبي باللغة العربية للتحقق من العناوين الفرعية."
    asset = provider.generate_scene_subtitles(
        scene_id="scene_ar_01",
        narration=narration,
        duration_seconds=5.0,
        locale="ar-SA",
        output_dir=tmp_path,
    )

    assert asset.status == "completed"
    assert Path(asset.srt_path).exists()
    assert Path(asset.vtt_path).exists()
    assert asset.ass_path is not None
    assert Path(asset.ass_path).exists()

    ass_text = Path(asset.ass_path).read_text(encoding="utf-8")
    assert "[Script Info]" in ass_text
    assert "Dialogue: " in ass_text
    assert "هذا نص تدريبي" in ass_text


@pytest.mark.skipif(not check_ffmpeg_available(), reason="FFmpeg binary required for live subtitle render test")
def test_issue_007_ffmpeg_arabic_ass_subtitle_burn(tmp_path: Path):
    """Verify FFmpeg renders an Arabic subtitle without error using complex text shaping."""
    import subprocess

    ass_file = tmp_path / "arabic_test.ass"
    chunks = [
        SubtitleChunk(index=1, start_seconds=0.0, end_seconds=1.0, text="اختبار الترجمة العربية"),
    ]
    ass_file.write_text(serialize_ass(chunks, locale="ar-SA"), encoding="utf-8")

    out_mp4 = tmp_path / "arabic_test_output.mp4"
    escaped_sub = escape_ffmpeg_filter_path(ass_file)

    cmd = [
        settings.FFMPEG_BINARY_PATH,
        "-y",
        "-f", "lavfi", "-i", "color=c=black:s=640x360:d=1",
        "-vf", f"ass={escaped_sub}:shaping=complex",
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        str(out_mp4.resolve()),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    assert res.returncode == 0, f"FFmpeg burn failed: {res.stderr}"
    assert out_mp4.exists()
    assert out_mp4.stat().st_size > 0


# =====================================================================
# ISSUE-008: Manifest Concurrency, Locking & Atomic Persistence
# =====================================================================


def test_issue_008_atomic_save_and_load(tmp_path: Path):
    """Verify manifest is saved atomically and loaded correctly without leaving temporary files."""
    mgr = ProjectManifestManager(storage_base_dir=tmp_path)
    req = TrainingVideoRequest(
        topic="Concurrent Testing",
        base_language="en-US",
        target_languages=["ar-SA"],
    )
    manifest = mgr.create_manifest("proj_atomic_01", req)
    assert manifest.status == "pending"

    manifest_file = mgr.get_manifest_path("proj_atomic_01")
    assert manifest_file.exists()

    # Verify no dangling temporary files remain
    tmp_files = list(tmp_path.glob("**/*.tmp"))
    assert len(tmp_files) == 0

    # Read and verify valid JSON
    loaded = mgr.load_manifest("proj_atomic_01")
    assert loaded is not None
    assert loaded.project_id == "proj_atomic_01"
    assert loaded.source_request.topic == "Concurrent Testing"


def test_issue_008_concurrent_writes_same_project(tmp_path: Path):
    """Verify concurrent thread writes to the same project never corrupt JSON or throw file conflicts."""
    mgr = ProjectManifestManager(storage_base_dir=tmp_path)
    req = TrainingVideoRequest(
        topic="Thread Safety Verification",
        base_language="en-US",
        target_languages=["es-ES"],
    )
    manifest = mgr.create_manifest("proj_threads_01", req)

    def write_update(thread_id: int):
        for step in range(5):
            m = mgr.load_manifest("proj_threads_01")
            assert m is not None
            m.record_error(stage="test", message=f"Thread {thread_id} step {step}", code=f"ERR_{thread_id}")
            mgr.save_manifest(m)

    # Launch 6 concurrent worker threads writing to the same manifest
    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = [executor.submit(write_update, tid) for tid in range(6)]
        for f in futures:
            f.result()

    # Verify JSON is 100% valid and readable
    final_m = mgr.load_manifest("proj_threads_01")
    assert final_m is not None
    assert len(final_m.error_details) > 0

    # Ensure no leftover temp files
    tmp_files = list(tmp_path.glob("**/*.tmp"))
    assert len(tmp_files) == 0


def test_issue_008_independent_projects_concurrency(tmp_path: Path):
    """Verify separate projects update independently without blocking each other."""
    mgr = ProjectManifestManager(storage_base_dir=tmp_path)

    def run_project_lifecycle(pid: str):
        req = TrainingVideoRequest(
            topic=f"Topic for {pid}",
            base_language="en-US",
            target_languages=["ar-SA"],
        )
        m = mgr.create_manifest(pid, req)
        m.status = "running"
        mgr.save_manifest(m)
        m.status = "completed"
        mgr.save_manifest(m)

    project_ids = [f"proj_indep_{i}" for i in range(8)]
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(run_project_lifecycle, pid) for pid in project_ids]
        for f in futures:
            f.result()

    for pid in project_ids:
        loaded = mgr.load_manifest(pid)
        assert loaded is not None
        assert loaded.status == "completed"

    projects_list = mgr.list_projects()
    assert len(projects_list) == 8
