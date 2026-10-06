"""TTS high-level service orchestrating voice synthesis across projects and bundles."""

from pathlib import Path
from typing import Optional, Dict
from app.core.config import settings
from app.core.logging import logger
from app.models.schemas import (
    LocalizedScript,
    LocalizationBundle,
    LocalizedAudioTrack,
)
from app.services.tts.base import TTSProvider
from app.services.tts.factory import get_tts_provider


class TTSService:
    """
    High-level speech synthesis service coordinating scene audio generation
    and updating pipeline timing metadata with measured waveform ground truth.
    """

    def __init__(
        self,
        provider: Optional[TTSProvider] = None,
        output_base_dir: Optional[Path] = None,
    ) -> None:
        self.provider = provider or get_tts_provider()
        self.output_base_dir = output_base_dir or settings.STORAGE_PATH

    def synthesize_locale(
        self,
        script: LocalizedScript,
        project_id: str,
        force_regenerate: bool = False,
    ) -> LocalizedAudioTrack:
        """
        Synthesize per-scene audio for a single localized script.
        """
        project_audio_dir = self.output_base_dir / project_id / "audio"
        logger.info(
            "Starting TTS synthesis for project '%s', locale '%s' via provider '%s'",
            project_id, script.locale, self.provider.provider_name
        )

        track = self.provider.synthesize_script(
            script=script,
            output_dir=project_audio_dir,
            force_regenerate=force_regenerate,
        )
        return track

    def synthesize_bundle(
        self,
        bundle: LocalizationBundle,
        project_id: str,
        force_regenerate: bool = False,
    ) -> Dict[str, LocalizedAudioTrack]:
        """
        Synthesize audio for all successful localized scripts in a bundle with error isolation.
        
        Failure in one locale track does not destroy or abort other locale audio tracks.
        """
        tracks: Dict[str, LocalizedAudioTrack] = {}

        for locale, script in bundle.localized_scripts.items():
            try:
                track = self.synthesize_locale(
                    script=script,
                    project_id=project_id,
                    force_regenerate=force_regenerate,
                )
                tracks[locale] = track
            except Exception as e:
                logger.error("TTS bundle generation failed for locale '%s': %s", locale, str(e))
                tracks[locale] = LocalizedAudioTrack(
                    locale=locale,
                    scene_audio=[],
                    total_audio_duration_seconds=0.0,
                    status="failed",
                    metadata={"error": str(e), "provider": self.provider.provider_name},
                )

        return tracks

    @staticmethod
    def update_script_with_actual_durations(
        script: LocalizedScript,
        track: LocalizedAudioTrack,
    ) -> LocalizedScript:
        """
        Replace pre-TTS heuristic duration estimates with exact measured audio waveform lengths.
        """
        asset_map = {a.scene_id: a.duration_seconds for a in track.scene_audio if a.status == "completed"}

        for scene in script.scenes:
            if scene.scene_id in asset_map:
                # Update with exact ground truth duration (rounded to integer seconds for scene model)
                scene.estimated_duration_seconds = max(1, round(asset_map[scene.scene_id]))

        script.total_estimated_duration_seconds = sum(s.estimated_duration_seconds for s in script.scenes)
        return script
