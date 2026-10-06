"""Abstract base class and eligibility rules for talking-head avatar video synthesis."""

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


def is_avatar_eligible(scene: Union[SceneDraft, LocalizedScene]) -> bool:
    """
    Determine if a scene is eligible for talking-head avatar synthesis.
    
    Returns:
        True if scene_type is 'presenter', 'intro', 'outro', or 'recap'.
        False for visual demos, slides, or explanations that rely purely on graphical assets.
    """
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
        audio_path: Path,
        avatar_id: Optional[str] = None,
    ) -> str:
        """
        Submit an avatar video generation task driven by scene audio.
        
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
        audio_path: Path,
        destination_path: Path,
        avatar_id: Optional[str] = None,
        poll_interval: Optional[float] = None,
        timeout_seconds: Optional[int] = None,
    ) -> AvatarVideoAsset:
        """
        Template method orchestrating full avatar video creation:
        submit -> poll -> retrieve -> probe duration.
        """
        avatar_name = avatar_id or settings.HEYGEN_DEFAULT_AVATAR_ID
        poll_wait = poll_interval or settings.HEYGEN_POLL_INTERVAL_SECONDS
        timeout = timeout_seconds or settings.HEYGEN_JOB_TIMEOUT_SECONDS

        destination_path.parent.mkdir(parents=True, exist_ok=True)

        logger.info(
            "Submitting avatar job for scene '%s' (%s, avatar=%s)",
            scene_id, locale, avatar_name
        )

        job_id = self.submit_avatar_job(
            scene_id=scene_id,
            locale=locale,
            audio_path=audio_path,
            avatar_id=avatar_name,
        )

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
                
                # Probe duration if possible, else default to audio duration
                try:
                    dur = get_audio_duration(final_path)
                except Exception:
                    try:
                        dur = get_audio_duration(audio_path)
                    except Exception:
                        dur = 0.0

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
                raise RuntimeError(f"Avatar job {job_id} failed: {err_msg}")

            time.sleep(poll_wait)
