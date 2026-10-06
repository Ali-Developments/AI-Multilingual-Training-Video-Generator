"""Mock video composition provider for rapid testing and dry runs."""

from pathlib import Path
from typing import List, Optional

from app.models.schemas import SceneCompositionAsset, FinalVideoAsset
from app.services.composition.base import CompositionProvider
from app.services.avatar.mock_avatar_provider import generate_synthetic_mp4_file


class MockCompositionProvider(CompositionProvider):
    """
    In-memory mock composition provider generating synthetic MP4 video files.
    """

    @property
    def provider_name(self) -> str:
        return "mock"

    def compose_scene(
        self,
        scene_id: str,
        locale: str,
        audio_path: Path,
        visual_image_path: Optional[Path],
        avatar_video_path: Optional[Path],
        subtitle_path: Optional[Path],
        duration_seconds: float,
        output_path: Path,
        burn_subtitles: bool = True,
    ) -> SceneCompositionAsset:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        generate_synthetic_mp4_file(output_path, duration_seconds=max(0.5, duration_seconds))

        has_avatar = bool(avatar_video_path and avatar_video_path.exists())
        has_sub = bool(burn_subtitles and subtitle_path and subtitle_path.exists())

        return SceneCompositionAsset(
            scene_id=scene_id,
            locale=locale,
            video_path=str(output_path.resolve()),
            duration_seconds=duration_seconds,
            has_avatar=has_avatar,
            has_subtitles=has_sub,
            status="completed",
        )

    def concatenate_scenes(
        self,
        scene_videos: List[SceneCompositionAsset],
        locale: str,
        output_path: Path,
    ) -> FinalVideoAsset:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        total_dur = sum(s.duration_seconds for s in scene_videos)
        generate_synthetic_mp4_file(output_path, duration_seconds=max(0.5, total_dur))

        return FinalVideoAsset(
            locale=locale,
            video_path=str(output_path.resolve()),
            total_duration_seconds=total_dur,
            scene_count=len(scene_videos),
            scene_videos=scene_videos,
            status="completed",
            metadata={"provider": self.provider_name},
        )
