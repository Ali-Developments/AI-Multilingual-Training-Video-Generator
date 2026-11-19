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
    AnimationStep,
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
        persistent_presenter: Optional[bool] = None,
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

        # Determine whether persistent presenter architecture is active
        if persistent_presenter is not None:
            is_persistent = bool(persistent_presenter)
        elif hasattr(request_or_topic, "persistent_presenter") and request_or_topic.persistent_presenter is not None:
            is_persistent = bool(request_or_topic.persistent_presenter)
        elif style == VideoStyle.PRESENTER_LED.value:
            is_persistent = True
        else:
            is_persistent = getattr(settings, "PERSISTENT_PRESENTER_ENABLED", False)

        logger.info(
            "Planning storyboard for %d scenes (topic='%s', style='%s', avatar_provider='%s', persistent=%s)",
            total,
            topic_clean,
            style,
            avatar_provider,
            is_persistent,
        )

        for idx, scene in enumerate(scenes):
            order = idx + 1
            is_first = (order == 1)
            is_last = (order == total)
            stype = (scene.scene_type or "presenter").lower()
            text_lower = f"{scene.title} {scene.purpose} {scene.narration}".lower()
            has_spoken_narration = bool(scene.narration and scene.narration.strip())

            # 1. First Scene: Introduction
            if is_first:
                scene.media_type = SceneMediaType.PRESENTER.value
                scene.layout_type = (
                    SceneLayoutType.PRESENTER_LEFT_VISUAL_RIGHT.value
                    if is_persistent
                    else (
                        SceneLayoutType.PRESENTER_FULL.value
                        if style in (VideoStyle.PRESENTER_LED.value, VideoStyle.HYBRID_PRESENTER_BROLL.value, VideoStyle.CORPORATE_TRAINING.value)
                        else SceneLayoutType.PRESENTER_SPLIT.value
                    )
                )
                scene.avatar_enabled = True
                scene.presenter_position = "left" if is_persistent else ("center" if scene.layout_type == SceneLayoutType.PRESENTER_FULL.value else "right")
                scene.visual_prompt = f"Professional studio setting introducing {topic_clean}"
                scene.preferred_provider = avatar_provider
                scene.camera_movement = "static"
                scene.motion_description = "Natural presenter posture, realistic head movements, and synchronized lip-sync speech addressing the audience."

            # 2. Final Scene: Outro / Call to Action
            elif is_last:
                scene.media_type = SceneMediaType.OUTRO.value
                scene.layout_type = SceneLayoutType.PRESENTER_CENTER_WITH_OVERLAYS.value if is_persistent else SceneLayoutType.PRESENTER_FULL.value
                scene.avatar_enabled = True
                scene.presenter_position = "center"
                scene.visual_prompt = f"Presenter delivering closing takeaways and call to action for {topic_clean}"
                scene.preferred_provider = avatar_provider
                scene.camera_movement = "slow zoom-in"
                scene.motion_description = "Presenter delivering closing takeaways and encouraging course completion."

            # 3. Quiz / Knowledge Check Scene
            elif stype == "quiz" or "question" in text_lower or "quiz" in text_lower or "اختبار" in text_lower or "سؤال" in text_lower:
                scene.media_type = SceneMediaType.QUIZ.value
                scene.layout_type = (
                    SceneLayoutType.PRESENTER_LEFT_VISUAL_RIGHT.value
                    if (is_persistent and has_spoken_narration)
                    else SceneLayoutType.QUIZ_CARD.value
                )
                scene.avatar_enabled = bool(is_persistent and has_spoken_narration)
                scene.presenter_position = "left"
                scene.visual_prompt = f"Educational assessment question for {topic_clean}"
                scene.preferred_provider = "quiz"
                scene.camera_movement = "static"
                scene.motion_description = "Clean graphic presentation card presenting interactive knowledge check question."
                if not scene.quiz_data:
                    scene.quiz_data = cls._generate_fallback_quiz(scene, topic_clean)

            # 4. Middle Body Educational Scenes
            elif style == VideoStyle.PRESENTER_LED.value:
                if idx % 2 == 1:
                    scene.media_type = SceneMediaType.PRESENTER.value
                    scene.layout_type = SceneLayoutType.PRESENTER_LEFT_VISUAL_RIGHT.value if is_persistent else SceneLayoutType.PRESENTER_SPLIT.value
                    scene.avatar_enabled = True
                    scene.presenter_position = "left" if is_persistent else "right"
                    scene.visual_prompt = f"Supporting visual diagram illustrating {scene.title}"
                    scene.preferred_provider = avatar_provider
                    scene.camera_movement = "static"
                    scene.motion_description = f"Presenter explaining core concepts of {scene.title} with natural gestures and lip-sync."
                else:
                    scene.media_type = SceneMediaType.MOTION_VISUAL.value
                    scene.layout_type = SceneLayoutType.PRESENTER_RIGHT_VISUAL_LEFT.value if is_persistent else SceneLayoutType.MEDIA_WITH_OVERLAY.value
                    scene.avatar_enabled = is_persistent
                    scene.presenter_position = "right"
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
                    "execute", "apply", "how-to", "tutorial", "method", "drill", "تطبيق", "خطوة", "فحص"
                )
                if stype in ("visual_demo", "demonstration", "example") or any(k in text_lower or k in topic_clean.lower() for k in demo_keywords):
                    scene.media_type = SceneMediaType.BROLL.value
                    scene.layout_type = SceneLayoutType.PRESENTER_PICTURE_IN_PICTURE.value if is_persistent else SceneLayoutType.MEDIA_FULL.value
                    scene.avatar_enabled = is_persistent
                    scene.preferred_provider = "veo"
                    scene.camera_movement = "slow pan"
                    scene.visual_prompt = f"Step-by-step demonstration B-roll showing {scene.title} for {topic_clean}"
                    scene.motion_description = f"Cinematic instructional demonstration showing {scene.title} with fluid realistic motion."
                else:
                    scene.media_type = SceneMediaType.PRESENTER.value
                    scene.layout_type = SceneLayoutType.PRESENTER_LEFT_VISUAL_RIGHT.value if is_persistent else SceneLayoutType.PRESENTER_SPLIT.value
                    scene.avatar_enabled = True
                    scene.presenter_position = "left" if is_persistent else "right"
                    scene.preferred_provider = avatar_provider
                    scene.camera_movement = "static"
                    scene.visual_prompt = f"Tutorial demonstration visual for {scene.title}"
                    scene.motion_description = f"Presenter guiding learner through {scene.title}."

            else:
                # Default: HYBRID_PRESENTER_BROLL
                demo_keywords = (
                    "action", "step", "demonstrat", "procedure", "process", "workflow",
                    "hands-on", "technique", "practice", "guide", "setup", "perform",
                    "execute", "apply", "how-to", "tutorial", "method", "drill", "تطبيق", "خطوة", "فحص"
                )
                is_demo = stype in ("visual_demo", "demonstration", "example") or any(k in text_lower or k in topic_clean.lower() for k in demo_keywords)

                if is_persistent:
                    scene.avatar_enabled = True
                    if is_demo:
                        scene.media_type = SceneMediaType.BROLL.value
                        scene.layout_type = (
                            SceneLayoutType.PRESENTER_PICTURE_IN_PICTURE.value
                            if idx % 2 == 1
                            else SceneLayoutType.PRESENTER_LEFT_VISUAL_RIGHT.value
                        )
                        scene.presenter_position = "right" if scene.layout_type == SceneLayoutType.PRESENTER_PICTURE_IN_PICTURE.value else "left"
                        scene.preferred_provider = "veo"
                        scene.camera_movement = "slow pan"
                        scene.visual_prompt = f"Step-by-step demonstration B-roll showing {scene.title} for {topic_clean}"
                        scene.motion_description = f"Cinematic instructional demonstration showing {scene.title} with fluid realistic motion while presenter instructs."
                    else:
                        scene.media_type = SceneMediaType.MOTION_VISUAL.value
                        scene.layout_type = (
                            SceneLayoutType.PRESENTER_RIGHT_VISUAL_LEFT.value
                            if idx % 2 == 1
                            else SceneLayoutType.PRESENTER_LEFT_VISUAL_RIGHT.value
                        )
                        scene.presenter_position = "right" if scene.layout_type == SceneLayoutType.PRESENTER_RIGHT_VISUAL_LEFT.value else "left"
                        scene.preferred_provider = "local_motion"
                        scene.camera_movement = "slow zoom-in"
                        scene.visual_prompt = f"Cinematic motion graphic illustrating {scene.title}"
                        scene.motion_description = f"Subtle animated motion graphic overlay highlighting {scene.title} supporting the presenter's narration."
                else:
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

            # Build comprehensive narration-synchronized SceneMediaPlan
            scene.media_plan = cls.build_demonstration_plan(
                scene=scene,
                topic=topic_clean,
                is_first=is_first,
                is_last=is_last,
            )

        return script

    # Generic cross-domain instructional action patterns (multilingual: EN + AR)
    _ACTION_RULES = [
        ("cut", "chop_rhythm", ("chop", "slice", "cut", "dice", "trim", "carve", "strip", "تقطيع", "فرم", "نقطع", "قطّع", "قص")),
        ("heat", "heat_pulse", ("heat", "boil", "simmer", "sauté", "saute", "fry", "melt", "roast", "bake", "oven", "preheat", "cook", "warm", "temperature", "thermal", "تسخين", "سلق", "غلي", "فرن", "خبز", "تذويب", "طهي", "حرارة")),
        ("mix", "stir_circular", ("stir", "whisk", "mix", "blend", "combine", "beat", "fold", "knead", "dissolve", "agitate", "تقليب", "خلط", "خفق", "مزج", "نقلب", "نخلط")),
        ("pour", "pour_stream", ("pour", "drizzle", "add", "fill", "drain", "strain", "inject", "dispense", "infuse", "سكب", "إضافة", "صب", "تصفية", "نضيف", "نسكب")),
        ("assemble", "layer_stack", ("layer", "assemble", "stack", "mount", "install", "build", "arrange", "spread", "place", "tray", "align", "رص", "طبقة", "طبقات", "تجميع", "تركيب", "فرد", "صينية", "توزيع")),
        ("measure", "highlight_scan", ("measure", "weigh", "calibrate", "gauge", "meter", "dose", "count", "ratio", "قياس", "وزن", "معايرة", "مقدار", "كمية")),
        ("inspect", "highlight_scan", ("inspect", "verify", "check", "test", "diagnose", "scan", "audit", "examine", "observe", "فحص", "تحقق", "اختبار", "مراقبة", "ملاحظة")),
        ("connect", "orbit_flow", ("connect", "wire", "solder", "circuit", "plug", "link", "route", "network", "pipeline", "توصيل", "ربط", "دائرة", "سلك", "شبكة")),
        ("code", "orbit_flow", ("code", "function", "compile", "deploy", "execute", "script", "query", "api", "debug", "برمجة", "كود", "تشغيل", "تنفيذ")),
        ("serve", "showcase_reveal", ("serve", "present", "plate", "garnish", "finish", "deliver", "lift", "reveal", "تقديم", "تزيين", "شريحة", "النتيجة", "النهائي")),
        ("prepare", "slide_in", ("prepare", "gather", "setup", "set up", "organize", "ingredients", "tools", "materials", "equip", "تحضير", "تجهيز", "مكونات", "أدوات", "إعداد")),
    ]

    _STOPWORDS = {
        "the", "and", "for", "with", "that", "this", "from", "into", "onto", "over", "then",
        "your", "our", "you", "are", "was", "were", "will", "have", "has", "been", "being",
        "about", "after", "before", "until", "while", "when", "where", "what", "which",
        "step", "scene", "show", "showing", "demonstrate", "demonstrating", "explain",
        "explaining", "using", "make", "making", "ensure", "properly", "carefully",
        "في", "من", "على", "إلى", "عن", "مع", "هذا", "هذه", "التي", "الذي", "حتى",
        "ثم", "بعد", "قبل", "عند", "كما", "أثناء", "خلال", "بين", "كل", "بشكل", "جيداً",
    }

    @classmethod
    def _infer_action_and_movement(cls, text: str) -> tuple[str, str]:
        """Infer generic action verb and procedural movement pattern from any instructional clause."""
        low = (text or "").lower()
        for action_verb, movement, keywords in cls._ACTION_RULES:
            if any(k in low for k in keywords):
                return action_verb, movement
        return "highlight", "slide_in"

    @classmethod
    def _extract_scene_objects(cls, text: str, max_items: int = 6) -> List[str]:
        """Extract concise domain object terms dynamically from scene text (no hardcoded topics)."""
        tokens = re.findall(r"[\w\u0600-\u06FF\-]{3,}", text or "")
        seen = set()
        objects: List[str] = []
        for tok in tokens:
            clean = tok.strip("-_")
            low = clean.lower()
            if len(clean) < 3 or low in cls._STOPWORDS or low.isdigit():
                continue
            if low not in seen:
                seen.add(low)
                objects.append(clean)
            if len(objects) >= max_items:
                break
        return objects

    @classmethod
    def _split_narration_clauses(cls, narration: str, fallback_title: str) -> List[str]:
        """Split narration into 2-5 visual beat clauses for narration-synchronized animation."""
        raw = (narration or "").strip()
        if not raw:
            return [fallback_title or "Visual demonstration"]

        # Split on sentence boundaries (English & Arabic punctuation)
        parts = [
            p.strip()
            for p in re.split(r"(?<=[.!?؟])\s+|[\n;؛]+", raw)
            if p and p.strip()
        ]
        # If single long sentence, split on commas / conjunctions
        if len(parts) == 1 and len(parts[0].split()) > 10:
            sub_parts = [
                p.strip()
                for p in re.split(r"[,،]\s+|\s+(?:then|and then|next|after that|finally|ثم|وبعد ذلك|بعدها)\s+", parts[0], flags=re.IGNORECASE)
                if p and p.strip()
            ]
            if len(sub_parts) >= 2:
                parts = sub_parts

        # Cap at 5 beats by merging trailing short clauses
        while len(parts) > 5:
            parts[-2] = f"{parts[-2]} {parts[-1]}".strip()
            parts.pop()

        return parts or [fallback_title or "Visual demonstration"]

    @classmethod
    def build_demonstration_plan(
        cls,
        scene: Any,
        topic: str = "",
        is_first: bool = False,
        is_last: bool = False,
    ) -> SceneMediaPlan:
        """
        Build a generic, narration-synchronized SceneMediaPlan with explicit
        demonstration actions, required objects, object movement, and timed animation steps.
        """
        title = (getattr(scene, "title", "") or "").strip()
        purpose = (getattr(scene, "purpose", "") or "Content delivery").strip()
        narration = (getattr(scene, "narration", "") or "").strip()
        vis_desc = (
            getattr(scene, "visual_direction", "")
            or getattr(scene, "visual_description", "")
            or getattr(scene, "visual_prompt", "")
            or title
        ).strip()
        media_type = str(getattr(scene, "media_type", "presenter") or "presenter").lower()
        scene_type = str(getattr(scene, "scene_type", "presenter") or "presenter").lower()
        target_duration = float(getattr(scene, "estimated_duration_seconds", 5.0) or 5.0)
        transition = str(getattr(scene, "transition", "fade") or "fade")

        # Determine if this scene is an active animated demonstration vs static card
        is_quiz_or_title = media_type in ("quiz", "title") or scene_type in ("quiz", "title")
        clauses = cls._split_narration_clauses(narration, title)

        # Compute word-proportional normalized timing ratios [0.0 -> 1.0]
        weights = [max(len(c.split()), 1) for c in clauses]
        total_weight = float(sum(weights)) or 1.0

        animation_steps: List[AnimationStep] = []
        cursor = 0.0
        all_objects: List[str] = []

        for idx, clause in enumerate(clauses, start=1):
            start_r = round(cursor, 4)
            end_r = 1.0 if idx == len(clauses) else round(min(1.0, cursor + weights[idx - 1] / total_weight), 4)
            cursor = end_r

            action_verb, movement = cls._infer_action_and_movement(f"{clause} {vis_desc if idx == 1 else ''}")
            if is_first and idx == 1 and action_verb == "highlight":
                action_verb, movement = "present", "showcase_reveal"
            elif is_last and idx == len(clauses) and action_verb == "highlight":
                action_verb, movement = "serve", "showcase_reveal"

            step_objs = cls._extract_scene_objects(clause, max_items=3)
            for obj in step_objs:
                if obj.lower() not in {o.lower() for o in all_objects}:
                    all_objects.append(obj)

            # Concise step label (first ~7 words of the clause)
            words = clause.split()
            short_label = " ".join(words[:7]) + ("..." if len(words) > 7 else "")

            animation_steps.append(
                AnimationStep(
                    step_index=idx,
                    label=short_label or f"Step {idx}",
                    action_verb=action_verb,
                    objects=step_objs,
                    movement=movement,
                    start_ratio=start_r,
                    end_ratio=max(end_r, start_r),
                    narration_segment=clause,
                )
            )

        if not all_objects:
            all_objects = cls._extract_scene_objects(f"{vis_desc} {title} {topic}", max_items=6)

        primary_action, primary_movement = cls._infer_action_and_movement(f"{title} {vis_desc} {narration}")
        if animation_steps and primary_action == "highlight":
            primary_action = animation_steps[0].action_verb
            primary_movement = animation_steps[0].movement

        is_animated_demo = (not is_quiz_or_title) and (
            media_type in ("broll", "motion_visual", "uploaded_video", "diagram")
            or scene_type in ("visual_demo", "demonstration", "example", "explanation", "concept")
            or len(animation_steps) >= 2
            or primary_action in ("cut", "heat", "mix", "pour", "assemble", "measure", "inspect", "connect", "code", "prepare", "serve")
        )

        pref_provider = getattr(scene, "preferred_provider", None)
        provider_hint = (
            "uploaded_video"
            if getattr(scene, "media_asset_path", None)
            else ("veo" if str(pref_provider or "").lower() == "veo" else "local_motion")
        )

        return SceneMediaPlan(
            scene_id=getattr(scene, "scene_id", "scene_1") or "scene_1",
            purpose=purpose,
            narration=narration,
            visual_description=vis_desc,
            motion_description=getattr(scene, "motion_description", None),
            camera_movement=getattr(scene, "camera_movement", "static") or "static",
            reference_image_requirements=getattr(scene, "reference_image_requirements", None),
            preferred_provider=pref_provider,
            target_duration=target_duration,
            aspect_ratio=getattr(scene, "aspect_ratio", "16:9") or "16:9",
            demonstration_action=f"{primary_action}: {title}" if title else primary_action,
            required_objects=all_objects[:6],
            object_movement=primary_movement,
            animation_sequence=animation_steps,
            transition_to_next=transition,
            is_animated_demonstration=is_animated_demo,
            animation_provider_hint=provider_hint,
        )

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
