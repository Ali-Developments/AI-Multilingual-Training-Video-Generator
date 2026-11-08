"""Local SadTalker Avatar Provider for Free Talking-Head Video Synthesis.

Executes SadTalker in an isolated Python environment via controlled subprocess,
animating a project-owned portrait image driven by scene narration audio.
"""

import json
import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from typing import Optional, Dict, Any, List

from app.core.config import settings
from app.core.logging import logger
from app.models.schemas import AvatarVideoAsset
from app.services.avatar.base import AvatarProvider
from app.services.tts.audio_probe import get_audio_duration


class SadTalkerError(Exception):
    """Base exception for SadTalker provider operations."""
    pass


class SadTalkerConfigurationError(SadTalkerError):
    """Configuration error: missing environment, checkpoints, or source portrait."""
    pass


class SadTalkerInferenceError(SadTalkerError):
    """Runtime error during SadTalker model inference execution."""
    pass


class SadTalkerProvider(AvatarProvider):
    """
    Subprocess-isolated local provider for SadTalker talking-head animation.
    
    Guarantees:
    - Never imports SadTalker into main application environment
    - Validates source portrait and scene audio before execution
    - Executes via safe subprocess argument lists (no shell=True)
    - Enforces timeout and output verification
    """

    def __init__(
        self,
        python_path: Optional[Path] = None,
        sadtalker_root: Optional[Path] = None,
        checkpoint_dir: Optional[Path] = None,
        default_source_image: Optional[Path] = None,
        timeout_seconds: Optional[int] = None,
        size: Optional[int] = None,
        preprocess: Optional[str] = None,
        still_mode: Optional[bool] = None,
    ) -> None:
        self.python_path = self._resolve_path(Path(python_path or settings.SADTALKER_PYTHON_PATH))
        self.sadtalker_root = self._resolve_path(Path(sadtalker_root or settings.SADTALKER_ROOT))
        self.checkpoint_dir = self._resolve_path(Path(checkpoint_dir or settings.SADTALKER_CHECKPOINT_PATH))
        self.default_source_image = self._resolve_path(Path(default_source_image or settings.SADTALKER_DEFAULT_SOURCE_IMAGE))
        self.timeout_seconds = timeout_seconds or settings.SADTALKER_TIMEOUT_SECONDS
        self.size = size or settings.SADTALKER_SIZE
        self.preprocess = preprocess or settings.SADTALKER_PREPROCESS
        self.still_mode = still_mode if still_mode is not None else settings.SADTALKER_STILL
        self._jobs: Dict[str, Dict[str, Any]] = {}

    @staticmethod
    def _resolve_path(candidate: Path) -> Path:
        """Resolve candidate path checking cwd and parent directories."""
        if candidate.exists():
            return candidate.resolve()
        parent_candidate = Path("..") / candidate
        if parent_candidate.exists():
            return parent_candidate.resolve()
        return candidate.resolve()

    @property
    def provider_name(self) -> str:
        return "sadtalker"

    def check_readiness(self) -> Dict[str, Any]:
        """
        Verify all local components required for SadTalker execution.
        Does not execute inference or consume compute.
        """
        python_ok = self.python_path.exists() and self.python_path.is_file()
        root_ok = self.sadtalker_root.exists() and (self.sadtalker_root / "inference.py").is_file()
        
        # Check for model checkpoints
        checkpoints_ok = False
        checkpoint_files = []
        if self.checkpoint_dir.exists() and self.checkpoint_dir.is_dir():
            checkpoint_files = [f.name for f in self.checkpoint_dir.iterdir() if f.suffix in (".safetensors", ".pth", ".tar")]
            # Minimum requirements: either safetensors or pth models
            checkpoints_ok = len(checkpoint_files) > 0

        # Check source portrait image
        image_ok = self.default_source_image.exists() and self.default_source_image.stat().st_size > 0

        # Check ffmpeg availability
        ffmpeg_ok = bool(shutil.which("ffmpeg") or Path(settings.FFMPEG_BINARY_PATH).exists())

        all_ready = python_ok and root_ok and checkpoints_ok and image_ok and ffmpeg_ok

        details = {
            "ready": all_ready,
            "python_executable": str(self.python_path),
            "python_exists": python_ok,
            "sadtalker_root": str(self.sadtalker_root),
            "root_exists": root_ok,
            "checkpoint_dir": str(self.checkpoint_dir),
            "checkpoints_found": checkpoint_files,
            "checkpoints_ok": checkpoints_ok,
            "default_source_image": str(self.default_source_image),
            "source_image_ok": image_ok,
            "ffmpeg_available": ffmpeg_ok,
            "device": "cuda" if os.environ.get("CUDA_VISIBLE_DEVICES") != "-1" else "cpu",
        }
        return details

    validate_environment = check_readiness

    def resolve_source_image(self, avatar_id: Optional[str] = None) -> Path:
        """Resolve valid source portrait image or raise configuration error."""
        if avatar_id and Path(avatar_id).exists() and Path(avatar_id).is_file():
            return Path(avatar_id).resolve()
        
        # Check configured portrait
        if self.default_source_image.exists() and self.default_source_image.is_file():
            return self.default_source_image

        raise SadTalkerConfigurationError(
            f"SadTalker source portrait image not found at '{self.default_source_image}'. "
            "Please provide a project-owned portrait at assets/avatars/local_presenter.png."
        )

    def build_inference_command(
        self,
        audio_path: Path,
        source_image: Path,
        result_dir: Path,
        cpu_only: bool = False,
    ) -> List[str]:
        """Construct safe subprocess argument list for SadTalker inference.py."""
        cmd = [
            str(self.python_path),
            str(self.sadtalker_root / "inference.py"),
            "--driven_audio", str(audio_path),
            "--source_image", str(source_image),
            "--result_dir", str(result_dir),
            "--checkpoint_dir", str(self.checkpoint_dir),
            "--size", str(self.size),
            "--preprocess", self.preprocess,
            "--batch_size", "2",
        ]
        if self.still_mode:
            cmd.append("--still")
        if cpu_only:
            cmd.append("--cpu")
        return cmd

    def submit_avatar_job(
        self,
        scene_id: str,
        locale: str,
        audio_path: Optional[Path] = None,
        avatar_id: Optional[str] = None,
        **kwargs: Any,
    ) -> str:
        """
        Execute local SadTalker synthesis for scene audio and cache result.
        Conforms to AvatarProvider contract.
        """
        if not audio_path:
            raise SadTalkerConfigurationError("SadTalker requires audio_path for audio-driven animation.")
        audio_file = Path(audio_path).resolve()
        if not audio_file.exists() or audio_file.stat().st_size == 0:
            raise SadTalkerConfigurationError(f"Audio file missing or empty: {audio_file}")

        source_image = self.resolve_source_image(avatar_id)

        job_id = f"sadtalker_{scene_id}_{uuid.uuid4().hex[:8]}"
        temp_dir = (Path(settings.SADTALKER_RESULT_DIR) / job_id).resolve()
        temp_dir.mkdir(parents=True, exist_ok=True)

        cmd = self.build_inference_command(
            audio_path=audio_file,
            source_image=source_image,
            result_dir=temp_dir,
        )

        logger.info(
            "Executing local SadTalker inference for scene '%s' (%s) with image '%s'",
            scene_id, locale, source_image.name
        )

        start_time = time.time()
        try:
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=str(self.sadtalker_root),
                timeout=self.timeout_seconds,
            )
        except subprocess.TimeoutExpired as te:
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise TimeoutError(
                f"SadTalker inference timed out after {self.timeout_seconds} seconds for scene '{scene_id}'"
            ) from te

        elapsed = time.time() - start_time

        if res.returncode != 0:
            error_details = (res.stderr or res.stdout or "").strip()[-500:]
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise SadTalkerInferenceError(
                f"SadTalker inference failed with exit code {res.returncode}: {error_details}"
            )

        # Locate generated MP4
        # SadTalker prints 'The generated video is named: <path>' or 'The generated video is named <path>'
        produced_mp4 = None
        potential_paths: List[Path] = []
        for line in res.stdout.splitlines():
            if "The generated video is named" in line:
                raw_path = line.split("The generated video is named")[-1].lstrip(": ").strip()
                p1 = Path(raw_path)
                p2 = self.sadtalker_root / raw_path
                if p1.exists() and p1.is_file():
                    potential_paths.append(p1)
                elif p2.exists() and p2.is_file():
                    potential_paths.append(p2)

        if potential_paths:
            full_candidates = [p for p in potential_paths if "_full" in p.name or p.name == f"{temp_dir.name}.mp4"]
            produced_mp4 = full_candidates[-1] if full_candidates else potential_paths[-1]

        if not produced_mp4:
            candidates = list(temp_dir.rglob("*.mp4")) or list(temp_dir.parent.glob(f"{temp_dir.name}*.mp4"))
            if not candidates:
                root_temp = self.sadtalker_root / "storage" / "sadtalker_temp"
                if root_temp.exists():
                    candidates = list(root_temp.rglob("*.mp4"))
            if candidates:
                full_cand = [c for c in candidates if "_full" in c.name or c.name == f"{temp_dir.name}.mp4"]
                produced_mp4 = full_cand[-1] if full_cand else candidates[-1]

        if not produced_mp4 or not produced_mp4.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise SadTalkerInferenceError(
                f"SadTalker reported success but produced no MP4 in '{temp_dir}'. stdout: {res.stdout[-300:]}"
            )


        logger.info(
            "SadTalker successfully rendered scene '%s' in %.1fs -> %s (%d bytes)",
            scene_id, elapsed, produced_mp4.name, produced_mp4.stat().st_size
        )

        self._jobs[job_id] = {
            "status": "completed",
            "video_path": str(produced_mp4.resolve()),
            "elapsed_seconds": elapsed,
            "scene_id": scene_id,
            "locale": locale,
            "avatar_id": str(source_image.name),
        }
        return job_id

    def poll_avatar_job(self, job_id: str) -> Dict[str, Any]:
        """Poll job status for SadTalker."""
        if job_id not in self._jobs:
            return {"status": "failed", "error": f"Unknown SadTalker job ID: {job_id}"}
        
        job = self._jobs[job_id]
        return {
            "status": job["status"],
            "video_url": f"file://{job['video_path']}",
            "inference_time_seconds": job.get("elapsed_seconds", 0.0),
        }

    def download_avatar_video(self, video_url: str, destination_path: Path) -> Path:
        """Move/copy rendered local video to destination path."""
        src_path = Path(video_url.replace("file://", ""))
        destination_path = Path(destination_path).resolve()
        destination_path.parent.mkdir(parents=True, exist_ok=True)

        if not src_path.exists():
            raise SadTalkerInferenceError(f"Rendered video missing at source path: {src_path}")

        shutil.copy2(src_path, destination_path)
        logger.info("Copied SadTalker avatar to destination: %s", destination_path)
        return destination_path
