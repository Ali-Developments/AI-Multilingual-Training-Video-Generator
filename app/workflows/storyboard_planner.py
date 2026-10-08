"""AI Storyboard Planning Service.

Plans scene media presentation types (presenter, broll, motion_visual, quiz, outro)
and layouts (presenter_full, presenter_split, media_full, media_with_overlay, quiz_card)
so final videos look like professional video studio productions rather than slide presentations.
"""

from typing import List, Optional, Dict, Any
import re
from app.core.logging import logger
from app.models.schemas import (
    SceneDraft,
    ScriptDraft,
    FinalScript,
    SceneMediaType,
    SceneLayoutType,
    VideoStyle,
    QuizData,
)


class StoryboardPlanner:
    """Plans multimodal presentation layouts and media assets for video scripts."""

    def __init__(self, llm_provider: Optional[Any] = None):
        self.llm_provider = llm_provider

    @classmethod
    def plan_storyboard(
        cls,
        script: Any,  # ScriptDraft or FinalScript
        request_or_topic: Any = "",
        video_style: Optional[str] = None,
        base_language: str = "en-US",
    ) -> Any:
        """
        Enrich each scene in the script with intelligent media types,
        layout types, visual prompts, and presenter roles.
        """
        scenes: List[SceneDraft] = script.scenes
        total = len(scenes)

        if hasattr(request_or_topic, "topic"):
            topic = request_or_topic.topic
            if not video_style and hasattr(request_or_topic, "video_style"):
                vs = request_or_topic.video_style
                video_style = vs.value if hasattr(vs, "value") else str(vs)
            if hasattr(request_or_topic, "base_language"):
                base_language = request_or_topic.base_language
        else:
            topic = str(request_or_topic or "")

        style = (video_style or VideoStyle.HYBRID_PRESENTER_BROLL.value).lower()
        topic_clean = topic or getattr(script, "title", "Training Topic")

        logger.info(
            "Planning storyboard for %d scenes (topic='%s', style='%s')",
            total,
            topic_clean,
            style,
        )

        for idx, scene in enumerate(scenes):
            order = idx + 1
            is_first = (order == 1)
            is_last = (order == total)
            stype = (scene.scene_type or "presenter").lower()
            text_lower = f"{scene.title} {scene.purpose} {scene.narration}".lower()

            # 1. First Scene: Introduction
            if is_first:
                scene.media_type = SceneMediaType.PRESENTER.value
                # If presenter-led or hybrid, lead with presenter
                scene.layout_type = (
                    SceneLayoutType.PRESENTER_FULL.value
                    if style in (VideoStyle.PRESENTER_LED.value, VideoStyle.HYBRID_PRESENTER_BROLL.value, VideoStyle.CORPORATE_TRAINING.value)
                    else SceneLayoutType.PRESENTER_SPLIT.value
                )
                scene.avatar_enabled = True
                scene.presenter_position = "center" if scene.layout_type == SceneLayoutType.PRESENTER_FULL.value else "right"
                scene.visual_prompt = f"Professional studio setting introducing {topic_clean}"
                scene.media_search_terms = cls._derive_search_terms(topic_clean, scene.title, "introduction")
                continue

            # 2. Final Scene: Outro / Call to Action
            if is_last:
                scene.media_type = SceneMediaType.OUTRO.value
                scene.layout_type = SceneLayoutType.PRESENTER_FULL.value
                scene.avatar_enabled = True
                scene.presenter_position = "center"
                scene.visual_prompt = f"Presenter delivering closing takeaways and call to action for {topic_clean}"
                scene.media_search_terms = cls._derive_search_terms(topic_clean, scene.title, "conclusion summary")
                continue

            # 3. Quiz / Knowledge Check Scene
            if stype == "quiz" or "question" in text_lower or "quiz" in text_lower or "اختبار" in text_lower or "سؤال" in text_lower:
                scene.media_type = SceneMediaType.QUIZ.value
                scene.layout_type = SceneLayoutType.QUIZ_CARD.value
                scene.avatar_enabled = False
                scene.visual_prompt = f"Educational assessment question for {topic_clean}"
                if not scene.quiz_data:
                    scene.quiz_data = cls._generate_fallback_quiz(scene, topic_clean)
                continue

            # 4. Middle Body Scenes planned according to VideoStyle
            if style == VideoStyle.PRESENTER_LED.value:
                # Primary presenter: alternate full / split
                if idx % 2 == 1:
                    scene.media_type = SceneMediaType.PRESENTER.value
                    scene.layout_type = SceneLayoutType.PRESENTER_SPLIT.value
                    scene.avatar_enabled = True
                    scene.presenter_position = "right"
                    scene.visual_prompt = f"Supporting visual diagram illustrating {scene.title}"
                else:
                    scene.media_type = SceneMediaType.MOTION_VISUAL.value
                    scene.layout_type = SceneLayoutType.MEDIA_WITH_OVERLAY.value
                    scene.avatar_enabled = False
                    scene.visual_prompt = f"High-impact motion visual for {scene.title}"

            elif style == VideoStyle.VISUAL_EXPLAINER.value:
                # Mostly motion visual / b-roll with minimal presenter
                scene.avatar_enabled = False
                if "demo" in text_lower or "step" in text_lower:
                    scene.media_type = SceneMediaType.BROLL.value
                    scene.layout_type = SceneLayoutType.MEDIA_FULL.value
                else:
                    scene.media_type = SceneMediaType.MOTION_VISUAL.value
                    scene.layout_type = SceneLayoutType.MEDIA_WITH_OVERLAY.value
                scene.visual_prompt = f"Cinematic explainer visual highlighting {scene.title}"

            elif style == VideoStyle.DEMONSTRATION_TUTORIAL.value:
                # Emphasize demonstration B-roll
                if "recipe" in topic_clean.lower() or "prep" in text_lower or "cook" in text_lower or "action" in text_lower or "step" in text_lower:
                    scene.media_type = SceneMediaType.BROLL.value
                    scene.layout_type = SceneLayoutType.MEDIA_FULL.value
                    scene.avatar_enabled = False
                    scene.visual_prompt = f"Step-by-step demonstration B-roll showing {scene.title}"
                else:
                    scene.media_type = SceneMediaType.PRESENTER.value
                    scene.layout_type = SceneLayoutType.PRESENTER_SPLIT.value
                    scene.avatar_enabled = True
                    scene.presenter_position = "right"
                    scene.visual_prompt = f"Tutorial demonstration visual for {scene.title}"

            else:
                # Default: HYBRID_PRESENTER_BROLL
                # Balance presenter explanation and cinematic supporting media
                if stype in ("visual_demo", "demonstration", "example"):
                    scene.media_type = SceneMediaType.BROLL.value
                    scene.layout_type = SceneLayoutType.MEDIA_FULL.value
                    scene.avatar_enabled = False
                    scene.visual_prompt = f"Dynamic B-roll footage showing {scene.title}"
                elif stype in ("explanation", "concept"):
                    scene.media_type = SceneMediaType.MOTION_VISUAL.value
                    scene.layout_type = SceneLayoutType.MEDIA_WITH_OVERLAY.value
                    scene.avatar_enabled = False
                    scene.visual_prompt = f"Cinematic motion graphic illustrating {scene.title}"
                elif stype in ("presenter", "recap", "summary"):
                    scene.media_type = SceneMediaType.PRESENTER.value
                    scene.layout_type = SceneLayoutType.PRESENTER_SPLIT.value
                    scene.avatar_enabled = True
                    scene.presenter_position = "right"
                    scene.visual_prompt = f"Visual infographic card supporting {scene.title}"
                else:
                    # Alternating default
                    if idx % 2 == 1:
                        scene.media_type = SceneMediaType.MOTION_VISUAL.value
                        scene.layout_type = SceneLayoutType.MEDIA_WITH_OVERLAY.value
                        scene.avatar_enabled = False
                    else:
                        scene.media_type = SceneMediaType.PRESENTER.value
                        scene.layout_type = SceneLayoutType.PRESENTER_SPLIT.value
                        scene.avatar_enabled = True
                        scene.presenter_position = "right"

            scene.media_search_terms = cls._derive_search_terms(topic_clean, scene.title, scene.purpose)

        return script

    @staticmethod
    def _derive_search_terms(topic: str, title: str, purpose: str) -> List[str]:
        """Derive relevant stock/media search terms from scene content."""
        clean_terms = []
        for phrase in (topic, title, purpose):
            words = [w.strip() for w in re.split(r"[,:\-\s]+", phrase) if len(w) > 3]
            clean_terms.extend(words[:3])
        # Deduplicate while preserving order
        seen = set()
        unique = []
        for t in clean_terms:
            t_low = t.lower()
            if t_low not in seen:
                seen.add(t_low)
                unique.append(t)
        return unique[:6]

    @staticmethod
    def _generate_fallback_quiz(scene: SceneDraft, topic: str) -> QuizData:
        """Create structured default quiz data from scene content."""
        q_text = scene.title
        if not q_text.endswith("?"):
            q_text = f"Quick Knowledge Check: {scene.title}?"
        return QuizData(
            question=q_text,
            options=[
                "Verify sender and details immediately",
                "Ignore safety protocols and proceed",
                "Forward to unauthorized external contacts",
            ],
            correct_index=0,
            explanation=f"Always follow best practices for {topic}.",
        )
