"""Deterministic subtitle generation based on known script narration and exact audio duration."""

from pathlib import Path
from app.core.logging import logger
from app.models.schemas import SceneSubtitleAsset
from app.services.localization.locale_utils import get_text_direction
from app.services.subtitles.base import SubtitleProvider
from app.services.subtitles.formatter import (
    split_narration_into_chunks,
    serialize_srt,
    serialize_vtt,
)


class DeterministicSubtitleProvider(SubtitleProvider):
    """
    High-speed, zero-cost deterministic subtitle generator.
    
    Splits validated narration into readable caption blocks and aligns them
    proportionally across measured audio waveform lengths.
    """

    @property
    def provider_name(self) -> str:
        return "deterministic"

    def generate_scene_subtitles(
        self,
        scene_id: str,
        narration: str,
        duration_seconds: float,
        locale: str,
        output_dir: Path,
    ) -> SceneSubtitleAsset:
        output_dir.mkdir(parents=True, exist_ok=True)
        srt_path = output_dir / f"{scene_id}.srt"
        vtt_path = output_dir / f"{scene_id}.vtt"
        direction = get_text_direction(locale)

        if not narration or not narration.strip() or duration_seconds <= 0:
            logger.info("Scene '%s' has empty narration or zero duration; creating blank subtitle asset.", scene_id)
            srt_path.write_text("", encoding="utf-8")
            vtt_path.write_text("WEBVTT\n\n", encoding="utf-8")
            return SceneSubtitleAsset(
                scene_id=scene_id,
                locale=locale,
                srt_path=str(srt_path.resolve()),
                vtt_path=str(vtt_path.resolve()),
                chunk_count=0,
                duration_seconds=duration_seconds,
                text_direction=direction,
                status="completed",
            )

        chunks = split_narration_into_chunks(narration, total_duration_seconds=duration_seconds)

        srt_content = serialize_srt(chunks)
        vtt_content = serialize_vtt(chunks)

        # Explicit UTF-8 encoding ensures Arabic and Bengali text integrity
        srt_path.write_text(srt_content, encoding="utf-8")
        vtt_path.write_text(vtt_content, encoding="utf-8")

        logger.info(
            "Generated subtitles for scene '%s' (%s, %d cues, duration=%.2fs)",
            scene_id, locale, len(chunks), duration_seconds
        )

        return SceneSubtitleAsset(
            scene_id=scene_id,
            locale=locale,
            srt_path=str(srt_path.resolve()),
            vtt_path=str(vtt_path.resolve()),
            chunk_count=len(chunks),
            duration_seconds=duration_seconds,
            text_direction=direction,
            status="completed",
        )
