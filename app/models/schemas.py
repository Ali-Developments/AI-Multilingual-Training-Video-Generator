"""Pydantic schemas for API requests, responses, content analysis, and video scripts."""

import re
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone
from pydantic import BaseModel, Field, model_validator


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
        description="Scene classification (intro, presenter, explanation, visual_demo, example, recap, outro)"
    )

    # Backwards-compatibility fields
    scene_number: Optional[int] = Field(default=None, description="Legacy alias for order")
    visual_description: Optional[str] = Field(default=None, description="Legacy alias for visual_direction")

    @model_validator(mode="after")
    def sync_scene_fields(self) -> "SceneDraft":
        """Synchronize legacy and new field names."""
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


class ProjectManifest(BaseModel):
    """Persistent project manifest tracking end-to-end lifecycle and artifacts."""

    project_id: str = Field(..., description="Unique project identifier")
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat(), description="ISO 8601 creation timestamp")
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat(), description="ISO 8601 last update timestamp")
    status: str = Field(default="pending", description="Pipeline status: pending, running, completed, needs_review, failed")
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




