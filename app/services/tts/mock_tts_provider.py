"""Mock TTS provider producing valid synthetic audio files without external network calls."""

import wave
from pathlib import Path
from typing import Optional, List, Dict
from app.core.logging import logger
from app.models.schemas import SceneAudioAsset
from app.services.tts.base import TTSProvider
from app.services.tts.audio_probe import get_audio_duration


def generate_synthetic_wav_file(file_path: Path, duration_seconds: float = 1.0, sample_rate: int = 16000) -> Path:
    """
    Generate a valid PCM WAV audio file with specified duration.
    
    Creates a valid RIFF/WAVE header measurable by ffprobe and Python's wave module.
    """
    file_path.parent.mkdir(parents=True, exist_ok=True)
    num_frames = int(sample_rate * duration_seconds)
    with wave.open(str(file_path), "wb") as wf:
        wf.setnchannels(1)  # Mono
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(sample_rate)
        wf.writeframes(b"\x00\x00" * num_frames)
    return file_path


class MockTTSProvider(TTSProvider):
    """
    Mock TTS provider generating real local audio files without consuming external credits.
    """

    def __init__(
        self,
        fixed_duration_seconds: Optional[float] = None,
        fail_scene_ids: Optional[List[str]] = None,
        fail_locales: Optional[List[str]] = None,
    ) -> None:
        self.fixed_duration_seconds = fixed_duration_seconds
        self.fail_scene_ids = set(fail_scene_ids or [])
        self.fail_locales = set(fail_locales or [])
        self.call_count = 0
        self.history: List[Dict[str, str]] = []

    @property
    def provider_name(self) -> str:
        return "mock"

    async def synthesize_scene_audio_async(
        self,
        narration: str,
        output_path: Path,
        locale: str,
        voice: Optional[str] = None,
    ) -> SceneAudioAsset:
        self.call_count += 1
        scene_stem = output_path.stem
        self.history.append({
            "scene": scene_stem,
            "locale": locale,
            "voice": voice or self.resolve_voice(locale),
        })

        if not narration or not narration.strip():
            raise ValueError(f"Narration text cannot be empty for {scene_stem}.")

        if locale in self.fail_locales:
            raise RuntimeError(f"Simulated TTS failure for locale '{locale}'.")

        if scene_stem in self.fail_scene_ids:
            raise RuntimeError(f"Simulated TTS failure for scene '{scene_stem}'.")

        # Determine realistic synthetic duration
        if self.fixed_duration_seconds is not None:
            dur = self.fixed_duration_seconds
        else:
            word_count = len(narration.split())
            dur = max(1.0, round((word_count / 140.0) * 60.0, 2))

        # Generate a real valid WAV file
        wav_path = output_path.with_suffix(".wav")
        generate_synthetic_wav_file(wav_path, duration_seconds=dur)

        # Measure duration through local probe to verify ground truth
        actual_duration = get_audio_duration(wav_path)

        logger.info("MockTTS generated '%s' (locale=%s, dur=%.2fs)", wav_path.name, locale, actual_duration)

        return SceneAudioAsset(
            scene_id=scene_stem,
            locale=locale,
            audio_path=str(wav_path.resolve()),
            duration_seconds=actual_duration,
            provider=self.provider_name,
            voice_id=voice or self.resolve_voice(locale),
            status="completed",
        )
