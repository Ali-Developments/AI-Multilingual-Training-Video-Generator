"""Local visual slide and background provider using Pillow."""

from pathlib import Path
from typing import Optional, List
from PIL import Image, ImageDraw, ImageFont

from app.core.logging import logger
from app.models.schemas import LocalizedScene, CulturalGuidance, SceneVisualAsset
from app.services.visuals.base import VisualAssetProvider, classify_visual_type


def _get_font(size: int) -> ImageFont.ImageFont:
    """Attempt to load a clean scalable system font, falling back to default font."""
    font_candidates = [
        "segoeui.ttf",
        "arial.ttf",
        "tahoma.ttf",
        "DejaVuSans.ttf",
        "Helvetica.ttf",
    ]
    for font_name in font_candidates:
        try:
            return ImageFont.truetype(font_name, size)
        except (OSError, IOError):
            continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def _wrap_text(text: str, max_chars: int = 50) -> List[str]:
    """Simple word-wrap helper for multiline text blocks."""
    if not text:
        return []
    words = text.split()
    lines = []
    current_line: List[str] = []
    current_len = 0

    for word in words:
        if current_len + len(word) + 1 > max_chars and current_line:
            lines.append(" ".join(current_line))
            current_line = [word]
            current_len = len(word)
        else:
            current_line.append(word)
            current_len += len(word) + 1

    if current_line:
        lines.append(" ".join(current_line))
    return lines


class LocalVisualProvider(VisualAssetProvider):
    """
    High-reliability, zero-cost local visual asset renderer.
    
    Generates high-definition (1920x1080) slide graphics, title cards,
    and diagram containers formatted for video presentation.
    """

    @property
    def provider_name(self) -> str:
        return "local"

    def generate_scene_visual(
        self,
        scene: LocalizedScene,
        locale: str,
        output_dir: Path,
        width: int = 1920,
        height: int = 1080,
        cultural_guidance: Optional[CulturalGuidance] = None,
    ) -> SceneVisualAsset:
        output_dir.mkdir(parents=True, exist_ok=True)
        img_path = output_dir / f"{scene.scene_id}.png"
        visual_type = classify_visual_type(scene.scene_type)

        # 1. Base Canvas - Deep modern navy / dark slate (#0B132B)
        bg_color = (11, 19, 43)
        image = Image.new("RGB", (width, height), color=bg_color)
        draw = ImageDraw.Draw(image)

        # 2. Modern accent gradient / top bar (#00E5FF to #4F46E5)
        accent_color = (0, 229, 255)
        secondary_color = (79, 70, 229)
        draw.rectangle([0, 0, width, 12], fill=accent_color)
        draw.rectangle([80, 70, width - 80, 74], fill=secondary_color)

        # 3. Fonts
        badge_font = _get_font(24)
        title_font = _get_font(52)
        heading_font = _get_font(36)
        body_font = _get_font(30)
        footer_font = _get_font(22)

        # 4. Scene Badge
        badge_text = f"SCENE {scene.order}  •  {scene.scene_type.upper()}  •  {visual_type.replace('_', ' ').upper()}"
        draw.text((80, 95), badge_text, fill=(0, 229, 255), font=badge_font)

        # 5. Scene Title
        title_lines = _wrap_text(scene.title, max_chars=40)[:2]
        title_y = 145
        for line in title_lines:
            draw.text((80, title_y), line, fill=(255, 255, 255), font=title_font)
            title_y += 65

        # 6. Main Content Area Card (#1C2541)
        card_x0, card_y0 = 80, 310
        card_x1, card_y1 = width - 80, height - 120
        draw.rounded_rectangle([card_x0, card_y0, card_x1, card_y1], radius=16, fill=(28, 37, 65))
        draw.rounded_rectangle([card_x0, card_y0, card_x1, card_y1], radius=16, outline=(58, 80, 107), width=2)

        # 7. Render Card Content
        content_y = card_y0 + 50

        # On-Screen Text (Primary Visual Focus)
        if scene.on_screen_text and scene.on_screen_text.strip():
            draw.text((card_x0 + 50, content_y), "KEY TAKEAWAY", fill=(0, 229, 255), font=heading_font)
            content_y += 55

            ost_lines = _wrap_text(scene.on_screen_text, max_chars=55)[:6]
            for line in ost_lines:
                draw.text((card_x0 + 70, content_y), f"•  {line}", fill=(240, 240, 245), font=body_font)
                content_y += 45
            content_y += 30

        # Purpose or Visual Direction
        if scene.purpose and scene.purpose.strip():
            draw.text((card_x0 + 50, content_y), "OBJECTIVE", fill=(160, 180, 210), font=heading_font)
            content_y += 50
            purpose_lines = _wrap_text(scene.purpose, max_chars=60)[:3]
            for line in purpose_lines:
                draw.text((card_x0 + 70, content_y), line, fill=(200, 210, 225), font=body_font)
                content_y += 42

        # 8. Footer Info
        footer_text = f"Locale: {locale}  |  Video Automation  |  {scene.scene_id}"
        draw.text((80, height - 70), footer_text, fill=(110, 130, 160), font=footer_font)

        # 9. Save PNG deterministically
        image.save(img_path, format="PNG")
        logger.info("Generated local visual slide for scene '%s' at %s", scene.scene_id, img_path)

        return SceneVisualAsset(
            scene_id=scene.scene_id,
            locale=locale,
            image_path=str(img_path.resolve()),
            width=width,
            height=height,
            visual_type=visual_type,
            provider=self.provider_name,
            status="completed",
        )
