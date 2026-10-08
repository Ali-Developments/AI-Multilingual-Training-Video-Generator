"""Abstract base class and contract for Text-to-Speech (TTS) voice synthesis providers."""

import asyncio
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional, List
from app.core.config import settings
from app.core.logging import logger
from app.models.schemas import (
    LocalizedScript,
    SceneAudioAsset,
    LocalizedAudioTrack,
)
from app.services.localization.locale_utils import normalize_locale
from app.services.tts.audio_probe import get_audio_duration
from app.core.caching import (
    is_audio_asset_valid,
    save_asset_metadata,
    hash_text,
    hash_file,
)


class TTSProvider(ABC):
    """Abstract interface defining voice synthesis capabilities."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Return unique provider identifier (e.g. edge_tts, mock, azure)."""
        pass

    def resolve_voice(self, locale: str, voice_override: Optional[str] = None) -> str:
        """
        Resolve configured voice identifier for the given locale.
        
        Args:
            locale: Normalized locale code (e.g. 'ar-SA', 'bn-BD', 'en-US').
            voice_override: Explicit voice name override.
        """
        if voice_override:
            return voice_override

        try:
            norm_loc = normalize_locale(locale)
        except Exception:
            norm_loc = locale

        # Exact locale match
        if norm_loc in settings.TTS_DEFAULT_VOICES:
            return settings.TTS_DEFAULT_VOICES[norm_loc]

        # Language-only fallback (e.g. 'ar' from 'ar-EG')
        lang_prefix = norm_loc.split("-")[0]
        if lang_prefix in settings.TTS_DEFAULT_VOICES:
            return settings.TTS_DEFAULT_VOICES[lang_prefix]

        # General English fallback
        return settings.TTS_DEFAULT_VOICES.get("en-US", "en-US-ChristopherNeural")

    @abstractmethod
    async def synthesize_scene_audio_async(
        self,
        narration: str,
        output_path: Path,
        locale: str,
        voice: Optional[str] = None,
    ) -> SceneAudioAsset:
        """Asynchronously synthesize speech audio for a single scene narration."""
        pass

    def synthesize_scene_audio(
        self,
        narration: str,
        output_path: Path,
        locale: str,
        voice: Optional[str] = None,
    ) -> SceneAudioAsset:
        """Synchronous wrapper for scene speech synthesis."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            # In an active event loop: create a task or run via thread pool
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(
                    asyncio.run,
                    self.synthesize_scene_audio_async(narration, output_path, locale, voice)
                ).result()
        else:
            return asyncio.run(
                self.synthesize_scene_audio_async(narration, output_path, locale, voice)
            )

    def synthesize_script(
        self,
        script: LocalizedScript,
        output_dir: Path,
        force_regenerate: bool = False,
    ) -> LocalizedAudioTrack:
        """
        Synthesize isolated speech audio for every scene in a localized script.
        
        Preserves completed assets if force_regenerate=False (idempotency).
        Isolates per-scene failures so single-scene errors do not abort the entire track.
        """
        locale = script.locale
        locale_audio_dir = output_dir / locale
        locale_audio_dir.mkdir(parents=True, exist_ok=True)

        scene_assets: List[SceneAudioAsset] = []
        voice_id = self.resolve_voice(locale)

        for scene in script.scenes:
            # File extension defaults to .mp3 unless mock specifies .wav
            file_ext = ".wav" if self.provider_name == "mock" else ".mp3"
            scene_file = locale_audio_dir / f"{scene.scene_id}{file_ext}"

            # Content-aware idempotency check: only reuse if narration matches
            if (
                not force_regenerate
                and scene_file.exists()
                and scene_file.stat().st_size > 0
                and is_audio_asset_valid(
                    audio_path=scene_file,
                    expected_narration=scene.narration,
                    expected_voice=voice_id,
                    expected_provider=self.provider_name,
                )
            ):
                try:
                    dur = get_audio_duration(scene_file)
                    logger.info("Reusing existing validated audio asset for scene '%s' (%s, %.2fs)", scene.scene_id, locale, dur)
                    scene_assets.append(
                        SceneAudioAsset(
                            scene_id=scene.scene_id,
                            locale=locale,
                            audio_path=str(scene_file.resolve()),
                            duration_seconds=dur,
                            provider=self.provider_name,
                            voice_id=voice_id,
                            status="completed",
                        )
                    )
                    continue
                except Exception as ex:
                    logger.warning("Existing audio asset '%s' corrupted (%s); regenerating.", scene_file, str(ex))

            # Synthesize new asset with scene-level failure isolation
            try:
                if not scene.narration or not scene.narration.strip():
                    raise ValueError(f"Scene '{scene.scene_id}' has empty narration; cannot synthesize speech.")

                asset = self.synthesize_scene_audio(
                    narration=scene.narration,
                    output_path=scene_file,
                    locale=locale,
                    voice=voice_id,
                )
                asset.scene_id = scene.scene_id
                # Persist sidecar metadata for content-aware cache validation
                save_asset_metadata(
                    scene_file,
                    {
                        "scene_id": scene.scene_id,
                        "locale": locale,
                        "narration_hash": hash_text(scene.narration),
                        "audio_hash": hash_file(scene_file),
                        "duration": asset.duration_seconds,
                        "provider": self.provider_name,
                        "voice_id": voice_id,
                    },
                )
                scene_assets.append(asset)
            except Exception as e:
                logger.error("TTS synthesis failed for scene '%s' in locale '%s': %s", scene.scene_id, locale, str(e))
                scene_assets.append(
                    SceneAudioAsset(
                        scene_id=scene.scene_id,
                        locale=locale,
                        audio_path=str(scene_file.resolve()),
                        duration_seconds=0.0,
                        provider=self.provider_name,
                        voice_id=voice_id,
                        status="failed",
                        error=str(e),
                    )
                )

        completed_assets = [a for a in scene_assets if a.status == "completed"]
        total_duration = round(sum(a.duration_seconds for a in completed_assets), 2)

        if len(completed_assets) == len(script.scenes):
            track_status = "completed"
        elif len(completed_assets) > 0:
            track_status = "partial"
        else:
            track_status = "failed"

        return LocalizedAudioTrack(
            locale=locale,
            scene_audio=scene_assets,
            total_audio_duration_seconds=total_duration,
            status=track_status,
            metadata={
                "provider": self.provider_name,
                "voice_id": voice_id,
                "total_scenes": len(script.scenes),
                "completed_scenes": len(completed_assets),
            },
        )
