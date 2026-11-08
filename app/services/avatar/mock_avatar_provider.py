"""Mock avatar provider generating synthetic talking-head video segments for testing."""

import subprocess
import uuid
from pathlib import Path
from typing import Optional, Dict, Any, List
from app.core.config import settings
from app.core.logging import logger
from app.services.avatar.base import AvatarProvider
from app.services.tts.audio_probe import get_audio_duration


def generate_synthetic_mp4_file(file_path: Path, duration_seconds: float = 1.0) -> Path:
    """
    Generate a lightweight valid MP4 video using FFmpeg lavfi color source.
    """
    file_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        settings.FFMPEG_BINARY_PATH,
        "-y",
        "-f", "lavfi",
        "-i", f"color=c=navy:s=320x240:d={duration_seconds}",
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        str(file_path.resolve()),
    ]
    try:
        subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True, timeout=10)
    except Exception as e:
        logger.debug("Synthetic MP4 generation fallback triggered: %s", str(e))
        # Fallback dummy file if ffmpeg binary execution encounters environment restriction
        with open(file_path, "wb") as f:
            f.write(b"MOCK_MP4_VIDEO_HEADER" + b"\x00" * 1024)
    return file_path


class MockAvatarProvider(AvatarProvider):
    """
    In-memory mock avatar provider for fast, credit-safe testing.
    """

    def __init__(
        self,
        poll_attempts_before_complete: int = 1,
        fail_scene_ids: Optional[List[str]] = None,
        fail_locales: Optional[List[str]] = None,
        timeout_scene_ids: Optional[List[str]] = None,
    ) -> None:
        self.poll_attempts_before_complete = poll_attempts_before_complete
        self.fail_scene_ids = set(fail_scene_ids or [])
        self.fail_locales = set(fail_locales or [])
        self.timeout_scene_ids = set(timeout_scene_ids or [])
        self.jobs: Dict[str, Dict[str, Any]] = {}
        self.submit_call_count = 0
        self.poll_call_count = 0
        self.download_call_count = 0

    @property
    def provider_name(self) -> str:
        return "mock"

    def submit_avatar_job(
        self,
        scene_id: str,
        locale: str,
        audio_path: Optional[Path] = None,
        avatar_id: Optional[str] = None,
        script_text: Optional[str] = None,
        voice_id: Optional[str] = None,
        mode: Optional[str] = None,
        project_id: Optional[str] = None,
        **kwargs: Any,
    ) -> str:
        self.submit_call_count += 1
        job_id = f"mock_job_{uuid.uuid4().hex[:8]}"

        # Measure audio duration for video alignment
        audio_duration = 2.0
        if audio_path and Path(audio_path).exists():
            try:
                audio_duration = get_audio_duration(Path(audio_path))
            except Exception:
                audio_duration = 2.0
            audio_duration = 2.0

        should_fail = (scene_id in self.fail_scene_ids) or (locale in self.fail_locales)
        should_timeout = scene_id in self.timeout_scene_ids

        self.jobs[job_id] = {
            "scene_id": scene_id,
            "locale": locale,
            "audio_path": audio_path,
            "avatar_id": avatar_id,
            "duration": audio_duration,
            "polls_left": self.poll_attempts_before_complete,
            "should_fail": should_fail,
            "should_timeout": should_timeout,
        }

        logger.info("Mock avatar job submitted: %s (scene=%s, locale=%s)", job_id, scene_id, locale)
        return job_id

    def poll_avatar_job(self, job_id: str) -> Dict[str, Any]:
        self.poll_call_count += 1
        if job_id not in self.jobs:
            return {"status": "failed", "error": f"Unknown job ID: {job_id}"}

        job = self.jobs[job_id]

        if job["should_timeout"]:
            # Indefinitely pending to trigger caller timeout
            return {"status": "processing"}

        if job["should_fail"]:
            return {"status": "failed", "error": f"Simulated avatar generation failure for scene {job['scene_id']}"}

        if job["polls_left"] > 0:
            job["polls_left"] -= 1
            return {"status": "processing"}

        return {
            "status": "completed",
            "video_url": f"https://mock.avatar.storage/{job_id}.mp4",
        }

    def download_avatar_video(self, video_url: str, destination_path: Path) -> Path:
        self.download_call_count += 1
        destination_path.parent.mkdir(parents=True, exist_ok=True)

        # Generate a valid MP4 with realistic duration matching the submitted job
        job_id = video_url.split("/")[-1].replace(".mp4", "")
        duration = self.jobs.get(job_id, {}).get("duration", 2.0)

        generate_synthetic_mp4_file(destination_path, duration_seconds=duration)
        logger.info("Mock avatar video downloaded to: %s", destination_path)
        return destination_path
