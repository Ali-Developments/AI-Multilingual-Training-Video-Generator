"""High-level video composition service orchestrating scene rendering and final concatenation."""

from pathlib import Path
from typing import Optional, Dict, List

from app.core.config import settings
from app.core.logging import logger
from app.models.schemas import (
    LocalizedScript,
    LocalizationBundle,
    LocalizedAudioTrack,
    LocalizedVisualTrack,
    LocalizedSubtitleTrack,
    LocalizedAvatarTrack,
    SceneCompositionAsset,
    FinalVideoAsset,
)
from app.services.composition.base import CompositionProvider
from app.services.composition.factory import get_composition_provider
from app.services.composition.ffmpeg_utils import get_video_duration


class CompositionService:
    """
    Coordinates end-to-end video assembly, per-scene layout rendering,
    and final multilingual video concatenation.
    """

    def __init__(
        self,
        provider: Optional[CompositionProvider] = None,
        output_base_dir: Optional[Path] = None,
    ) -> None:
        self.provider = provider or get_composition_provider()
        self.output_base_dir = output_base_dir or settings.STORAGE_PATH

    def compose_locale_scenes(
        self,
        script: LocalizedScript,
        audio_track: LocalizedAudioTrack,
        visual_track: Optional[LocalizedVisualTrack] = None,
        subtitle_track: Optional[LocalizedSubtitleTrack] = None,
        avatar_track: Optional[LocalizedAvatarTrack] = None,
        project_id: str = "default_project",
        force_regenerate: bool = False,
    ) -> List[SceneCompositionAsset]:
        """
        Render individual scene video files for each scene in a localized script.
        """
        locale = script.locale
        rendered_dir = self.output_base_dir / project_id / "rendered" / locale
        rendered_dir.mkdir(parents=True, exist_ok=True)

        audio_map = {
            a.scene_id: a
            for a in audio_track.scene_audio
            if a.status == "completed"
        }
        visual_map = {
            v.scene_id: v
            for v in (visual_track.scene_visuals if visual_track else [])
            if v.status == "completed"
        }
        sub_map = {
            s.scene_id: s
            for s in (subtitle_track.scene_subtitles if subtitle_track else [])
            if s.status == "completed"
        }
        avatar_map = {
            av.scene_id: av
            for av in (avatar_track.scene_avatars if avatar_track else [])
            if av.status == "completed"
        }

        scene_results: List[SceneCompositionAsset] = []

        for scene in script.scenes:
            out_file = rendered_dir / f"{scene.scene_id}.mp4"
            audio_asset = audio_map.get(scene.scene_id)
            if not audio_asset or not Path(audio_asset.audio_path).exists():
                logger.error("Missing audio asset for scene '%s'", scene.scene_id)
                scene_results.append(
                    SceneCompositionAsset(
                        scene_id=scene.scene_id,
                        locale=locale,
                        video_path="",
                        duration_seconds=0.0,
                        status="failed",
                        error="Missing audio asset",
                    )
                )
                continue

            duration = audio_asset.duration_seconds

            # Idempotency check: reuse existing valid MP4 video ONLY if duration matches current audio
            if not force_regenerate and out_file.exists() and out_file.stat().st_size > 0:
                measured = get_video_duration(out_file)
                if measured > 0 and abs(measured - duration) <= 0.5:
                    logger.info("Reusing existing rendered scene '%s' for locale '%s'", scene.scene_id, locale)
                    has_av = scene.scene_id in avatar_map
                    has_sub = scene.scene_id in sub_map
                    scene_results.append(
                        SceneCompositionAsset(
                            scene_id=scene.scene_id,
                            locale=locale,
                            video_path=str(out_file.resolve()),
                            duration_seconds=measured,
                            has_avatar=has_av,
                            has_subtitles=has_sub,
                            status="completed",
                        )
                    )
                    continue
                elif measured > 0:
                    logger.warning(
                        "Stale rendered scene asset detected for '%s' (file duration %.2fs != audio duration %.2fs). Re-rendering scene.",
                        scene.scene_id,
                        measured,
                        duration,
                    )

            vis_asset = visual_map.get(scene.scene_id)
            vis_path = Path(vis_asset.image_path) if vis_asset and vis_asset.image_path else None

            av_asset = avatar_map.get(scene.scene_id)
            av_path = Path(av_asset.video_path) if av_asset and av_asset.video_path else None

            sub_asset = sub_map.get(scene.scene_id)
            sub_path = Path(sub_asset.srt_path) if sub_asset and sub_asset.srt_path else None

            try:
                asset = self.provider.compose_scene(
                    scene_id=scene.scene_id,
                    locale=locale,
                    audio_path=Path(audio_asset.audio_path),
                    visual_image_path=vis_path,
                    avatar_video_path=av_path,
                    subtitle_path=sub_path,
                    duration_seconds=duration,
                    output_path=out_file,
                    burn_subtitles=settings.BURN_SUBTITLES,
                )
                scene_results.append(asset)
            except Exception as e:
                logger.error("Failed to compose scene '%s': %s", scene.scene_id, e)
                scene_results.append(
                    SceneCompositionAsset(
                        scene_id=scene.scene_id,
                        locale=locale,
                        video_path="",
                        duration_seconds=duration,
                        status="failed",
                        error=str(e),
                    )
                )

        return scene_results

    def compose_locale_final_video(
        self,
        script: LocalizedScript,
        scene_videos: List[SceneCompositionAsset],
        project_id: str = "default_project",
        force_regenerate: bool = False,
    ) -> FinalVideoAsset:
        """
        Concatenate successfully rendered scene videos in sequence order into final MP4.
        """
        locale = script.locale
        final_dir = self.output_base_dir / project_id / "final"
        final_dir.mkdir(parents=True, exist_ok=True)
        final_output = final_dir / f"training_{locale}.mp4"

        successful_scenes = [s for s in scene_videos if s.status == "completed" and Path(s.video_path).exists()]
        if not successful_scenes:
            return FinalVideoAsset(
                locale=locale,
                video_path="",
                total_duration_seconds=0.0,
                scene_count=0,
                scene_videos=scene_videos,
                status="failed",
                error="No successful scene videos available for concatenation.",
            )

        # Idempotency check: reuse final video ONLY if duration matches sum of scene videos
        expected_total = sum(s.duration_seconds for s in successful_scenes)
        if not force_regenerate and final_output.exists() and final_output.stat().st_size > 0:
            measured = get_video_duration(final_output)
            if measured > 0 and abs(measured - expected_total) <= 0.5:
                logger.info("Reusing existing final video for locale '%s'", locale)
                return FinalVideoAsset(
                    locale=locale,
                    video_path=str(final_output.resolve()),
                    total_duration_seconds=measured,
                    scene_count=len(successful_scenes),
                    scene_videos=scene_videos,
                    status="completed",
                    metadata={"provider": self.provider.provider_name, "reused": True},
                )
            elif measured > 0:
                logger.warning(
                    "Stale final video asset detected for locale '%s' (measured %.2fs != scenes sum %.2fs). Re-concatenating.",
                    locale,
                    measured,
                    expected_total,
                )

        try:
            final_asset = self.provider.concatenate_scenes(
                scene_videos=successful_scenes,
                locale=locale,
                output_path=final_output,
            )
            final_asset.scene_videos = scene_videos
            return final_asset
        except Exception as e:
            logger.error("Failed to concatenate final video for locale '%s': %s", locale, e)
            return FinalVideoAsset(
                locale=locale,
                video_path="",
                total_duration_seconds=0.0,
                scene_count=len(successful_scenes),
                scene_videos=scene_videos,
                status="failed",
                error=str(e),
            )

    def compose_bundle_videos(
        self,
        bundle: LocalizationBundle,
        audio_tracks: Dict[str, LocalizedAudioTrack],
        visual_tracks: Optional[Dict[str, LocalizedVisualTrack]] = None,
        subtitle_tracks: Optional[Dict[str, LocalizedSubtitleTrack]] = None,
        avatar_tracks: Optional[Dict[str, LocalizedAvatarTrack]] = None,
        project_id: str = "default_project",
        force_regenerate: bool = False,
    ) -> Dict[str, FinalVideoAsset]:
        """
        Compose scene videos and final concatenated videos for all locales in bundle.
        """
        results: Dict[str, FinalVideoAsset] = {}
        vis_tracks = visual_tracks or {}
        sub_tracks = subtitle_tracks or {}
        av_tracks = avatar_tracks or {}

        for locale, script in bundle.localized_scripts.items():
            audio_track = audio_tracks.get(locale)
            if not audio_track:
                logger.warning("No audio track for locale '%s'; skipping composition.", locale)
                results[locale] = FinalVideoAsset(
                    locale=locale,
                    video_path="",
                    total_duration_seconds=0.0,
                    status="failed",
                    error="Missing audio track for locale",
                )
                continue

            try:
                scenes = self.compose_locale_scenes(
                    script=script,
                    audio_track=audio_track,
                    visual_track=vis_tracks.get(locale),
                    subtitle_track=sub_tracks.get(locale),
                    avatar_track=av_tracks.get(locale),
                    project_id=project_id,
                    force_regenerate=force_regenerate,
                )
                final_video = self.compose_locale_final_video(
                    script=script,
                    scene_videos=scenes,
                    project_id=project_id,
                    force_regenerate=force_regenerate,
                )
                results[locale] = final_video
            except Exception as e:
                logger.error("Composition error on locale '%s': %s", locale, e)
                results[locale] = FinalVideoAsset(
                    locale=locale,
                    video_path="",
                    total_duration_seconds=0.0,
                    status="failed",
                    error=str(e),
                )

        return results
