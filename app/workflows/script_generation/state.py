"""Workflow state definition for video script generation."""

from typing import Optional, List
from pydantic import BaseModel, Field

from app.core.config import settings
from app.models.schemas import (
    TrainingVideoRequest,
    ContentAnalysis,
    ScriptDraft,
    ScriptValidationResult,
    FinalScript,
)


class VideoScriptState(BaseModel):
    """
    Serializable state schema for LangGraph script generation workflow.
    
    Contains strictly serializable domain models and primitives.
    Does NOT contain API keys, client objects, or network handles.
    """

    request: Optional[TrainingVideoRequest] = Field(default=None, description="Normalized incoming request")
    analysis: Optional[ContentAnalysis] = Field(default=None, description="Pedagogical content analysis")
    draft_script: Optional[ScriptDraft] = Field(default=None, description="Active script draft under review/revision")
    validation: Optional[ScriptValidationResult] = Field(default=None, description="Outcome of deterministic validation")
    final_script: Optional[FinalScript] = Field(default=None, description="Approved final canonical script")
    revision_count: int = Field(default=0, ge=0, description="Number of revisions attempted so far")
    max_revisions: int = Field(
        default_factory=lambda: settings.SCRIPT_DEFAULT_MAX_REVISIONS,
        ge=0,
        description="Configured ceiling for revision attempts"
    )
    workflow_status: str = Field(default="processing", description="processing, completed, needs_review, failed")
    errors: List[str] = Field(default_factory=list, description="Diagnostic error messages accumulated during execution")
