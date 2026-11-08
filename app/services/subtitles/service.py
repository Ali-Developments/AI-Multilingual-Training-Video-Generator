"""Subtitle high-level service coordinating per-scene caption generation."""

from pathlib import Path
from typing import Optional, Dict
from app.core.config import settings
from app.core.logging import logger
from app.models.schemas import (
    LocalizedScript,
    LocalizationBundle,
    LocalizedAudioTrack,
    SceneSubtitleAsset,
    LocalizedSubtitleTrack,
    SubtitleChunk,
)
from app.services.subtitles.base import SubtitleProvider
from app.services.subtitles.factory import get_subtitle_provider
from app.services.subtitles.formatter import (
    split_narration_into_chunks,
    serialize_srt,
    serialize_vtt,
    serialize_ass,
)
from app.services.localization.locale_utils import get_text_direction


class SubtitleService:
    """
    High-level subtitle service coordinating per-scene caption generation
    aligned strictly to ground-truth audio waveform lengths.
    """

    def __init__(
        self,
        provider: Optional[SubtitleProvider] = None,
        output_base_dir: Optional[Path] = None,
    ) -> None:
        self.provider = provider or get_subtitle_provider()
        self.output_base_dir = output_base_dir or settings.STORAGE_PATH

    def generate_locale_subtitles(
        self,
        script: LocalizedScript,
        audio_track: LocalizedAudioTrack,
        project_id: str,
        force_regenerate: bool = False,
    ) -> LocalizedSubtitleTrack:
        """
        Generate timed subtitle files for each scene in a localized script.
        """
        locale = script.locale
        sub_dir = self.output_base_dir / project_id / "subtitles" / locale
        sub_dir.mkdir(parents=True, exist_ok=True)

        audio_map = {
            a.scene_id: a.duration_seconds
            for a in audio_track.scene_audio
            if a.status == "completed"
        }

        scene_subtitles = []
        for scene in script.scenes:
            srt_dest = sub_dir / f"{scene.scene_id}.srt"
            vtt_dest = sub_dir / f"{scene.scene_id}.vtt"
            ass_dest = sub_dir / f"{scene.scene_id}.ass"
            exact_duration = audio_map.get(scene.scene_id, float(scene.estimated_duration_seconds))

            # Idempotency check: reuse valid existing subtitle files
            if (
                not force_regenerate
                and srt_dest.exists()
                and vtt_dest.exists()
                and ass_dest.exists()
            ):
                logger.info("Reusing existing subtitle asset for scene '%s' (%s)", scene.scene_id, locale)
                raw_srt = srt_dest.read_text(encoding="utf-8").strip()
                parsed_cues = [b for b in raw_srt.split("\n\n") if b.strip()] if raw_srt else []
                scene_subtitles.append(
                    SceneSubtitleAsset(
                        scene_id=scene.scene_id,
                        locale=locale,
                        srt_path=str(srt_dest.resolve()),
                        vtt_path=str(vtt_dest.resolve()),
                        ass_path=str(ass_dest.resolve()),
                        chunk_count=len(parsed_cues),
                        duration_seconds=exact_duration,
                        text_direction=get_text_direction(locale),
                        status="completed",
                    )
                )
                continue

            try:
                asset = self.provider.generate_scene_subtitles(
                    scene_id=scene.scene_id,
                    narration=scene.narration,
                    duration_seconds=exact_duration,
                    locale=locale,
                    output_dir=sub_dir,
                )
                scene_subtitles.append(asset)
            except Exception as e:
                logger.error("Subtitle generation failed for scene '%s': %s", scene.scene_id, str(e))
                scene_subtitles.append(
                    SceneSubtitleAsset(
                        scene_id=scene.scene_id,
                        locale=locale,
                        srt_path="",
                        vtt_path="",
                        ass_path="",
                        chunk_count=0,
                        duration_seconds=exact_duration,
                        text_direction=get_text_direction(locale),
                        status="failed",
                        error=str(e),
                    )
                )

        completed_count = sum(1 for s in scene_subtitles if s.status == "completed")
        failed_count = sum(1 for s in scene_subtitles if s.status == "failed")

        if failed_count == 0:
            track_status = "completed"
        elif completed_count > 0:
            track_status = "partial"
        else:
            track_status = "failed"

        # Assemble track-level cumulative subtitles (subtitles.srt, subtitles.vtt, subtitles.ass)
        all_chunks = []
        elapsed = 0.0
        global_cue_idx = 1
        for scene in script.scenes:
            exact_dur = audio_map.get(scene.scene_id, float(scene.estimated_duration_seconds or 1.0))
            if scene.narration and scene.narration.strip():
                scene_chunks = split_narration_into_chunks(scene.narration, total_duration_seconds=exact_dur)
                for sc in scene_chunks:
                    all_chunks.append(
                        SubtitleChunk(
                            index=global_cue_idx,
                            start_seconds=round(elapsed + sc.start_seconds, 3),
                            end_seconds=round(elapsed + sc.end_seconds, 3),
                            text=sc.text,
                        )
                    )
                    global_cue_idx += 1
            elapsed += exact_dur

        track_srt = sub_dir / "subtitles.srt"
        track_vtt = sub_dir / "subtitles.vtt"
        track_ass = sub_dir / "subtitles.ass"
        if all_chunks:
            track_srt.write_text(serialize_srt(all_chunks), encoding="utf-8")
            track_vtt.write_text(serialize_vtt(all_chunks), encoding="utf-8")
            track_ass.write_text(serialize_ass(all_chunks, locale=locale), encoding="utf-8")
        else:
            track_srt.write_text("", encoding="utf-8")
            track_vtt.write_text("WEBVTT\n\n", encoding="utf-8")
            track_ass.write_text("", encoding="utf-8")

        return LocalizedSubtitleTrack(
            locale=locale,
            scene_subtitles=scene_subtitles,
            srt_path=str(track_srt.resolve()),
            vtt_path=str(track_vtt.resolve()),
            ass_path=str(track_ass.resolve()),
            status=track_status,
            metadata={
                "provider": self.provider.provider_name,
                "total_scenes": len(script.scenes),
                "completed_count": completed_count,
                "failed_count": failed_count,
            },
        )

    def generate_bundle_subtitles(
        self,
        bundle: LocalizationBundle,
        audio_tracks: Dict[str, LocalizedAudioTrack],
        project_id: str,
        force_regenerate: bool = False,
    ) -> Dict[str, LocalizedSubtitleTrack]:
        """
        Generate subtitle tracks for all localized scripts in a bundle with error isolation.
        """
        sub_tracks = {}
        for locale, script in bundle.localized_scripts.items():
            audio_track = audio_tracks.get(locale)
            if not audio_track:
                logger.warning("No audio track found for locale '%s'; skipping subtitles.", locale)
                sub_tracks[locale] = LocalizedSubtitleTrack(
                    locale=locale,
                    scene_subtitles=[],
                    status="failed",
                    metadata={"error": "Missing audio track for locale"},
                )
                continue

            try:
                track = self.generate_locale_subtitles(
                    script=script,
                    audio_track=audio_track,
                    project_id=project_id,
                    force_regenerate=force_regenerate,
                )
                sub_tracks[locale] = track
            except Exception as e:
                logger.error("Failed to generate subtitle track for locale '%s': %s", locale, str(e))
                sub_tracks[locale] = LocalizedSubtitleTrack(
                    locale=locale,
                    scene_subtitles=[],
                    status="failed",
                    metadata={"error": str(e)},
                )

        return sub_tracks
