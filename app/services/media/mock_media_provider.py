"""Mock scene media provider for offline development and testing."""

from pathlib import Path
from typing import Optional
from app.models.schemas import LocalizedScene
from app.services.media.base import SceneMediaProvider
from app.services.avatar.mock_avatar_provider import generate_synthetic_mp4_file


class MockMediaProvider(SceneMediaProvider):
    """Generates synthetic valid MP4 video assets without external API costs."""

    @property
    def provider_name(self) -> str:
        return "mock"

    def supports_media_type(self, media_type: str) -> bool:
        return True

    def generate_scene_media(
        self,
        scene: LocalizedScene,
        locale: str,
        output_dir: Path,
        duration_seconds: float,
        background_image_path: Optional[Path] = None,
        custom_media_path: Optional[Path] = None,
    ) -> Path:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        out_file = output_dir / f"{scene.scene_id}_mock.mp4"
        return generate_synthetic_mp4_file(out_file, duration_seconds=max(duration_seconds, 1.0))

