"""AI Storyboard Planning Service.

Plans scene media presentation types (presenter, broll, motion_visual, quiz, outro)
and layouts (presenter_full, presenter_split, media_full, media_with_overlay, quiz_card)
so final videos look like professional video studio productions rather than slide presentations.
"""

from typing import List, Optional, Dict, Any
import re
from app.core.config import settings
from app.core.logging import logger
from app.models.schemas import (
    SceneDraft,
    ScriptDraft,
    FinalScript,
    SceneMediaType,
    SceneLayoutType,
    SceneMediaPlan,
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

        avatar_provider = "heygen"
        if hasattr(request_or_topic, "avatar_provider") and request_or_topic.avatar_provider:
            avatar_provider = str(request_or_topic.avatar_provider).strip().lower()
        else:
            avatar_provider = getattr(settings, "DEFAULT_AVATAR_PROVIDER", "heygen").strip().lower()

        logger.info(
            "Planning storyboard for %d scenes (topic='%s', style='%s', avatar_provider='%s')",
            total,
            topic_clean,
            style,
            avatar_provider,
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
                scene.layout_type = (
                    SceneLayoutType.PRESENTER_FULL.value
                    if style in (VideoStyle.PRESENTER_LED.value, VideoStyle.HYBRID_PRESENTER_BROLL.value, VideoStyle.CORPORATE_TRAINING.value)
                    else SceneLayoutType.PRESENTER_SPLIT.value
                )
                scene.avatar_enabled = True
                scene.presenter_position = "center" if scene.layout_type == SceneLayoutType.PRESENTER_FULL.value else "right"
                scene.visual_prompt = f"Professional studio setting introducing {topic_clean}"
                scene.preferred_provider = avatar_provider
                scene.camera_movement = "static"
                scene.motion_description = "Natural presenter posture, realistic head movements, and synchronized lip-sync speech addressing the audience."

            # 2. Final Scene: Outro / Call to Action
            elif is_last:
                scene.media_type = SceneMediaType.OUTRO.value
                scene.layout_type = SceneLayoutType.PRESENTER_FULL.value
                scene.avatar_enabled = True
                scene.presenter_position = "center"
                scene.visual_prompt = f"Presenter delivering closing takeaways and call to action for {topic_clean}"
                scene.preferred_provider = avatar_provider
                scene.camera_movement = "slow zoom-in"
                scene.motion_description = "Presenter delivering closing takeaways and encouraging course completion."

            # 3. Quiz / Knowledge Check Scene
            elif stype == "quiz" or "question" in text_lower or "quiz" in text_lower or "اختبار" in text_lower or "سؤال" in text_lower:
                scene.media_type = SceneMediaType.QUIZ.value
                scene.layout_type = SceneLayoutType.QUIZ_CARD.value
                scene.avatar_enabled = False
                scene.visual_prompt = f"Educational assessment question for {topic_clean}"
                scene.preferred_provider = "quiz"
                scene.camera_movement = "static"
                scene.motion_description = "Clean graphic presentation card presenting interactive knowledge check question."
                if not scene.quiz_data:
                    scene.quiz_data = cls._generate_fallback_quiz(scene, topic_clean)

            # 4. Middle Body Scenes planned according to VideoStyle
            elif style == VideoStyle.PRESENTER_LED.value:
                if idx % 2 == 1:
                    scene.media_type = SceneMediaType.PRESENTER.value
                    scene.layout_type = SceneLayoutType.PRESENTER_SPLIT.value
                    scene.avatar_enabled = True
                    scene.presenter_position = "right"
                    scene.visual_prompt = f"Supporting visual diagram illustrating {scene.title}"
                    scene.preferred_provider = avatar_provider
                    scene.camera_movement = "static"
                    scene.motion_description = f"Presenter explaining core concepts of {scene.title} with natural gestures and lip-sync."
                else:
                    scene.media_type = SceneMediaType.MOTION_VISUAL.value
                    scene.layout_type = SceneLayoutType.MEDIA_WITH_OVERLAY.value
                    scene.avatar_enabled = False
                    scene.visual_prompt = f"High-impact motion visual for {scene.title}"
                    scene.preferred_provider = "local_motion"
                    scene.camera_movement = "slow zoom-in"
                    scene.motion_description = f"Subtle animated Ken Burns motion graphic overlay highlighting {scene.title}."

            elif style == VideoStyle.VISUAL_EXPLAINER.value:
                scene.avatar_enabled = False
                if "demo" in text_lower or "step" in text_lower:
                    scene.media_type = SceneMediaType.BROLL.value
                    scene.layout_type = SceneLayoutType.MEDIA_FULL.value
                    scene.preferred_provider = "veo"
                    scene.camera_movement = "slow pan"
                    scene.motion_description = f"Cinematic B-roll footage showing {scene.title} in action."
                else:
                    scene.media_type = SceneMediaType.MOTION_VISUAL.value
                    scene.layout_type = SceneLayoutType.MEDIA_WITH_OVERLAY.value
                    scene.preferred_provider = "local_motion"
                    scene.camera_movement = "slow zoom-in"
                    scene.motion_description = f"Cinematic motion graphic illustrating {scene.title}."
                scene.visual_prompt = f"Cinematic explainer visual highlighting {scene.title}"

            elif style == VideoStyle.DEMONSTRATION_TUTORIAL.value:
                demo_keywords = (
                    "action", "step", "demonstrat", "procedure", "process", "workflow",
                    "hands-on", "technique", "practice", "guide", "setup", "perform",
                    "execute", "apply", "how-to", "tutorial", "method", "drill"
                )
                if any(k in text_lower or k in topic_clean.lower() for k in demo_keywords):
                    scene.media_type = SceneMediaType.BROLL.value
                    scene.layout_type = SceneLayoutType.MEDIA_FULL.value
                    scene.avatar_enabled = False
                    scene.preferred_provider = "veo"
                    scene.camera_movement = "slow pan"
                    scene.visual_prompt = f"Step-by-step demonstration B-roll showing {scene.title} for {topic_clean}"
                    scene.motion_description = f"Cinematic instructional demonstration showing {scene.title} with fluid realistic motion."
                else:
                    scene.media_type = SceneMediaType.PRESENTER.value
                    scene.layout_type = SceneLayoutType.PRESENTER_SPLIT.value
                    scene.avatar_enabled = True
                    scene.presenter_position = "right"
                    scene.preferred_provider = avatar_provider
                    scene.camera_movement = "static"
                    scene.visual_prompt = f"Tutorial demonstration visual for {scene.title}"
                    scene.motion_description = f"Presenter guiding learner through {scene.title}."

            else:
                # Default: HYBRID_PRESENTER_BROLL
                if stype in ("visual_demo", "demonstration", "example"):
                    scene.media_type = SceneMediaType.BROLL.value
                    scene.layout_type = SceneLayoutType.MEDIA_FULL.value
                    scene.avatar_enabled = False
                    scene.preferred_provider = "veo"
                    scene.camera_movement = "slow pan"
                    scene.visual_prompt = f"Dynamic B-roll footage showing {scene.title}"
                    scene.motion_description = f"Cinematic B-roll capturing {scene.title} with realistic camera motion and professional lighting."
                elif stype in ("explanation", "concept"):
                    scene.media_type = SceneMediaType.MOTION_VISUAL.value
                    scene.layout_type = SceneLayoutType.MEDIA_WITH_OVERLAY.value
                    scene.avatar_enabled = False
                    scene.preferred_provider = "local_motion"
                    scene.camera_movement = "slow zoom-in"
                    scene.visual_prompt = f"Cinematic motion graphic illustrating {scene.title}"
                    scene.motion_description = f"Subtle animated Ken Burns motion graphic overlay highlighting {scene.title}."
                elif stype in ("presenter", "recap", "summary"):
                    scene.media_type = SceneMediaType.PRESENTER.value
                    scene.layout_type = SceneLayoutType.PRESENTER_SPLIT.value
                    scene.avatar_enabled = True
                    scene.presenter_position = "right"
                    scene.preferred_provider = avatar_provider
                    scene.camera_movement = "static"
                    scene.visual_prompt = f"Visual infographic card supporting {scene.title}"
                    scene.motion_description = f"Presenter explaining {scene.title} with synchronized lip movements."
                else:
                    if idx % 2 == 1:
                        scene.media_type = SceneMediaType.MOTION_VISUAL.value
                        scene.layout_type = SceneLayoutType.MEDIA_WITH_OVERLAY.value
                        scene.avatar_enabled = False
                        scene.preferred_provider = "local_motion"
                        scene.camera_movement = "slow zoom-in"
                        scene.motion_description = f"Motion visual highlighting {scene.title}."
                    else:
                        scene.media_type = SceneMediaType.PRESENTER.value
                        scene.layout_type = SceneLayoutType.PRESENTER_SPLIT.value
                        scene.avatar_enabled = True
                        scene.presenter_position = "right"
                        scene.preferred_provider = avatar_provider
                        scene.camera_movement = "static"
                        scene.motion_description = f"Presenter explaining {scene.title}."

            # Finalize per-scene media metadata and structured media plan
            scene.aspect_ratio = getattr(scene, "aspect_ratio", None) or "16:9"
            scene.media_search_terms = cls._derive_search_terms(
                topic_clean,
                scene.title,
                "introduction" if is_first else ("conclusion summary" if is_last else scene.purpose)
            )

            # Build comprehensive SceneMediaPlan
            scene.media_plan = SceneMediaPlan(
                scene_id=scene.scene_id,
                purpose=scene.purpose or "Content delivery",
                narration=scene.narration or "",
                visual_description=scene.visual_direction or scene.visual_description or scene.visual_prompt or scene.title or "",
                motion_description=scene.motion_description,
                camera_movement=scene.camera_movement or "static",
                reference_image_requirements=scene.reference_image_requirements,
                preferred_provider=scene.preferred_provider,
                target_duration=float(scene.estimated_duration_seconds or 5.0),
                aspect_ratio=scene.aspect_ratio or "16:9",
            )

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
        """Create structured default quiz data dynamically from scene content and topic."""
        title_clean = (scene.title or "").strip()
        purpose_clean = (scene.purpose or "").strip()

        q_text = title_clean
        if not q_text.endswith("?"):
            q_text = f"Knowledge Check: Regarding {title_clean}, what is the primary recommended approach?"

        correct_action = (
            purpose_clean
            if (purpose_clean and len(purpose_clean) > 8 and not purpose_clean.lower().startswith("content delivery"))
            else f"Apply the validated best practices for {title_clean}."
        )
        if not correct_action.endswith("."):
            correct_action += "."

        distractor_1 = f"Disregard standard procedures for {title_clean} and proceed without verification."
        distractor_2 = f"Skip this step entirely, assuming default assumptions are always sufficient."

        return QuizData(
            question=q_text,
            options=[
                correct_action,
                distractor_1,
                distractor_2,
            ],
            correct_index=0,
            explanation=f"Applying the validated principles of {title_clean} ensures consistent and reliable outcomes in {topic}.",
        )
