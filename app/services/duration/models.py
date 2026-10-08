"""Models for post-TTS duration reconciliation and scene budgeting."""

from datetime import datetime, timezone
from typing import List, Optional
from pydantic import BaseModel, Field


class SceneDurationBudget(BaseModel):
    """Deterministic duration budget allocation for a single scene."""

    scene_id: str = Field(..., description="Unique scene identifier")
    scene_type: str = Field(..., description="Pedagogical scene type (intro, concept, example, quiz, summary)")
    measured_duration_seconds: float = Field(..., description="Actual measured audio duration before condensation")
    allocated_budget_seconds: float = Field(..., description="Target duration budget allocated to this scene")
    weight: float = Field(default=1.0, description="Pedagogical importance weighting")


class DurationRevisionAttempt(BaseModel):
    """Record of a single post-TTS script condensation and re-synthesis attempt."""

    revision_number: int = Field(..., description="1-based iteration index")
    measured_duration_before: float = Field(..., description="Measured audio duration prior to this revision")
    estimated_duration_after: float = Field(..., description="Estimated duration of revised script text")
    measured_duration_after: Optional[float] = Field(default=None, description="Actual measured TTS duration after re-synthesis")
    compression_ratio: float = Field(..., description="Target/measured compression ratio applied to LLM prompt")
    delta_seconds: float = Field(..., description="Absolute difference between measured duration and target")
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="ISO 8601 timestamp of revision attempt",
    )


class DurationReconciliationResult(BaseModel):
    """Complete outcome of the post-TTS duration reconciliation workflow."""

    locale: str = Field(..., description="Language locale (e.g. ar-SA)")
    target_duration_seconds: float = Field(..., description="Requested video duration in seconds")
    tolerance_seconds: float = Field(..., description="Allowed deviation in seconds (e.g. ±2.0s)")
    initial_duration_seconds: float = Field(..., description="Measured audio duration before any reconciliation")
    final_duration_seconds: float = Field(..., description="Authoritative measured audio duration at end of process")
    revisions_attempted: int = Field(default=0, description="Number of condensation revisions executed")
    max_revisions: int = Field(default=2, description="Configured maximum revision attempts")
    is_approved: bool = Field(default=False, description="Whether final measured duration meets tolerance criteria")
    status: str = Field(
        default="pending",
        description="Reconciliation status: 'approved', 'needs_review', 'within_tolerance', 'disabled'",
    )
    history: List[DurationRevisionAttempt] = Field(default_factory=list, description="Chronological revision attempts")
    scene_budgets: List[SceneDurationBudget] = Field(default_factory=list, description="Scene-level allocated budgets")
    message: str = Field(default="", description="Human-readable outcome summary")
