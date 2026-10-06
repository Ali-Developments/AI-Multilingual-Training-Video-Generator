"""Edge TTS provider implementation offering free neural voice synthesis."""

from pathlib import Path
from typing import Optional
import edge_tts
from app.core.logging import logger
from app.models.schemas import SceneAudioAsset
from app.services.tts.base import TTSProvider
from app.services.tts.audio_probe import get_audio_duration


class EdgeTTSProvider(TTSProvider):
    """
    Microsoft Edge TTS provider using free neural speech synthesis.
    """

    @property
    def provider_name(self) -> str:
        return "edge_tts"

    async def synthesize_scene_audio_async(
        self,
        narration: str,
        output_path: Path,
        locale: str,
        voice: Optional[str] = None,
    ) -> SceneAudioAsset:
        """
        Synthesize speech audio using edge_tts.
        """
        if not narration or not narration.strip():
            raise ValueError(f"Narration text cannot be empty for {output_path.stem}.")

        voice_id = voice or self.resolve_voice(locale)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        logger.info(
            "Synthesizing audio with EdgeTTS: locale='%s', voice='%s', destination='%s'",
            locale, voice_id, output_path.name
        )

        try:
            communicate = edge_tts.Communicate(text=narration, voice=voice_id)
            await communicate.save(str(output_path))
        except Exception as e:
            logger.error("EdgeTTS communication failed for voice '%s': %s", voice_id, str(e))
            raise RuntimeError(f"EdgeTTS generation failed for voice '{voice_id}': {str(e)}") from e

        if not output_path.exists() or output_path.stat().st_size == 0:
            raise RuntimeError(f"EdgeTTS failed to produce valid audio file at: {output_path}")

        # Probe exact waveform duration
        measured_duration = get_audio_duration(output_path)

        return SceneAudioAsset(
            scene_id=output_path.stem,
            locale=locale,
            audio_path=str(output_path.resolve()),
            duration_seconds=measured_duration,
            provider=self.provider_name,
            voice_id=voice_id,
            status="completed",
        )
