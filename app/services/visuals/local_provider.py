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

        # 1. Base Canvas - Deep modern cinematic slate (#090D1A)
        bg_color = (9, 13, 26)
        image = Image.new("RGB", (width, height), color=bg_color)
        draw = ImageDraw.Draw(image)

        # Draw ambient atmospheric soft glows
        draw.ellipse([int(width * 0.15), int(height * 0.1), int(width * 0.7), int(height * 0.75)], fill=(16, 26, 52))
        draw.ellipse([int(width * 0.5), int(height * 0.25), int(width * 0.95), int(height * 0.9)], fill=(14, 38, 62))

        # 2. Sleek accent header line
        accent_color = (0, 229, 255)
        secondary_color = (79, 70, 229)
        draw.rectangle([0, 0, width, 6], fill=accent_color)
        draw.rectangle([100, 60, width - 100, 62], fill=(30, 41, 69))

        # 3. Fonts
        title_font = _get_font(48)
        heading_font = _get_font(34)
        body_font = _get_font(28)
        option_font = _get_font(26)

        # Check if Quiz Scene
        is_quiz = (getattr(scene, "media_type", "") == "quiz") or (scene.scene_type == "quiz") or (getattr(scene, "quiz_data", None) is not None)

        if is_quiz and getattr(scene, "quiz_data", None):
            quiz = scene.quiz_data
            # Quiz Card UI
            card_x0, card_y0 = 140, 150
            card_x1, card_y1 = width - 140, height - 200
            draw.rounded_rectangle([card_x0, card_y0, card_x1, card_y1], radius=20, fill=(16, 24, 46), outline=(0, 229, 255), width=2)

            # Quiz Badge
            draw.rounded_rectangle([card_x0 + 40, card_y0 - 20, card_x0 + 260, card_y0 + 20], radius=10, fill=(0, 229, 255))
            draw.text((card_x0 + 55, card_y0 - 15), "KNOWLEDGE CHECK", fill=(9, 13, 26), font=_get_font(20))

            # Question Text
            q_lines = _wrap_text(quiz.question, max_chars=48)[:3]
            qy = card_y0 + 50
            for line in q_lines:
                draw.text((card_x0 + 50, qy), line, fill=(255, 255, 255), font=title_font)
                qy += 60

            # Option Cards
            opt_y = qy + 20
            letters = ["A", "B", "C", "D"]
            for idx, opt in enumerate(quiz.options[:4]):
                prefix = letters[idx] if idx < len(letters) else "•"
                opt_x0 = card_x0 + 50
                opt_x1 = card_x1 - 50
                draw.rounded_rectangle([opt_x0, opt_y, opt_x1, opt_y + 55], radius=12, fill=(24, 35, 65), outline=(45, 62, 105), width=1)
                draw.text((opt_x0 + 20, opt_y + 12), f"{prefix}.", fill=(0, 229, 255), font=heading_font)
                draw.text((opt_x0 + 70, opt_y + 14), opt, fill=(235, 240, 250), font=option_font)
                opt_y += 70

        else:
            # Standard Educational Visual Slide
            # Scene Title (clean, no "SCENE 1" debug text)
            title_lines = _wrap_text(scene.title, max_chars=45)[:2]
            title_y = 100
            for line in title_lines:
                draw.text((100, title_y), line, fill=(255, 255, 255), font=title_font)
                title_y += 62

            # Main Visual Focus Card
            if scene.on_screen_text and scene.on_screen_text.strip():
                card_x0, card_y0 = 100, title_y + 30
                card_x1, card_y1 = width - 100, height - 200
                draw.rounded_rectangle([card_x0, card_y0, card_x1, card_y1], radius=18, fill=(16, 25, 48), outline=(38, 55, 96), width=2)

                # Key Focus Text
                cy = card_y0 + 40
                ost_lines = _wrap_text(scene.on_screen_text.strip(), max_chars=48)[:5]
                for line in ost_lines:
                    draw.text((card_x0 + 60, cy), line, fill=(240, 245, 255), font=heading_font)
                    cy += 55

        # 9. Save PNG deterministically
        image.save(img_path, format="PNG")
        logger.info("Generated clean visual slide for scene '%s' at %s", scene.scene_id, img_path)

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
