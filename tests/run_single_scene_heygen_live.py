"""Single-Scene Live HeyGen Test Execution Script (Scene 1 ONLY).

STRICT SCOPE:
- Target: scene_1 ONLY (Arabic, ar-SA)
- Avatar: Brody (469ba809c9f6441ba74a580058d41c4b)
- Audio: Existing uploaded HeyGen CDN asset URL (50,112 bytes, ~8.35s)
- Max paid submissions: EXACTLY 1. If job ID exists, resumes polling.
- Persists scene_1.job.json immediately upon submission.
- Probes downloaded MP4 with ffprobe.
- scene_5 is strictly untouched.
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from app.core.config import settings
from app.services.avatar.heygen_provider import HeyGenProvider
from app.services.avatar.base import is_avatar_eligible
from app.services.tts.audio_probe import get_audio_duration


def run_single_scene_live():
    print("==================================================")
    print("STARTING AUTHORIZED SINGLE-SCENE HEYGEN LIVE TEST")
    print("==================================================")

    # 1. Verify Configuration & Environment
    print(f"ENABLE_LIVE_HEYGEN: {settings.ENABLE_LIVE_HEYGEN}")
    print(f"ENABLE_LIVE_API_TESTS: {settings.ENABLE_LIVE_API_TESTS}")
    print(f"DEFAULT_AVATAR_PROVIDER: {settings.DEFAULT_AVATAR_PROVIDER}")
    print(f"HEYGEN_DEFAULT_AVATAR_ID: {settings.HEYGEN_DEFAULT_AVATAR_ID}")

    if not settings.ENABLE_LIVE_HEYGEN:
        print("ERROR: ENABLE_LIVE_HEYGEN is not True. Aborting.")
        sys.exit(1)

    if settings.ENABLE_LIVE_API_TESTS:
        print("WARNING: ENABLE_LIVE_API_TESTS should remain False for application runtime.")

    # 2. Verify Target Scene Paths
    project_id = "proj_real_e2e_phishing"
    locale = "ar-SA"
    scene_id = "scene_1"
    base_storage = Path("storage/projects") / project_id

    audio_file = base_storage / "audio" / locale / f"{scene_id}.mp3"
    asset_url_file = base_storage / "audio" / locale / f"{scene_id}.asset_url"
    dest_dir = base_storage / "avatars" / locale
    dest_dir.mkdir(parents=True, exist_ok=True)

    dest_mp4 = dest_dir / f"{scene_id}.mp4"
    job_file = dest_dir / f"{scene_id}.job.json"

    assert audio_file.exists(), f"Audio file not found: {audio_file}"
    audio_duration = get_audio_duration(audio_file)
    print(f"\nTarget Audio: {audio_file}")
    print(f"Audio Duration: {audio_duration:.2f} seconds ({audio_file.stat().st_size} bytes)")

    # 3. Audio Asset URL Verification
    assert asset_url_file.exists(), f"Asset URL file not found: {asset_url_file}"
    audio_cdn_url = asset_url_file.read_text(encoding="utf-8").strip()
    print(f"Audio CDN URL: {audio_cdn_url}")

    # 4. Instantiate HeyGen Provider
    provider = HeyGenProvider()

    # 5. Check Idempotency & In-Flight Jobs
    existing_job_id = None
    if job_file.exists():
        try:
            saved_data = json.loads(job_file.read_text(encoding="utf-8"))
            saved_job = saved_data.get("job_id")
            saved_status = saved_data.get("status")
            print(f"Found existing job file: {job_file} (status: {saved_status}, job_id: {saved_job})")
            if saved_job and saved_status in ("submitted", "pending", "processing", "completed"):
                existing_job_id = saved_job
                print(f"Resuming existing job: {existing_job_id}")
        except Exception as ex:
            print(f"Warning reading job file: {ex}")

    # 6. Submission (at most ONE paid submission)
    if not existing_job_id:
        print("\n--- SUBMITTING VIDEO GENERATION TO HEYGEN (1 PAID ACTION) ---")
        job_id = provider.submit_avatar_job(
            scene_id=scene_id,
            locale=locale,
            audio_path=audio_file,
            avatar_id="469ba809c9f6441ba74a580058d41c4b",
        )
        print(f"SUBMISSION SUCCESS! Job ID: {job_id}")

        # Persist IMMEDIATELY
        job_record = {
            "job_id": job_id,
            "scene_id": scene_id,
            "locale": locale,
            "avatar_id": "469ba809c9f6441ba74a580058d41c4b",
            "provider": "heygen",
            "audio_url": audio_cdn_url,
            "submitted_at": time.time(),
            "status": "processing",
        }
        job_file.write_text(json.dumps(job_record, indent=2), encoding="utf-8")
        assert job_file.exists(), "CRITICAL: Failed to write job.json file!"
        print(f"Persisted job record to: {job_file}")
        active_job_id = job_id
    else:
        active_job_id = existing_job_id

    # 7. Polling Loop
    print(f"\n--- POLLING HEYGEN FOR JOB: {active_job_id} ---")
    start_poll = time.time()
    timeout = 360.0
    poll_interval = 4.0
    completed_video_url = None

    while True:
        elapsed = time.time() - start_poll
        if elapsed > timeout:
            print(f"ERROR: Polling timed out after {elapsed:.1f}s")
            sys.exit(1)

        status_info = provider.poll_avatar_job(active_job_id)
        current_status = status_info.get("status", "processing")
        print(f"[{elapsed:5.1f}s] HeyGen status: {current_status}")

        if current_status == "completed":
            completed_video_url = status_info.get("video_url")
            print(f"Render completed! Video URL: {completed_video_url}")
            break
        elif current_status == "failed":
            err_msg = status_info.get("error", "Unknown HeyGen error")
            print(f"FATAL: HeyGen generation failed: {err_msg}")
            # Update job file
            job_record = json.loads(job_file.read_text(encoding="utf-8"))
            job_record["status"] = "failed"
            job_record["error"] = err_msg
            job_file.write_text(json.dumps(job_record, indent=2), encoding="utf-8")
            sys.exit(1)

        time.sleep(poll_interval)

    # 8. Download Completed Video
    print(f"\n--- DOWNLOADING RESULT TO: {dest_mp4} ---")
    provider.download_avatar_video(completed_video_url, dest_mp4)
    assert dest_mp4.exists(), f"Downloaded file missing: {dest_mp4}"
    file_size = dest_mp4.stat().st_size
    assert file_size > 50000, f"File size unexpectedly small: {file_size} bytes"
    print(f"Download successful! Size: {file_size:,} bytes")

    # Update job record
    job_record = json.loads(job_file.read_text(encoding="utf-8"))
    job_record["status"] = "completed"
    job_record["completed_at"] = time.time()
    job_record["video_path"] = str(dest_mp4.resolve())
    job_record["file_size_bytes"] = file_size
    job_file.write_text(json.dumps(job_record, indent=2), encoding="utf-8")

    # 9. Technical ffprobe Analysis
    print("\n--- RUNNING FFPROBE TECHNICAL VALIDATION ---")
    cmd = [
        "ffprobe",
        "-v", "error",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        str(dest_mp4),
    ]
    probe_res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    probe_data = json.loads(probe_res.stdout)

    video_stream = next((s for s in probe_data.get("streams", []) if s.get("codec_type") == "video"), None)
    audio_stream = next((s for s in probe_data.get("streams", []) if s.get("codec_type") == "audio"), None)
    fmt = probe_data.get("format", {})

    video_duration = float(fmt.get("duration", 0.0))
    duration_diff = abs(video_duration - audio_duration)

    width = video_stream.get("width") if video_stream else None
    height = video_stream.get("height") if video_stream else None
    video_codec = video_stream.get("codec_name") if video_stream else None
    fps_raw = video_stream.get("r_frame_rate", "0/1") if video_stream else "0/1"
    fps = eval(fps_raw) if "/" in fps_raw else float(fps_raw)
    audio_codec = audio_stream.get("codec_name") if audio_stream else "None"

    print(f"Video Duration: {video_duration:.2f}s")
    print(f"Audio Duration: {audio_duration:.2f}s")
    print(f"Duration Delta: {duration_diff:.2f}s")
    print(f"Resolution:     {width}x{height}")
    print(f"Video Codec:    {video_codec}")
    print(f"FPS:            {fps:.2f}")
    print(f"Audio Codec:    {audio_codec}")
    print(f"File Size:      {file_size:,} bytes")

    # 10. Optional Local FFmpeg Single-Scene Composition (Local Only)
    print("\n--- PERFORMING LOCAL SINGLE-SCENE COMPOSITION (NO HEYGEN CREDITS) ---")
    composed_dest = base_storage / "rendered" / locale / f"{scene_id}_composed.mp4"
    composed_dest.parent.mkdir(parents=True, exist_ok=True)

    # Remux/compose scene_1 with audio and clean H.264
    compose_cmd = [
        "ffmpeg", "-y",
        "-i", str(dest_mp4),
        "-c:v", "copy",
        "-c:a", "aac",
        "-b:a", "192k",
        "-movflags", "+faststart",
        str(composed_dest),
    ]
    subprocess.run(compose_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
    print(f"Local composition created at: {composed_dest} ({composed_dest.stat().st_size:,} bytes)")

    print("\n==================================================")
    print("SINGLE-SCENE HEYGEN LIVE TEST COMPLETE")
    print("==================================================")
    print(f"Canonical MP4 Path: {dest_mp4.resolve()}")
    print(f"Local Composed MP4: {composed_dest.resolve()}")
    print(f"VISUAL REVIEW REQUIRED: Open '{dest_mp4.resolve()}' to inspect Arabic lip-sync and visual quality.")


if __name__ == "__main__":
    run_single_scene_live()
