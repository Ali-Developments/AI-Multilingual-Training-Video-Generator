"""Avatar high-level service coordinating talking-head video synthesis per scene."""

from pathlib import Path
from typing import Optional, Dict
from app.core.config import settings
from app.core.logging import logger
from app.models.schemas import (
    LocalizedScript,
    LocalizationBundle,
    LocalizedAudioTrack,
    AvatarVideoAsset,
    LocalizedAvatarTrack,
)
from app.services.avatar.base import AvatarProvider, is_avatar_eligible
from app.services.avatar.factory import get_avatar_provider
from app.services.tts.audio_probe import get_audio_duration
from app.core.caching import is_avatar_asset_valid, save_asset_metadata, hash_file


class AvatarService:
    """
    High-level avatar rendering service coordinating scene-level eligibility,
    audio-driven lip-sync alignment, and asset storage.
    """

    def __init__(
        self,
        provider: Optional[AvatarProvider] = None,
        output_base_dir: Optional[Path] = None,
    ) -> None:
        self.provider = provider or get_avatar_provider()
        self.output_base_dir = output_base_dir or settings.STORAGE_PATH

    def generate_locale_avatars(
        self,
        script: LocalizedScript,
        audio_track: LocalizedAudioTrack,
        project_id: str,
        avatar_id: Optional[str] = None,
        force_regenerate: bool = False,
    ) -> LocalizedAvatarTrack:
        """
        Generate talking-head video segments for all eligible scenes in a localized script.
        """
        locale = script.locale
        avatar_dir = self.output_base_dir / project_id / "avatars" / locale
        avatar_dir.mkdir(parents=True, exist_ok=True)

        # Index available scene audio assets
        audio_map = {
            a.scene_id: a for a in audio_track.scene_audio if a.status == "completed"
        }

        scene_avatars = []
        for scene in script.scenes:
            # 1. Eligibility Check
            if not is_avatar_eligible(scene):
                logger.info("Scene '%s' (%s) is not eligible for avatar; skipping.", scene.scene_id, scene.scene_type)
                scene_avatars.append(
                    AvatarVideoAsset(
                        scene_id=scene.scene_id,
                        locale=locale,
                        provider=self.provider.provider_name,
                        job_id="skipped_ineligible",
                        video_path=None,
                        duration_seconds=0.0,
                        status="skipped",
                        avatar_id=None,
                    )
                )
                continue

            # 2. Verify Audio Ground Truth
            audio_asset = audio_map.get(scene.scene_id)
            if not audio_asset or not Path(audio_asset.audio_path).exists():
                logger.error("Scene '%s' has no completed audio asset; cannot synthesize avatar.", scene.scene_id)
                scene_avatars.append(
                    AvatarVideoAsset(
                        scene_id=scene.scene_id,
                        locale=locale,
                        provider=self.provider.provider_name,
                        job_id="failed_no_audio",
                        video_path=None,
                        duration_seconds=0.0,
                        status="failed",
                        avatar_id=avatar_id,
                        error="Missing completed TTS audio asset required for audio-driven avatar.",
                    )
                )
                continue

            dest_file = avatar_dir / f"{scene.scene_id}.mp4"

            # 3. Content-aware idempotency check: only reuse if input audio hash matches
            audio_file_path = Path(audio_asset.audio_path)
            if (
                not force_regenerate
                and dest_file.exists()
                and dest_file.stat().st_size > 0
                and is_avatar_asset_valid(
                    avatar_video_path=dest_file,
                    audio_path=audio_file_path,
                    expected_provider=self.provider.provider_name,
                )
            ):
                try:
                    dur = get_audio_duration(dest_file)
                    logger.info("Reusing existing validated avatar video for scene '%s' (%s, %.2fs)", scene.scene_id, locale, dur)
                    scene_avatars.append(
                        AvatarVideoAsset(
                            scene_id=scene.scene_id,
                            locale=locale,
                            provider=self.provider.provider_name,
                            job_id="cached",
                            video_path=str(dest_file.resolve()),
                            duration_seconds=dur,
                            status="completed",
                            avatar_id=avatar_id or settings.HEYGEN_DEFAULT_AVATAR_ID,
                        )
                    )
                    continue
                except Exception as ex:
                    logger.warning("Existing avatar file '%s' corrupted (%s); regenerating.", dest_file, str(ex))

            # 4. Generate avatar video with failure isolation
            try:
                asset = self.provider.generate_scene_avatar(
                    scene_id=scene.scene_id,
                    locale=locale,
                    audio_path=audio_file_path,
                    destination_path=dest_file,
                    avatar_id=avatar_id,
                    force_regenerate=force_regenerate,
                    script_text=scene.narration,
                    voice_id=getattr(scene, "voice_id", None),
                    mode=getattr(settings, "HEYGEN_MODE", "audio"),
                    project_id=project_id,
                )
                if dest_file.exists() and dest_file.stat().st_size > 0:
                    save_asset_metadata(
                        dest_file,
                        {
                            "scene_id": scene.scene_id,
                            "locale": locale,
                            "audio_hash": hash_file(audio_file_path),
                            "duration": asset.duration_seconds,
                            "provider": self.provider.provider_name,
                            "avatar_id": avatar_id or getattr(self.provider, "default_source_image", None),
                        },
                    )
                scene_avatars.append(asset)
            except Exception as e:
                logger.error("Avatar generation failed for scene '%s': %s", scene.scene_id, str(e))
                scene_avatars.append(
                    AvatarVideoAsset(
                        scene_id=scene.scene_id,
                        locale=locale,
                        provider=self.provider.provider_name,
                        job_id="failed_exception",
                        video_path=None,
                        duration_seconds=0.0,
                        status="failed",
                        avatar_id=avatar_id,
                        error=str(e),
                    )
                )

        completed_count = sum(1 for a in scene_avatars if a.status == "completed")
        failed_count = sum(1 for a in scene_avatars if a.status == "failed")

        if failed_count == 0:
            track_status = "completed"
        elif completed_count > 0:
            track_status = "partial"
        else:
            track_status = "failed"

        return LocalizedAvatarTrack(
            locale=locale,
            scene_avatars=scene_avatars,
            status=track_status,
            metadata={
                "provider": self.provider.provider_name,
                "total_scenes": len(script.scenes),
                "completed_count": completed_count,
                "failed_count": failed_count,
            },
        )

    def generate_bundle_avatars(
        self,
        bundle: LocalizationBundle,
        audio_tracks: Dict[str, LocalizedAudioTrack],
        project_id: str,
        avatar_id: Optional[str] = None,
        force_regenerate: bool = False,
    ) -> Dict[str, LocalizedAvatarTrack]:
        """
        Generate avatar tracks for all localized scripts in a bundle with failure isolation.
        """
        avatar_tracks = {}
        for locale, script in bundle.localized_scripts.items():
            audio_track = audio_tracks.get(locale)
            if not audio_track:
                logger.warning("No audio track found for locale '%s'; skipping avatar generation.", locale)
                avatar_tracks[locale] = LocalizedAvatarTrack(
                    locale=locale,
                    scene_avatars=[],
                    status="failed",
                    metadata={"error": "Missing audio track for locale"},
                )
                continue

            try:
                track = self.generate_locale_avatars(
                    script=script,
                    audio_track=audio_track,
                    project_id=project_id,
                    avatar_id=avatar_id,
                    force_regenerate=force_regenerate,
                )
                avatar_tracks[locale] = track
            except Exception as e:
                logger.error("Failed to generate avatar track for locale '%s': %s", locale, str(e))
                avatar_tracks[locale] = LocalizedAvatarTrack(
                    locale=locale,
                    scene_avatars=[],
                    status="failed",
                    metadata={"error": str(e)},
                )

        return avatar_tracks
