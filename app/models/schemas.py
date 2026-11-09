"""Pydantic schemas for API requests, responses, content analysis, and video scripts."""

from enum import Enum
import re
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone
from pydantic import BaseModel, Field, model_validator


class SceneMediaType(str, Enum):
    """Presentation media source type for a scene."""

    PRESENTER = "presenter"
    BROLL = "broll"
    UPLOADED_VIDEO = "uploaded_video"
    UPLOADED_IMAGE = "uploaded_image"
    MOTION_VISUAL = "motion_visual"
    DIAGRAM = "diagram"
    TITLE = "title"
    QUIZ = "quiz"
    OUTRO = "outro"


class SceneLayoutType(str, Enum):
    """Visual arrangement and layout composition for a scene."""

    PRESENTER_LEFT_VISUAL_RIGHT = "presenter_left_visual_right"
    PRESENTER_RIGHT_VISUAL_LEFT = "presenter_right_visual_left"
    PRESENTER_PICTURE_IN_PICTURE = "presenter_picture_in_picture"
    PRESENTER_CENTER_WITH_OVERLAYS = "presenter_center_with_overlays"
    PRESENTER_FULL = "presenter_full"
    PRESENTER_SPLIT = "presenter_split"
    MEDIA_FULL = "media_full"
    MEDIA_WITH_OVERLAY = "media_with_overlay"
    PRESENTER_OVERLAY = "presenter_overlay"
    TITLE_CARD = "title_card"
    QUIZ_CARD = "quiz_card"


class VideoStyle(str, Enum):
    """Overall visual presentation style for the training video."""

    PRESENTER_LED = "presenter_led"
    HYBRID_PRESENTER_BROLL = "hybrid_presenter_broll"
    VISUAL_EXPLAINER = "visual_explainer"
    DEMONSTRATION_TUTORIAL = "demonstration_tutorial"
    CORPORATE_TRAINING = "corporate_training"


class QuizData(BaseModel):
    """Structured question and answer data for educational quiz scenes."""

    question: str = Field(..., description="Interactive training question prompt")
    options: List[str] = Field(..., min_length=2, description="Available answer choices")
    correct_index: Optional[int] = Field(default=None, description="0-indexed correct option")
    explanation: Optional[str] = Field(default=None, description="Brief educational rationale for the answer")


class SceneMediaPlan(BaseModel):
    """Structured media production plan for video, avatar, and b-roll generation."""

    scene_id: str = Field(..., description="Unique scene identifier (e.g. scene_1)")
    purpose: str = Field(default="Content delivery", description="Instructional role or objective of this scene")
    narration: str = Field(default="", description="Spoken narration text")
    visual_description: str = Field(default="", description="Visual scene environment, subject, and content guidance")
    motion_description: Optional[str] = Field(default=None, description="Detailed cinematic motion, subject dynamics, or animation")
    camera_movement: Optional[str] = Field(default="static", description="Camera movement: static, slow zoom-in, pan right, pan left, orbital, tracking")
    reference_image_requirements: Optional[str] = Field(default=None, description="Stylistic requirements for reference image conditioning")
    preferred_provider: Optional[str] = Field(default=None, description="Target provider: heygen, veo, local_motion, mock, sadtalker, quiz")
    target_duration: float = Field(default=5.0, ge=0.1, description="Target duration in seconds")
    aspect_ratio: str = Field(default="16:9", description="Aspect ratio (16:9, 9:16, 1:1)")


class BrandingConfig(BaseModel):
    """Project brand identity and custom styling configuration."""

    enabled: bool = Field(default=False, description="Whether custom branding is applied")
    logo_path: Optional[str] = Field(default=None, description="Path or URL to company logo")
    primary_accent: Optional[str] = Field(default="#00E5FF", description="Primary accent color (hex)")
    secondary_accent: Optional[str] = Field(default="#4F46E5", description="Secondary accent color (hex)")
    font_preference: Optional[str] = Field(default="modern", description="Typography style key")
    intro_title: Optional[str] = Field(default=None, description="Custom branded title text")
    outro_cta: Optional[str] = Field(default=None, description="Closing call-to-action text")


class HealthResponse(BaseModel):
    """Schema for the health check endpoint response."""

    status: str = Field(..., description="Service health status", json_schema_extra={"example": "healthy"})
    app_name: str = Field(..., description="Application name")
    version: str = Field(..., description="Application semantic version")
    environment: str = Field(..., description="Execution environment")
    debug: bool = Field(..., description="Debug mode state")
    storage_accessible: bool = Field(..., description="Whether storage directory is accessible")
    details: Optional[Dict[str, Any]] = Field(default=None, description="Detailed system metadata")


class TrainingVideoRequest(BaseModel):
    """Input model requesting a training/educational video script."""

    topic: Optional[str] = Field(default=None, description="Topic or headline of the training module")
    source_content: Optional[str] = Field(default=None, description="Raw source text, transcript, or bullet points")
    audience: str = Field(default="General Professional / Adult Learner", description="Target learner profile")
    base_language: str = Field(default="en-US", description="Language for canonical script generation")
    target_languages: List[str] = Field(default_factory=lambda: ["en-US"], description="Future localization target languages")
    target_duration_seconds: int = Field(default=120, ge=15, le=3600, description="Target total video duration in seconds")
    tone: str = Field(default="engaging and professional", description="Stylistic tone of instruction")
    difficulty_level: Optional[str] = Field(default="intermediate", description="Difficulty level: beginner, intermediate, advanced")
    learning_objectives: Optional[List[str]] = Field(default=None, description="Explicit desired learning outcomes")
    locale: Optional[str] = Field(default=None, description="Cultural / regional locale hint (e.g., sa-Gulf, us-Corporate)")
    avatar_provider: str = Field(default="mock", description="Avatar provider: 'mock', 'sadtalker', or 'heygen'")
    ack_paid_credits: bool = Field(default=False, description="User acknowledgement for paid HeyGen credit usage")
    video_style: str = Field(default="hybrid_presenter_broll", description="Presentation style")
    persistent_presenter: Optional[bool] = Field(default=None, description="Whether presenter remains visible across all spoken scenes")
    branding: Optional[BrandingConfig] = Field(default=None, description="Visual branding overrides")

    @model_validator(mode="after")
    def validate_content_presence(self) -> "TrainingVideoRequest":
        """Ensure that content is provided, matches base_language, and adheres to avatar safety gates."""
        has_topic = bool(self.topic and self.topic.strip())
        has_source = bool(self.source_content and self.source_content.strip())
        if not (has_topic or has_source):
            raise ValueError("At least one of 'topic' or 'source_content' must be provided.")
        
        from app.core.language import validate_source_language_mismatch
        source_text = self.source_content or self.topic
        mismatch_err = validate_source_language_mismatch(source_text, self.base_language)
        if mismatch_err:
            raise ValueError(mismatch_err)

        prov = self.avatar_provider.strip().lower()
        if prov not in ("mock", "sadtalker", "heygen"):
            raise ValueError(
                f"Unsupported avatar provider '{self.avatar_provider}'. Supported options: 'mock', 'sadtalker', 'heygen'."
            )

        if prov == "heygen":
            from app.core.config import settings
            if not getattr(settings, "ENABLE_LIVE_HEYGEN", False):
                raise ValueError(
                    "Live HeyGen avatar generation is blocked: ENABLE_LIVE_HEYGEN is False in system configuration."
                )
            if not self.ack_paid_credits:
                raise ValueError(
                    "Live HeyGen avatar generation requires explicit acknowledgement that paid credits may be consumed."
                )
            
        return self


class LearningObjective(BaseModel):
    """Normalized educational learning objective with stable ID."""

    id: str = Field(..., description="Stable objective identifier (e.g. LO1, LO2)")
    description: str = Field(..., description="Concrete learning outcome description")


class ContentAnalysis(BaseModel):
    """Structured pedagogical analysis of the training topic or source material."""

    topic_summary: str = Field(..., description="Executive summary of the instructional topic")
    key_concepts: List[str] = Field(default_factory=list, description="Core educational concepts to cover")
    learning_objectives: List[LearningObjective] = Field(default_factory=list, description="Structured learning objectives with IDs")
    audience_notes: str = Field(..., description="Tailored pedagogical considerations for the target audience")
    recommended_scene_count: int = Field(..., ge=1, description="Recommended number of scenes")
    recommended_structure: List[str] = Field(default_factory=list, description="Sequential narrative structure stages")
    important_terms: List[str] = Field(default_factory=list, description="Key domain terminology that must remain precise")
    factual_constraints: List[str] = Field(default_factory=list, description="Factual rules and pedagogical guardrails")


class SceneDraft(BaseModel):
    """Rich scene specification ready for multi-modal video pipelines."""

    scene_id: str = Field(default="", description="Unique scene identifier (e.g., scene_1)")
    order: int = Field(default=1, ge=1, description="1-indexed sequence order")
    title: str = Field(..., description="Short scene title or section theme")
    purpose: str = Field(default="Content delivery", description="Instructional role of this scene")
    narration: str = Field(..., description="Spoken narration script for presenter/voiceover")
    estimated_duration_seconds: int = Field(default=15, ge=1, description="Estimated duration in seconds")
    visual_direction: str = Field(default="", description="Visual guidance for background, diagrams, or graphics (text metadata only)")
    on_screen_text: Optional[str] = Field(default=None, description="Optional text cards, bullets, or title overlay")
    learning_objective_ids: List[str] = Field(default_factory=list, description="IDs of learning objectives addressed in this scene")
    scene_type: str = Field(
        default="presenter",
        description="Scene classification (intro, presenter, explanation, visual_demo, example, recap, outro, quiz)"
    )

    # V2 Media & Layout Engine fields
    media_type: str = Field(default="presenter", description="Media source type (presenter, broll, motion_visual, uploaded_video, quiz, outro, etc.)")
    layout_type: str = Field(default="presenter_left_visual_right", description="Scene visual composition layout (presenter_left_visual_right, presenter_right_visual_left, presenter_picture_in_picture, presenter_center_with_overlays, presenter_split, presenter_full, media_full, etc.)")
    visual_prompt: Optional[str] = Field(default=None, description="Visual description or prompt for media synthesis/search")
    media_search_terms: List[str] = Field(default_factory=list, description="Search keywords for finding b-roll / stock / asset")
    avatar_enabled: bool = Field(default=True, description="Whether presenter avatar is actively rendered for this scene")
    presenter_position: str = Field(default="left", description="Presenter screen placement: left, right, center")
    transition: str = Field(default="fade", description="Scene transition: fade, cut, slide, crossfade")
    media_asset_path: Optional[str] = Field(default=None, description="Custom assigned media video or image path")
    quiz_data: Optional[QuizData] = Field(default=None, description="Structured quiz question and options if quiz scene")
    render_status: Optional[str] = Field(default=None, description="Render status for scene: completed, rendering, failed, or unrendered")
    rendered_video_url: Optional[str] = Field(default=None, description="Static storage URL to rendered scene MP4 if completed")
    has_rendered_asset: bool = Field(default=False, description="True if rendered video asset exists on disk and is completed")

    # Structured Media Planning & Motion Engine fields
    motion_description: Optional[str] = Field(default=None, description="Cinematic motion or animation description")
    camera_movement: Optional[str] = Field(default="static", description="Camera movement: static, slow zoom-in, pan right, pan left, orbital, tracking")
    reference_image_requirements: Optional[str] = Field(default=None, description="Stylistic requirements for reference image conditioning")
    preferred_provider: Optional[str] = Field(default=None, description="Preferred provider: heygen, sadtalker, veo, local_motion, mock, quiz")
    aspect_ratio: str = Field(default="16:9", description="Video aspect ratio: 16:9")
    media_plan: Optional[SceneMediaPlan] = Field(default=None, description="Structured media production plan")

    # Backwards-compatibility fields
    scene_number: Optional[int] = Field(default=None, description="Legacy alias for order")
    visual_description: Optional[str] = Field(default=None, description="Legacy alias for visual_direction")

    @model_validator(mode="after")
    def sync_scene_fields(self) -> "SceneDraft":
        """Synchronize legacy and new field names, deriving V2 defaults if needed."""
        if not self.order and self.scene_number:
            self.order = self.scene_number
        elif not self.scene_number and self.order:
            self.scene_number = self.order

        if not self.scene_id:
            self.scene_id = f"scene_{self.order}"

        if not self.visual_direction and self.visual_description:
            self.visual_direction = self.visual_description
        elif not self.visual_description and self.visual_direction:
            self.visual_description = self.visual_direction

        # Derive V2 media and layout settings if using legacy defaults
        user_set_avatar = "avatar_enabled" in getattr(self, "__pydantic_fields_set__", set())
        stype = (self.scene_type or "presenter").lower()
        if stype in ("intro", "outro"):
            if self.layout_type in ("presenter_split", "presenter_full"):
                self.layout_type = "presenter_center_with_overlays"
            if not user_set_avatar:
                self.avatar_enabled = True
            if stype == "outro" and self.media_type == "presenter":
                self.media_type = "outro"
        elif stype in ("explanation", "concept"):
            if self.media_type == "presenter":
                self.media_type = "motion_visual"
            if self.layout_type in ("presenter_split", "presenter_left_visual_right"):
                self.layout_type = "media_with_overlay"
            if not user_set_avatar:
                self.avatar_enabled = False
        elif stype in ("visual_demo", "demonstration", "example"):
            if self.media_type == "presenter":
                self.media_type = "broll"
            if self.layout_type in ("presenter_split", "presenter_left_visual_right"):
                self.layout_type = "media_full"
            if not user_set_avatar:
                self.avatar_enabled = False
        elif stype == "quiz":
            self.media_type = "quiz"
            self.layout_type = "quiz_card"
            if not user_set_avatar:
                self.avatar_enabled = False
        elif stype in ("presenter", "recap", "summary"):
            if not user_set_avatar:
                self.avatar_enabled = True
            if self.media_type == "presenter":
                self.media_type = "presenter"

        # Synchronize structured SceneMediaPlan
        if not self.media_plan and self.scene_id:
            self.media_plan = SceneMediaPlan(
                scene_id=self.scene_id,
                purpose=self.purpose or "Content delivery",
                narration=self.narration or "",
                visual_description=self.visual_direction or self.visual_description or self.title or "",
                motion_description=self.motion_description,
                camera_movement=self.camera_movement or "static",
                reference_image_requirements=self.reference_image_requirements,
                preferred_provider=self.preferred_provider,
                target_duration=float(self.estimated_duration_seconds or 5.0),
                aspect_ratio=self.aspect_ratio or "16:9",
            )
        elif self.media_plan:
            if not self.motion_description and self.media_plan.motion_description:
                self.motion_description = self.media_plan.motion_description
            if not self.camera_movement and self.media_plan.camera_movement:
                self.camera_movement = self.media_plan.camera_movement
            if not self.preferred_provider and self.media_plan.preferred_provider:
                self.preferred_provider = self.media_plan.preferred_provider
            if not self.reference_image_requirements and self.media_plan.reference_image_requirements:
                self.reference_image_requirements = self.media_plan.reference_image_requirements

        return self


class ScriptDraft(BaseModel):
    """Structured video script draft representing a complete video module."""

    title: str = Field(..., description="Module title")
    language: str = Field(default="en-US", description="Language code")
    audience: str = Field(default="General Professional", description="Target learner profile")
    target_audience: Optional[str] = Field(default=None, description="Legacy alias for audience")
    learning_objectives: List[LearningObjective] = Field(default_factory=list, description="Target learning objectives")
    opening_hook: str = Field(default="", description="Engaging opening statement for the video")
    scenes: List[SceneDraft] = Field(..., min_length=1, description="Ordered list of scene drafts")
    closing_summary: str = Field(default="", description="Key takeaways and closing sign-off")
    total_estimated_duration_seconds: int = Field(default=0, ge=0, description="Sum of scene estimated durations in seconds")

    @model_validator(mode="after")
    def sync_script_fields(self) -> "ScriptDraft":
        """Synchronize audience aliases and recalculate total duration."""
        if not self.audience and self.target_audience:
            self.audience = self.target_audience
        elif not self.target_audience and self.audience:
            self.target_audience = self.audience

        # Automatically calculate total duration from scenes if not explicitly provided or 0
        computed_total = sum(scene.estimated_duration_seconds for scene in self.scenes)
        if self.total_estimated_duration_seconds == 0 or self.total_estimated_duration_seconds != computed_total:
            self.total_estimated_duration_seconds = computed_total

        return self


class ValidationIssue(BaseModel):
    """Specific defect or warning identified during script validation."""

    code: str = Field(..., description="Machine-readable issue code (e.g., DURATION_MISMATCH, MISSING_NARRATION)")
    severity: str = Field(default="error", description="Issue severity: error, warning")
    message: str = Field(..., description="Human-readable description of the defect")
    scene_id: Optional[str] = Field(default=None, description="Associated scene identifier if applicable")


class ScriptValidationResult(BaseModel):
    """Outcome of deterministic script validation."""

    is_valid: bool = Field(..., description="Whether the script passed all mandatory validation checks")
    issues: List[ValidationIssue] = Field(default_factory=list, description="List of identified validation issues")
    estimated_total_duration_seconds: int = Field(default=0, description="Sum of scene durations")
    duration_difference_seconds: int = Field(default=0, description="Difference between estimate and target duration")
    duration_difference_percent: float = Field(default=0.0, description="Percentage deviation from target duration")
    coverage_report: Optional[Dict[str, Any]] = Field(default=None, description="Deterministic learning objective coverage report")


class FinalScript(BaseModel):
    """Canonical finalized script ready for downstream localization, TTS, and video synthesis."""

    title: str = Field(..., description="Module title")
    language: str = Field(..., description="Language code of canonical script")
    audience: str = Field(..., description="Target audience profile")
    target_duration_seconds: int = Field(..., description="Requested video duration in seconds")
    total_estimated_duration_seconds: int = Field(..., description="Estimated total spoken runtime in seconds")
    opening_hook: str = Field(..., description="Opening attention hook")
    closing_summary: str = Field(..., description="Closing key takeaways")
    learning_objectives: List[LearningObjective] = Field(default_factory=list, description="Covered learning objectives")
    scenes: List[SceneDraft] = Field(..., description="Sequence of production-ready scene specifications")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Pipeline metadata (revisions, timestamps, etc.)")


# =====================================================================
# Step 4: Localization & Cultural Adaptation Schemas
# =====================================================================


class TerminologyEntry(BaseModel):
    """Domain term handling rules during script localization."""

    source_term: str = Field(..., description="Original domain, technical, or branded term")
    preferred_translation: Optional[str] = Field(default=None, description="Explicit localized equivalent if desired")
    preserve_original: bool = Field(default=True, description="Whether to keep the term in original language/script")
    notes: Optional[str] = Field(default=None, description="Contextual guidance for translation or adaptation")


class CulturalGuidance(BaseModel):
    """Culturally appropriate presentation and contextual guidance (non-vendor-specific metadata)."""

    locale: str = Field(..., description="Target normalized locale code (e.g. ar-SA, bn-BD)")
    language_name: Optional[str] = Field(default=None, description="Human-readable language name")
    region_name: Optional[str] = Field(default=None, description="Human-readable region or country name")
    formality_guidance: Optional[str] = Field(default=None, description="Guidance on linguistic register, politeness, and address")
    presenter_style_guidance: Optional[str] = Field(default=None, description="Culturally authentic presentation delivery style")
    attire_guidance: Optional[str] = Field(default=None, description="Contextually appropriate professional presentation attire notes")
    visual_environment_guidance: Optional[str] = Field(default=None, description="Culturally authentic educational/workplace setting notes")
    cultural_notes: List[str] = Field(default_factory=list, description="General educational context and sensitivity notes")


class LocalizedScene(BaseModel):
    """Structurally aligned scene draft for a specific target locale."""

    scene_id: str = Field(..., description="Unique scene identifier strictly matching the source scene (protected)")
    order: int = Field(..., ge=1, description="1-indexed sequence order strictly matching the source scene (protected)")
    title: str = Field(..., description="Localized section or scene title")
    purpose: str = Field(default="Content delivery", description="Localized scene purpose")
    narration: str = Field(..., description="Localized spoken narration script")
    estimated_duration_seconds: int = Field(default=15, ge=1, description="Recalculated duration in seconds from localized narration")
    visual_direction: str = Field(default="", description="Culturally adapted visual guidance metadata")
    on_screen_text: Optional[str] = Field(default=None, description="Localized on-screen text overlay")
    learning_objective_ids: List[str] = Field(default_factory=list, description="Learning objective IDs strictly matching source scene (protected)")
    scene_type: str = Field(default="presenter", description="Scene classification strictly matching source scene (protected)")

    # V2 Media & Layout Engine fields
    media_type: str = Field(default="presenter", description="Media source type matching source scene")
    layout_type: str = Field(default="presenter_left_visual_right", description="Scene layout composition matching source scene")
    visual_prompt: Optional[str] = Field(default=None, description="Localized visual guidance or prompt")
    media_search_terms: List[str] = Field(default_factory=list, description="Localized media search keywords")
    avatar_enabled: bool = Field(default=True, description="Whether presenter avatar is actively rendered for this scene")
    presenter_position: str = Field(default="left", description="Presenter screen placement: left, right, center")
    transition: str = Field(default="fade", description="Scene transition: fade, cut, slide, crossfade")
    media_asset_path: Optional[str] = Field(default=None, description="Custom assigned media path")
    quiz_data: Optional[QuizData] = Field(default=None, description="Localized quiz question and options")
    render_status: Optional[str] = Field(default=None, description="Render status for scene: completed, rendering, failed, or unrendered")
    rendered_video_url: Optional[str] = Field(default=None, description="Static storage URL to rendered scene MP4 if completed")
    has_rendered_asset: bool = Field(default=False, description="True if rendered video asset exists on disk and is completed")

    # Structured Media Planning & Motion Engine fields
    motion_description: Optional[str] = Field(default=None, description="Culturally adapted motion guidance")
    camera_movement: Optional[str] = Field(default="static", description="Camera movement: static, slow zoom-in, pan right, orbital")
    reference_image_requirements: Optional[str] = Field(default=None, description="Reference image or background style requirements")
    preferred_provider: Optional[str] = Field(default=None, description="Preferred provider matching source scene")
    aspect_ratio: str = Field(default="16:9", description="Video aspect ratio: 16:9")
    media_plan: Optional[SceneMediaPlan] = Field(default=None, description="Structured media production plan")

    # Backwards-compatibility fields
    visual_description: Optional[str] = Field(default=None, description="Legacy alias for visual_direction")

    @model_validator(mode="after")
    def sync_localized_scene_fields(self) -> "LocalizedScene":
        """Synchronize V2 defaults for localized scene based on scene_type."""
        user_set_avatar = "avatar_enabled" in getattr(self, "__pydantic_fields_set__", set())
        stype = (self.scene_type or "presenter").lower()
        if stype in ("intro", "outro"):
            if self.layout_type in ("presenter_split", "presenter_full"):
                self.layout_type = "presenter_center_with_overlays"
            if not user_set_avatar:
                self.avatar_enabled = True
            if stype == "outro":
                self.media_type = "outro"
        elif stype in ("explanation", "concept"):
            if self.media_type == "presenter":
                self.media_type = "motion_visual"
            if self.layout_type in ("presenter_split", "presenter_left_visual_right"):
                self.layout_type = "media_with_overlay"
            if not user_set_avatar:
                self.avatar_enabled = False
        elif stype in ("visual_demo", "demonstration", "example"):
            if self.media_type == "presenter":
                self.media_type = "broll"
            if self.layout_type in ("presenter_split", "presenter_left_visual_right"):
                self.layout_type = "media_full"
            if not user_set_avatar:
                self.avatar_enabled = False
        elif stype == "quiz":
            self.media_type = "quiz"
            self.layout_type = "quiz_card"
            if not user_set_avatar:
                self.avatar_enabled = False
        elif stype in ("presenter", "recap", "summary"):
            if not user_set_avatar:
                self.avatar_enabled = True
            if self.media_type == "presenter":
                self.media_type = "presenter"

        if not self.visual_direction and self.visual_description:
            self.visual_direction = self.visual_description
        elif not self.visual_description and self.visual_direction:
            self.visual_description = self.visual_direction

        # Synchronize structured SceneMediaPlan
        if not self.media_plan and self.scene_id:
            self.media_plan = SceneMediaPlan(
                scene_id=self.scene_id,
                purpose=self.purpose or "Content delivery",
                narration=self.narration or "",
                visual_description=self.visual_direction or self.visual_description or self.title or "",
                motion_description=self.motion_description,
                camera_movement=self.camera_movement or "static",
                reference_image_requirements=self.reference_image_requirements,
                preferred_provider=self.preferred_provider,
                target_duration=float(self.estimated_duration_seconds or 5.0),
                aspect_ratio=self.aspect_ratio or "16:9",
            )
        elif self.media_plan:
            if not self.motion_description and self.media_plan.motion_description:
                self.motion_description = self.media_plan.motion_description
            if not self.camera_movement and self.media_plan.camera_movement:
                self.camera_movement = self.media_plan.camera_movement
            if not self.preferred_provider and self.media_plan.preferred_provider:
                self.preferred_provider = self.media_plan.preferred_provider
            if not self.reference_image_requirements and self.media_plan.reference_image_requirements:
                self.reference_image_requirements = self.media_plan.reference_image_requirements

        return self


class LocalizedScript(BaseModel):
    """Complete localized educational video script structurally aligned with canonical FinalScript."""

    title: str = Field(..., description="Localized video module title")
    source_language: str = Field(..., description="Canonical source language/locale code (e.g. en-US)")
    language: str = Field(..., description="Target language identifier")
    locale: str = Field(..., description="Target normalized locale (e.g. ar-SA, bn-BD)")
    text_direction: str = Field(default="ltr", description="Text layout direction: ltr or rtl")
    audience: str = Field(..., description="Target learner profile")
    learning_objectives: List[LearningObjective] = Field(default_factory=list, description="Preserved learning objectives with localized descriptions")
    opening_hook: str = Field(..., description="Localized opening attention hook")
    scenes: List[LocalizedScene] = Field(..., min_length=1, description="Ordered sequence of localized scenes")
    closing_summary: str = Field(..., description="Localized closing takeaways")
    target_duration_seconds: int = Field(..., description="Target total video duration matching canonical script")
    total_estimated_duration_seconds: int = Field(default=0, ge=0, description="Sum of localized scene durations in seconds")
    cultural_guidance: Optional[CulturalGuidance] = Field(default=None, description="Optional presentation guidance for downstream avatar/visual pipelines")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Localization process metadata")


class LocalizationRequest(BaseModel):
    """Specification requesting localization for a canonical FinalScript."""

    source_script: FinalScript = Field(..., description="Canonical immutable source script")
    target_locale: str = Field(..., description="Desired target locale (e.g. ar-SA, bn-BD)")
    adaptation_level: str = Field(
        default="cultural_adaptation",
        description="Adaptation level: translation, natural_localization, cultural_adaptation"
    )
    preserve_terms: Optional[List[str]] = Field(default=None, description="Specific terms to preserve unchanged")
    terminology_entries: Optional[List[TerminologyEntry]] = Field(default=None, description="Structured terminology rules")
    additional_context: Optional[str] = Field(default=None, description="Optional regional or organizational context")


class LocalizationValidationResult(BaseModel):
    """Outcome of deterministic validation for a localized script."""

    is_valid: bool = Field(..., description="Whether localized script passed all deterministic checks")
    issues: List[ValidationIssue] = Field(default_factory=list, description="Identified structural or content defects")
    estimated_total_duration_seconds: int = Field(default=0, description="Sum of localized scene durations")
    duration_difference_seconds: int = Field(default=0, description="Deviation from target duration")
    duration_difference_percent: float = Field(default=0.0, description="Percentage deviation from target duration")


class LocalizationBundle(BaseModel):
    """Container grouping the canonical source script with all requested localized scripts."""

    source_script: FinalScript = Field(..., description="Original canonical script")
    localized_scripts: Dict[str, LocalizedScript] = Field(
        default_factory=dict,
        description="Dictionary of localized scripts keyed by normalized locale (e.g. 'ar-SA')"
    )
    failed_locales: Dict[str, Dict[str, Any]] = Field(
        default_factory=dict,
        description="Dictionary of locales that failed localization or require human review"
    )
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Bundle orchestration metadata")


# =====================================================================
# Step 5: Voice Synthesis & Audio Manifest Schemas
# =====================================================================


class SceneAudioAsset(BaseModel):
    """Synthesized speech audio asset for an individual scene."""

    scene_id: str = Field(..., description="Unique scene identifier matching source and localized scripts")
    locale: str = Field(..., description="Target locale code (e.g. en-US, ar-SA, bn-BD)")
    audio_path: str = Field(..., description="Filesystem path to synthesized audio file (.mp3 / .wav)")
    duration_seconds: float = Field(..., ge=0.0, description="Exact measured audio waveform duration in seconds")
    provider: str = Field(..., description="TTS provider identifier (edge_tts, mock, azure)")
    voice_id: str = Field(..., description="Voice model or identifier used for synthesis")
    status: str = Field(default="completed", description="Synthesis status: completed, failed")
    error: Optional[str] = Field(default=None, description="Diagnostic error message if synthesis failed")


class LocalizedAudioTrack(BaseModel):
    """Collection of synthesized scene audio assets representing a complete localized audio track."""

    locale: str = Field(..., description="Target locale code (e.g. en-US, ar-SA, bn-BD)")
    scene_audio: List[SceneAudioAsset] = Field(default_factory=list, description="Ordered per-scene audio assets")
    total_audio_duration_seconds: float = Field(default=0.0, ge=0.0, description="Sum of measured scene audio durations in seconds")
    status: str = Field(default="completed", description="Track status: completed, partial, failed")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="TTS pipeline metadata")


# =====================================================================
# Step 6: Talking-Head Avatar Video Schemas
# =====================================================================


class AvatarVideoAsset(BaseModel):
    """Talking-head avatar video segment generated for an eligible scene."""

    scene_id: str = Field(..., description="Unique scene identifier matching source and localized scripts")
    locale: str = Field(..., description="Target locale code (e.g. en-US, ar-SA, bn-BD)")
    provider: str = Field(..., description="Avatar provider identifier (heygen, mock)")
    job_id: str = Field(..., description="Job or task identifier assigned by provider")
    video_path: Optional[str] = Field(default=None, description="Filesystem path to retrieved avatar video (.mp4)")
    duration_seconds: float = Field(default=0.0, ge=0.0, description="Duration in seconds of avatar video")
    status: str = Field(default="completed", description="Status: completed, skipped, failed, pending")
    avatar_id: Optional[str] = Field(default=None, description="Avatar identity or persona identifier")
    error: Optional[str] = Field(default=None, description="Diagnostic error message if generation failed")


class LocalizedAvatarTrack(BaseModel):
    """Collection of generated avatar video assets for a localized script."""

    locale: str = Field(..., description="Target locale code")
    scene_avatars: List[AvatarVideoAsset] = Field(default_factory=list, description="List of scene avatar video assets")
    status: str = Field(default="completed", description="Track status: completed, partial, failed")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Avatar generation metadata")


# =====================================================================
# Step 7: Subtitle Asset Schemas (.srt / .vtt)
# =====================================================================


class SubtitleChunk(BaseModel):
    """Single timed caption entry within a subtitle track."""

    index: int = Field(..., ge=1, description="1-indexed sequence order")
    start_seconds: float = Field(..., ge=0.0, description="Start timestamp in seconds")
    end_seconds: float = Field(..., ge=0.0, description="End timestamp in seconds")
    text: str = Field(..., description="Caption text content")


class SceneSubtitleAsset(BaseModel):
    """Generated subtitle files (.srt, .vtt, and .ass) for a specific scene."""

    scene_id: str = Field(..., description="Unique scene identifier")
    locale: str = Field(..., description="Target locale code")
    srt_path: str = Field(..., description="Path to generated .srt file")
    vtt_path: Optional[str] = Field(default=None, description="Path to generated .vtt file")
    ass_path: Optional[str] = Field(default=None, description="Path to generated .ass file with native RTL styling")
    chunk_count: int = Field(default=0, ge=0, description="Total number of caption cues")
    duration_seconds: float = Field(default=0.0, ge=0.0, description="Scene audio duration covered")
    text_direction: str = Field(default="ltr", description="Text layout direction: ltr or rtl")
    status: str = Field(default="completed", description="Status: completed, failed, skipped")
    error: Optional[str] = Field(default=None, description="Diagnostic error message if generation failed")


class LocalizedSubtitleTrack(BaseModel):
    """Collection of scene subtitle assets for a localized script."""

    locale: str = Field(..., description="Target locale code")
    scene_subtitles: List[SceneSubtitleAsset] = Field(default_factory=list, description="Ordered per-scene subtitle assets")
    srt_path: Optional[str] = Field(default=None, description="Path to combined full-track .srt file")
    vtt_path: Optional[str] = Field(default=None, description="Path to combined full-track .vtt file")
    ass_path: Optional[str] = Field(default=None, description="Path to combined full-track .ass file")
    status: str = Field(default="completed", description="Track status: completed, partial, failed")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Subtitle pipeline metadata")


# =====================================================================
# Step 8: Supporting Visual Slide & Background Schemas
# =====================================================================


class SceneVisualAsset(BaseModel):
    """Supporting visual slide, diagram, or background asset generated for a scene."""

    scene_id: str = Field(..., description="Unique scene identifier")
    locale: str = Field(..., description="Target locale code")
    image_path: str = Field(..., description="Filesystem path to generated image (.png)")
    width: int = Field(default=1920, ge=1, description="Image width in pixels")
    height: int = Field(default=1080, ge=1, description="Image height in pixels")
    visual_type: str = Field(default="slide", description="Visual template classification: title_card, concept_slide, demo_slide, background, intro, outro")
    provider: str = Field(default="local", description="Visual asset provider identifier (local, mock)")
    status: str = Field(default="completed", description="Status: completed, failed, skipped")
    error: Optional[str] = Field(default=None, description="Diagnostic error message if generation failed")


class LocalizedVisualTrack(BaseModel):
    """Collection of supporting visual assets for a localized script."""

    locale: str = Field(..., description="Target locale code")
    scene_visuals: List[SceneVisualAsset] = Field(default_factory=list, description="Ordered per-scene visual assets")
    status: str = Field(default="completed", description="Track status: completed, partial, failed")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Visual pipeline metadata")


# =====================================================================
# Step 9: Video Composition Schemas (FFmpeg)
# =====================================================================


class SceneCompositionAsset(BaseModel):
    """Composed video segment for an individual scene."""

    scene_id: str = Field(..., description="Unique scene identifier")
    locale: str = Field(..., description="Target locale code")
    video_path: str = Field(..., description="Filesystem path to composed scene MP4")
    duration_seconds: float = Field(..., ge=0.0, description="Duration in seconds of composed scene video")
    has_avatar: bool = Field(default=False, description="Whether scene contains avatar video segment")
    has_subtitles: bool = Field(default=False, description="Whether subtitles were burned into scene video")
    status: str = Field(default="completed", description="Status: completed, failed, skipped")
    error: Optional[str] = Field(default=None, description="Diagnostic error message if composition failed")


class FinalVideoAsset(BaseModel):
    """Final concatenated multilingual training video for a locale."""

    locale: str = Field(..., description="Target locale code")
    video_path: str = Field(..., description="Filesystem path to final composed training video (.mp4)")
    total_duration_seconds: float = Field(default=0.0, ge=0.0, description="Measured total duration in seconds")
    scene_count: int = Field(default=0, ge=0, description="Number of scenes concatenated")
    scene_videos: List[SceneCompositionAsset] = Field(default_factory=list, description="Ordered per-scene composition assets")
    status: str = Field(default="completed", description="Status: completed, failed, skipped")
    error: Optional[str] = Field(default=None, description="Diagnostic error message if concatenation failed")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Composition metadata")


# =====================================================================
# Step 10: End-to-End Project Manifest & Lifecycle Schemas
# =====================================================================


class ManifestError(BaseModel):
    """Structured diagnostic error record for pipeline stages."""

    stage: str = Field(..., description="Pipeline stage where the error occurred")
    code: str = Field(default="UNKNOWN", description="Machine-readable error code")
    message: str = Field(..., description="Human-readable error description")
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat(), description="ISO 8601 timestamp")
    occurrence_count: int = Field(default=1, ge=1, description="Number of times this error was observed")


def sanitize_diagnostic_message(msg: str) -> str:
    """
    Sanitize diagnostic error messages to strip API keys, Bearer tokens, or authorization data
    before persistence in project manifests or exposure in APIs and UI.
    """
    if not msg:
        return ""
    clean = str(msg)
    try:
        from app.core.config import settings
        if settings.GROQ_API_KEY and len(settings.GROQ_API_KEY) > 6:
            clean = clean.replace(settings.GROQ_API_KEY, "[REDACTED_GROQ_KEY]")
        if settings.HEYGEN_API_KEY and len(settings.HEYGEN_API_KEY) > 6:
            clean = clean.replace(settings.HEYGEN_API_KEY, "[REDACTED_HEYGEN_KEY]")
    except Exception:
        pass

    # Regex redact generic provider keys, tokens, auth headers
    clean = re.sub(r"gsk_[A-Za-z0-9_\-]{15,}", "gsk_[REDACTED]", clean)
    clean = re.sub(r"(?i)bearer\s+[A-Za-z0-9_\-\.]{8,}", "Bearer [REDACTED]", clean)
    clean = re.sub(r"(?i)(api[_-]?key|authorization|token)[\"'\s:=]+[A-Za-z0-9_\-]{10,}", r"\1: [REDACTED]", clean)
    return clean


class ProviderCostItem(BaseModel):
    """Estimated cost component for an external or local generation provider."""

    provider: str = Field(..., description="Provider name: heygen, veo, local_motion, mock, sadtalker")
    usage_unit: str = Field(..., description="Unit of measurement: credits, seconds, scenes")
    quantity: float = Field(default=0.0, ge=0, description="Usage amount")
    rate_per_unit: float = Field(default=0.0, ge=0, description="Rate per unit in USD")
    estimated_cost_usd: float = Field(default=0.0, ge=0, description="Estimated total USD cost")
    details: str = Field(default="", description="Descriptive rationale or pricing SKU note")


class ProjectBudgetEstimate(BaseModel):
    """Complete structured cost breakdown and authorization state for a project."""

    project_id: str = Field(..., description="Project ID")
    status: str = Field(default="not_required", description="Approval status: not_required, pending_approval, approved, rejected")
    total_estimated_cost_usd: float = Field(default=0.0, ge=0, description="Total estimated USD generation cost")
    requires_approval: bool = Field(default=False, description="True if any paid live generation API is requested")
    currency: str = Field(default="USD", description="Currency identifier")
    items: List[ProviderCostItem] = Field(default_factory=list, description="Per-provider cost line items")
    calculated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat(), description="ISO calculation timestamp")
    approved_at: Optional[str] = Field(default=None, description="ISO approval timestamp")
    approved_by: Optional[str] = Field(default=None, description="User or service identity that approved budget")
    notes: Optional[str] = Field(default=None, description="Approval notes or rationale")


class ApproveBudgetRequest(BaseModel):
    """Payload to authorize or reject project generation budget."""

    approved: bool = Field(default=True, description="Whether the budget is approved")
    user_email: Optional[str] = Field(default="admin@workspace.local", description="Approving user email")
    notes: Optional[str] = Field(default=None, description="Optional notes or budget cap remarks")


class ProjectManifest(BaseModel):
    """Persistent project manifest tracking end-to-end lifecycle and artifacts."""

    project_id: str = Field(..., description="Unique project identifier")
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat(), description="ISO 8601 creation timestamp")
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat(), description="ISO 8601 last update timestamp")
    status: str = Field(default="pending", description="Pipeline status: pending, running, completed, needs_review, failed, pending_approval")
    budget_status: str = Field(default="not_required", description="Budget status: not_required, pending_approval, approved, rejected")
    budget: Optional[ProjectBudgetEstimate] = Field(default=None, description="Structured budget estimate breakdown")
    avatar_provider: str = Field(default="mock", description="Selected avatar provider for this project: 'mock', 'sadtalker', 'heygen'")
    source_request: TrainingVideoRequest = Field(..., description="Original input request parameters")

    @model_validator(mode="before")
    @classmethod
    def populate_avatar_provider(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if not data.get("avatar_provider"):
                src = data.get("source_request", {})
                if isinstance(src, dict) and src.get("avatar_provider"):
                    data["avatar_provider"] = str(src["avatar_provider"]).strip().lower()
                else:
                    data["avatar_provider"] = "mock"
            else:
                data["avatar_provider"] = str(data["avatar_provider"]).strip().lower()
        return data
    script_status: str = Field(default="pending", description="Script workflow status: pending, running, completed, failed")
    localization_status: str = Field(default="pending", description="Localization status: pending, running, completed, partial, failed")
    audio_status: str = Field(default="pending", description="Audio synthesis status: pending, running, completed, partial, failed")
    avatar_status: str = Field(default="pending", description="Avatar generation status: pending, running, completed, partial, skipped, failed")
    visual_status: str = Field(default="pending", description="Supporting visuals status: pending, running, completed, partial, failed")
    subtitle_status: str = Field(default="pending", description="Subtitle generation status: pending, running, completed, partial, failed")
    composition_status: str = Field(default="pending", description="Video composition status: pending, running, completed, partial, failed")
    final_script: Optional[FinalScript] = Field(default=None, description="Canonical canonical finalized script")
    localization_bundle: Optional[LocalizationBundle] = Field(default=None, description="Localized scripts bundle")
    audio_tracks: Dict[str, LocalizedAudioTrack] = Field(default_factory=dict, description="Synthesized audio tracks by locale")
    avatar_tracks: Dict[str, LocalizedAvatarTrack] = Field(default_factory=dict, description="Generated avatar tracks by locale")
    visual_tracks: Dict[str, LocalizedVisualTrack] = Field(default_factory=dict, description="Supporting visual tracks by locale")
    subtitle_tracks: Dict[str, LocalizedSubtitleTrack] = Field(default_factory=dict, description="Subtitle tracks by locale")
    final_videos: Dict[str, FinalVideoAsset] = Field(default_factory=dict, description="Composed final training videos by locale")
    error_details: List[ManifestError] = Field(default_factory=list, description="Structured error records with occurrence counts and stages")
    errors: List[str] = Field(default_factory=list, description="Diagnostic error log")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Arbitrary pipeline metadata")

    def record_error(self, stage: str, message: str, code: str = "ERROR") -> None:
        """
        Record or update a structured diagnostic error without duplicating identical messages.
        Sanitizes secret keys and preserves insertion order and occurrence count.
        """
        now = datetime.now(timezone.utc).isoformat()
        clean_msg = sanitize_diagnostic_message(message)
        for err in self.error_details:
            if err.stage == stage and err.message == clean_msg:
                err.occurrence_count += 1
                err.timestamp = now
                return

        new_err = ManifestError(
            stage=stage,
            code=code,
            message=clean_msg,
            timestamp=now,
            occurrence_count=1,
        )
        self.error_details.append(new_err)
        if clean_msg not in self.errors:
            self.errors.append(clean_msg)

    def clear_stage_errors(self, stage: str) -> None:
        """Clear active errors associated with a specific stage upon successful execution/retry."""
        self.error_details = [e for e in self.error_details if e.stage != stage]
        self.errors = [e.message for e in self.error_details]


# =====================================================================
# Step 11: FastAPI Endpoint Request/Response Schemas
# =====================================================================


class CreateProjectRequest(BaseModel):
    """Payload for creating a new video automation project."""

    project_id: Optional[str] = Field(default=None, description="Optional custom unique project ID; auto-generated if omitted")
    request: TrainingVideoRequest = Field(..., description="Target training video configuration")


class RunProjectRequest(BaseModel):
    """Parameters for executing a project pipeline."""

    force_regenerate: bool = Field(default=False, description="Whether to recompute existing valid assets")


class ResumeProjectRequest(BaseModel):
    """Parameters for resuming an interrupted or failed project pipeline."""

    force_regenerate: bool = Field(default=False, description="Whether to force regeneration of incomplete stages")


class ProjectOutputsResponse(BaseModel):
    """Structured response summarizing generated project artifacts."""

    project_id: str = Field(..., description="Project identifier")
    status: str = Field(..., description="Overall pipeline status")
    avatar_provider: str = Field(default="mock", description="Selected avatar provider")
    has_final_script: bool = Field(..., description="Whether final canonical script exists")
    locales: List[str] = Field(default_factory=list, description="Target locales in project")
    audio_tracks: Dict[str, str] = Field(default_factory=dict, description="Audio track status by locale")
    avatar_tracks: Dict[str, str] = Field(default_factory=dict, description="Avatar track status by locale")
    visual_tracks: Dict[str, str] = Field(default_factory=dict, description="Visual track status by locale")
    subtitle_tracks: Dict[str, str] = Field(default_factory=dict, description="Subtitle track status by locale")
    final_videos: Dict[str, str] = Field(default_factory=dict, description="Final video file paths by locale")


class UpdateSceneRequest(BaseModel):
    """Request payload for modifying an individual scene's attributes."""

    title: Optional[str] = Field(default=None, description="Updated scene title")
    narration: Optional[str] = Field(default=None, description="Updated narration text (triggers audio invalidation)")
    media_type: Optional[str] = Field(default=None, description="Updated media source type")
    layout_type: Optional[str] = Field(default=None, description="Updated layout composition")
    avatar_enabled: Optional[bool] = Field(default=None, description="Toggle avatar video generation")
    presenter_position: Optional[str] = Field(default=None, description="Presenter placement: left, right, center")
    on_screen_text: Optional[str] = Field(default=None, description="Updated on-screen text overlay")
    visual_direction: Optional[str] = Field(default=None, description="Updated visual directions")
    visual_prompt: Optional[str] = Field(default=None, description="Updated generative visual prompt")
    transition: Optional[str] = Field(default=None, description="Scene transition: fade, cut, etc.")
    scene_type: Optional[str] = Field(default=None, description="Scene type classification")
    media_asset_path: Optional[str] = Field(default=None, description="Path or filename of custom assigned media")
    quiz_data: Optional[QuizData] = Field(default=None, description="Quiz question and choices")
    estimated_duration_seconds: Optional[int] = Field(default=None, ge=1, description="Estimated duration in seconds")
    target_duration: Optional[int] = Field(default=None, ge=1, description="Target duration in seconds")


class ReorderScenesRequest(BaseModel):
    """Request payload for updating scene sequencing order."""

    scene_order: Optional[List[str]] = Field(default=None, description="Ordered list of scene_ids reflecting new order")
    scene_ids: Optional[List[str]] = Field(default=None, description="Alias for scene_order")

    @model_validator(mode="after")
    def sync_scene_order(self) -> "ReorderScenesRequest":
        if not self.scene_order and self.scene_ids:
            self.scene_order = self.scene_ids
        elif not self.scene_ids and self.scene_order:
            self.scene_ids = self.scene_order
        if not self.scene_order:
            raise ValueError("Either scene_order or scene_ids must be provided.")
        return self


class UpdateProjectRequest(BaseModel):
    """Request payload for updating top-level project metadata and configuration."""

    topic: Optional[str] = Field(default=None, description="Training topic or title")
    video_style: Optional[str] = Field(default=None, description="Video presentation style")
    avatar_provider: Optional[str] = Field(default=None, description="Avatar provider: mock, sadtalker, heygen")
    target_duration_seconds: Optional[int] = Field(default=None, ge=15, le=3600, description="Target duration in seconds")
    target_languages: Optional[List[str]] = Field(default=None, description="Target localized locales")
    branding: Optional[BrandingConfig] = Field(default=None, description="Project branding overrides")


class ProjectSummary(BaseModel):
    """Lightweight dashboard project card summary."""

    project_id: str = Field(..., description="Project ID")
    topic: str = Field(..., description="Project topic or title")
    title: Optional[str] = Field(default=None, description="Display title alias for topic")
    base_language: str = Field(default="en-US", description="Base canonical language")
    source_language: Optional[str] = Field(default=None, description="Display language alias for base_language")
    target_languages: List[str] = Field(default_factory=list, description="Target localization locales")
    target_duration_seconds: int = Field(default=60, description="Target video duration")
    duration_seconds: Optional[float] = Field(default=None, description="Measured or target duration in seconds")
    status: str = Field(default="pending", description="Overall project status")
    avatar_provider: str = Field(default="mock", description="Selected avatar provider")
    video_style: str = Field(default="hybrid_presenter_broll", description="Selected video style")
    created_at: str = Field(default="", description="ISO timestamp created")
    updated_at: str = Field(default="", description="ISO timestamp last updated")
    scenes_count: int = Field(default=0, description="Number of scenes in script")
    completed_locales: List[str] = Field(default_factory=list, description="Locales with completed final videos")
    thumbnail_url: Optional[str] = Field(default=None, description="URL or relative path to project preview thumbnail")
    thumbnail_path: Optional[str] = Field(default=None, description="Alias for thumbnail_url")
    is_legacy: bool = Field(default=False, description="Flag indicating legacy or migrated manifest")
    migration_required: bool = Field(default=False, description="Flag indicating manifest requires schema migration")

    @model_validator(mode="before")
    @classmethod
    def sync_summary_fields_before(cls, data: Any) -> Any:
        if isinstance(data, dict):
            # Sync title <-> topic
            if not data.get("topic") and data.get("title"):
                data["topic"] = data["title"]
            if not data.get("title") and data.get("topic"):
                data["title"] = data["topic"]

            # Sync source_language <-> base_language
            if not data.get("base_language") and data.get("source_language"):
                data["base_language"] = data["source_language"]
            if not data.get("source_language") and data.get("base_language"):
                data["source_language"] = data["base_language"]

            # Sync duration_seconds <-> target_duration_seconds
            if data.get("duration_seconds") is None and data.get("target_duration_seconds") is not None:
                data["duration_seconds"] = float(data["target_duration_seconds"])
            elif data.get("target_duration_seconds") is None and data.get("duration_seconds") is not None:
                data["target_duration_seconds"] = int(round(data["duration_seconds"]))

            # Sync thumbnail_path <-> thumbnail_url
            if not data.get("thumbnail_url") and data.get("thumbnail_path"):
                data["thumbnail_url"] = data["thumbnail_path"]
            if not data.get("thumbnail_path") and data.get("thumbnail_url"):
                data["thumbnail_path"] = data["thumbnail_url"]
        return data

    @model_validator(mode="after")
    def sync_summary_fields_after(self) -> "ProjectSummary":
        if not self.title and self.topic:
            self.title = self.topic
        if not self.topic and self.title:
            self.topic = self.title
        if not self.source_language and self.base_language:
            self.source_language = self.base_language
        if not self.base_language and self.source_language:
            self.base_language = self.source_language
        if self.duration_seconds is None:
            self.duration_seconds = float(self.target_duration_seconds)
        if not self.thumbnail_path and self.thumbnail_url:
            self.thumbnail_path = self.thumbnail_url
        if not self.thumbnail_url and self.thumbnail_path:
            self.thumbnail_url = self.thumbnail_path
        return self


class UploadedMediaItem(BaseModel):
    """Uploaded media item in the project or global media library."""

    filename: str = Field(..., description="Media filename")
    file_path: str = Field(..., description="Filesystem absolute or storage path")
    media_type: str = Field(..., description="Media kind: video or image")
    size_bytes: int = Field(default=0, description="File size in bytes")
    created_at: str = Field(default="", description="ISO upload timestamp")
    url: str = Field(default="", description="API access URL")




