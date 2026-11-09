"""Abstract base class and eligibility rules for talking-head avatar video synthesis."""

import json
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional, Union, Dict, Any
from app.core.config import settings
from app.core.logging import logger
from app.models.schemas import (
    SceneDraft,
    LocalizedScene,
    AvatarVideoAsset,
)
from app.services.tts.audio_probe import get_audio_duration

# Scene types that qualify for talking-head avatar rendering
AVATAR_ELIGIBLE_SCENE_TYPES = {
    "presenter",
    "intro",
    "outro",
    "recap",
}

# Layout types that actively feature the talking-head presenter
PRESENTER_ACTIVE_LAYOUTS = {
    "presenter_left_visual_right",
    "presenter_right_visual_left",
    "presenter_picture_in_picture",
    "presenter_center_with_overlays",
    "presenter_split",
    "presenter_overlay",
    "presenter_full",
    "pip",
}


def is_avatar_eligible(scene: Union[SceneDraft, LocalizedScene]) -> bool:
    """
    Determine if a scene is eligible for talking-head avatar synthesis.
    
    Returns:
        True if avatar_enabled is True and scene features a presenter layout or presenter scene/media type.
        False for standalone visual demos, broll, slides, diagrams, quizzes, or when avatar_enabled is False.
    """
    if getattr(scene, "avatar_enabled", True) is False:
        return False

    layout_type = getattr(scene, "layout_type", None)
    if layout_type is not None:
        lt = str(layout_type.value if hasattr(layout_type, "value") else layout_type).strip().lower()
        if lt in PRESENTER_ACTIVE_LAYOUTS:
            return True
        if lt in ("media_full", "media_with_overlay", "title_card", "quiz_card"):
            return False

    media_type = getattr(scene, "media_type", None)
    if media_type is not None:
        mt = str(media_type.value if hasattr(media_type, "value") else media_type).strip().lower()
        if mt in ("presenter", "outro"):
            return True
        if mt in ("broll", "motion_visual", "uploaded_video", "uploaded_image", "diagram", "quiz", "title"):
            return False

    stype = (scene.scene_type or "presenter").strip().lower()
    return stype in AVATAR_ELIGIBLE_SCENE_TYPES


class AvatarProvider(ABC):
    """Abstract interface defining talking-head avatar video providers."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Return unique provider identifier (heygen, mock)."""
        pass

    @abstractmethod
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
        """
        Submit an avatar video generation task driven by scene audio or script.
        
        Returns:
            job_id: Unique task identifier.
        """
        pass

    @abstractmethod
    def poll_avatar_job(self, job_id: str) -> Dict[str, Any]:
        """
        Poll avatar generation task status.
        
        Returns:
            Dict containing status ('pending', 'processing', 'completed', 'failed')
            and 'video_url' when completed.
        """
        pass

    @abstractmethod
    def download_avatar_video(self, video_url: str, destination_path: Path) -> Path:
        """Download rendered avatar video file to local filesystem."""
        pass

    def generate_scene_avatar(
        self,
        scene_id: str,
        locale: str,
        audio_path: Optional[Path],
        destination_path: Path,
        avatar_id: Optional[str] = None,
        poll_interval: Optional[float] = None,
        timeout_seconds: Optional[int] = None,
        force_regenerate: bool = False,
        script_text: Optional[str] = None,
        voice_id: Optional[str] = None,
        mode: Optional[str] = None,
        project_id: Optional[str] = None,
    ) -> AvatarVideoAsset:
        """
        Template method orchestrating full avatar video creation:
        submit -> poll -> retrieve -> technical validation -> duration probe.
        Persists job_id immediately after submission to enable safe resume without duplicate paid calls.
        """
        avatar_name = avatar_id or settings.HEYGEN_DEFAULT_AVATAR_ID
        poll_wait = poll_interval or settings.HEYGEN_POLL_INTERVAL_SECONDS
        timeout = timeout_seconds or settings.HEYGEN_JOB_TIMEOUT_SECONDS

        destination_path.parent.mkdir(parents=True, exist_ok=True)
        job_file = destination_path.with_suffix(".job.json")
        job_id = None

        if not force_regenerate and job_file.exists():
            try:
                saved_info = json.loads(job_file.read_text(encoding="utf-8"))
                saved_job_id = saved_info.get("job_id")
                saved_prov = saved_info.get("provider") or "heygen"
                if (
                    saved_job_id
                    and saved_prov.strip().lower() == self.provider_name.strip().lower()
                    and saved_info.get("status") in ("submitted", "pending", "processing", "completed")
                ):
                    logger.info(
                        "Found persisted avatar job ID '%s' for scene '%s' (%s); polling existing job instead of resubmitting.",
                        saved_job_id, scene_id, self.provider_name
                    )
                    job_id = saved_job_id
            except Exception as ex:
                logger.warning("Could not read existing job file '%s': %s", job_file, ex)

        if not job_id:
            logger.info(
                "Submitting avatar job for scene '%s' (%s, avatar=%s, mode=%s)",
                scene_id, locale, avatar_name, mode or "audio"
            )
            job_id = self.submit_avatar_job(
                scene_id=scene_id,
                locale=locale,
                audio_path=audio_path,
                avatar_id=avatar_name,
                script_text=script_text,
                voice_id=voice_id,
                mode=mode,
                project_id=project_id,
            )
            try:
                job_data = {
                    "job_id": job_id,
                    "scene_id": scene_id,
                    "locale": locale,
                    "avatar_id": avatar_name,
                    "provider": self.provider_name,
                    "mode": mode or "audio",
                    "submitted_at": time.time(),
                    "status": "processing",
                }
                job_file.write_text(json.dumps(job_data, indent=2), encoding="utf-8")
                logger.info("Persisted avatar job ID '%s' to '%s'", job_id, job_file)
            except Exception as ex:
                logger.warning("Failed to persist job file '%s': %s", job_file, ex)

        start_time = time.time()
        while True:
            if time.time() - start_time > timeout:
                raise TimeoutError(
                    f"Avatar generation timed out for scene '{scene_id}' after {timeout} seconds (Job ID: {job_id})."
                )

            status_info = self.poll_avatar_job(job_id)
            current_status = status_info.get("status", "pending")

            if current_status == "completed":
                video_url = status_info.get("video_url")
                if not video_url:
                    raise RuntimeError(f"Avatar job {job_id} reported completed but returned no video_url.")
                
                final_path = self.download_avatar_video(video_url, destination_path)
                
                # Perform technical validation with ffprobe
                try:
                    from app.services.composition.ffmpeg_utils import validate_video_file, get_video_duration
                    probe_meta = validate_video_file(
                        final_path,
                        min_duration=0.5,
                        require_video=True,
                        require_audio=False,
                    )
                    dur = probe_meta["duration"]
                    logger.info(
                        "Technical validation passed for avatar '%s': %dx%d, %.2fs, codec=%s",
                        scene_id, probe_meta["width"], probe_meta["height"], dur, probe_meta["video_codec"]
                    )
                except Exception as ex:
                    logger.warning("ffprobe stream validation fallback: %s", ex)
                    try:
                        dur = get_video_duration(final_path)
                    except Exception:
                        try:
                            dur = get_audio_duration(audio_path) if audio_path else 0.0
                        except Exception:
                            dur = 0.0

                try:
                    if job_file.exists():
                        completed_data = json.loads(job_file.read_text(encoding="utf-8"))
                        completed_data["status"] = "completed"
                        completed_data["completed_at"] = time.time()
                        completed_data["duration_seconds"] = dur
                        completed_data["inference_time_seconds"] = status_info.get(
                            "inference_time_seconds",
                            round(completed_data["completed_at"] - completed_data.get("submitted_at", completed_data["completed_at"]), 2)
                        )
                        job_file.write_text(json.dumps(completed_data, indent=2), encoding="utf-8")
                except Exception:
                    pass

                return AvatarVideoAsset(
                    scene_id=scene_id,
                    locale=locale,
                    provider=self.provider_name,
                    job_id=job_id,
                    video_path=str(final_path.resolve()),
                    duration_seconds=dur,
                    status="completed",
                    avatar_id=avatar_name,
                )

            elif current_status == "failed":
                err_msg = status_info.get("error", "Unknown provider failure")
                try:
                    if job_file.exists():
                        failed_data = json.loads(job_file.read_text(encoding="utf-8"))
                        failed_data["status"] = "failed"
                        failed_data["error"] = err_msg
                        job_file.write_text(json.dumps(failed_data, indent=2), encoding="utf-8")
                except Exception:
                    pass
                raise RuntimeError(f"Avatar job {job_id} failed: {err_msg}")

            time.sleep(poll_wait)
