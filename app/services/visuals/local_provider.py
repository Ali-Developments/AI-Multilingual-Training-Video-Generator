"""Local visual slide and background provider using Pillow and Motion Animator."""

from pathlib import Path
from typing import Optional, List
from PIL import Image, ImageDraw, ImageFont

from app.core.logging import logger
from app.models.schemas import LocalizedScene, CulturalGuidance, SceneVisualAsset
from app.services.visuals.base import VisualAssetProvider, classify_visual_type
from app.services.media.motion_animator import (
    detect_motion_archetype,
    _render_email_security_frame,
    _render_safe_handling_frame,
    _render_incident_response_frame,
    _render_general_concept_frame,
    _get_font,
    _wrap_text,
)


class LocalVisualProvider(VisualAssetProvider):
    """
    High-reliability, zero-cost local visual asset renderer.
    
    Generates high-definition (1920x1080) slide graphics, title cards,
    and instructional visual containers formatted for video presentation.
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

        # Check if Quiz Scene
        is_quiz = (getattr(scene, "media_type", "") == "quiz") or (scene.scene_type == "quiz") or (getattr(scene, "quiz_data", None) is not None)

        if is_quiz and getattr(scene, "quiz_data", None):
            bg_color = (9, 13, 26)
            image = Image.new("RGB", (width, height), color=bg_color)
            draw = ImageDraw.Draw(image)

            # Ambient atmospheric glows
            draw.ellipse([int(width * 0.15), int(height * 0.1), int(width * 0.7), int(height * 0.75)], fill=(16, 26, 52))
            draw.ellipse([int(width * 0.5), int(height * 0.25), int(width * 0.95), int(height * 0.9)], fill=(14, 38, 62))

            # Sleek accent header line
            draw.rectangle([0, 0, width, 5], fill=(0, 229, 255))
            draw.rectangle([int(width * 0.5), 0, width, 5], fill=(79, 70, 229))

            title_font = _get_font(38, bold=True)
            heading_font = _get_font(28, bold=True)
            option_font = _get_font(24, bold=False)

            quiz = scene.quiz_data
            card_x0, card_y0 = 140, 150
            card_x1, card_y1 = width - 140, height - 180
            draw.rounded_rectangle([card_x0, card_y0, card_x1, card_y1], radius=20, fill=(16, 24, 46), outline=(0, 229, 255), width=2)

            # Quiz Badge
            draw.rounded_rectangle([card_x0 + 40, card_y0 - 20, card_x0 + 260, card_y0 + 20], radius=10, fill=(0, 229, 255))
            draw.text((card_x0 + 55, card_y0 - 15), "KNOWLEDGE CHECK", fill=(9, 13, 26), font=_get_font(18, bold=True))

            # Question Text
            q_lines = _wrap_text(quiz.question, max_chars=48)[:3]
            qy = card_y0 + 50
            for line in q_lines:
                draw.text((card_x0 + 50, qy), line, fill=(255, 255, 255), font=title_font)
                qy += 55

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
            # Render fully-assembled instructional graphic from motion animator
            archetype = detect_motion_archetype(scene)
            dur = 5.0
            sec = 4.2  # Fully resolved state with highlights, badges, and complete text
            if archetype == "email_security":
                image = _render_email_security_frame(width, height, sec, dur, scene)
            elif archetype == "safe_handling":
                image = _render_safe_handling_frame(width, height, sec, dur, scene)
            elif archetype == "incident_response":
                image = _render_incident_response_frame(width, height, sec, dur, scene)
            else:
                image = _render_general_concept_frame(width, height, sec, dur, scene)

        # Save PNG deterministically
        image.save(img_path, format="PNG")
        logger.info("Generated high-quality visual slide for scene '%s' at %s", scene.scene_id, img_path)

        return SceneVisualAsset(
            scene_id=scene.scene_id,
            locale=locale,
            image_path=str(img_path.resolve()),
            width=width,
            height=height,
            format="png",
            visual_type=visual_type,
            status="completed",
        )
