"""Budget calculation and authorization service for AI video production."""

from datetime import datetime, timezone
from typing import List, Optional
from app.core.config import settings
from app.core.logging import logger
from app.models.schemas import (
    ProjectManifest,
    ProjectBudgetEstimate,
    ProviderCostItem,
)


class BudgetService:
    """Calculates granular pricing estimates for external and cloud generation providers."""

    @classmethod
    def calculate_project_budget(cls, manifest: ProjectManifest) -> ProjectBudgetEstimate:
        """
        Calculate estimated cost for all stages based on requested providers and duration.
        """
        project_id = manifest.project_id
        selected_avatar = (
            getattr(manifest, "avatar_provider", None)
            or (manifest.source_request.avatar_provider if manifest.source_request else None)
            or settings.DEFAULT_AVATAR_PROVIDER
        ).strip().lower()

        target_locales = (
            manifest.source_request.target_languages
            if manifest.source_request and manifest.source_request.target_languages
            else [manifest.source_request.base_language if manifest.source_request else "en-US"]
        )
        locale_count = max(len(target_locales), 1)

        items: List[ProviderCostItem] = []
        scenes = manifest.final_script.scenes if manifest.final_script else []

        # -------------------------------------------------------------
        # 1. HeyGen Presenter Avatar Budget
        # -------------------------------------------------------------
        if selected_avatar == "heygen":
            live_heygen = getattr(settings, "ENABLE_LIVE_HEYGEN", False)
            rate_per_credit = float(getattr(settings, "HEYGEN_PRICE_PER_CREDIT", 0.08))

            if scenes:
                avatar_scenes = [s for s in scenes if getattr(s, "avatar_enabled", True)]
                total_avatar_sec = sum(float(s.estimated_duration_seconds or 15) for s in avatar_scenes)
            else:
                target_sec = manifest.source_request.target_duration_seconds if manifest.source_request else 60
                total_avatar_sec = float(target_sec) * 0.5  # Approx 50% presenter

            total_sec_all_locales = total_avatar_sec * locale_count
            total_minutes = max(total_sec_all_locales / 60.0, 0.5)
            # HeyGen charges ~1 credit per 60 seconds (min 0.5 credits)
            credits_needed = round(total_minutes, 2)
            est_cost = round(credits_needed * rate_per_credit, 2) if live_heygen else 0.0

            items.append(
                ProviderCostItem(
                    provider="heygen",
                    usage_unit="credits",
                    quantity=credits_needed if live_heygen else 0.0,
                    rate_per_unit=rate_per_credit if live_heygen else 0.0,
                    estimated_cost_usd=est_cost,
                    details=(
                        f"HeyGen v2 video generation: ~{credits_needed:.1f} credits for {total_sec_all_locales:.0f}s "
                        f"across {locale_count} locale(s) (${rate_per_credit:.2f}/credit)"
                        if live_heygen
                        else "HeyGen in offline/mock mode (ENABLE_LIVE_HEYGEN=False); $0.00 cost"
                    ),
                )
            )

        # -------------------------------------------------------------
        # 2. Google Veo AI Video Budget
        # -------------------------------------------------------------
        veo_scenes = [
            s for s in scenes
            if getattr(s, "preferred_provider", "") == "veo"
            or getattr(s, "media_type", "") in ("broll", "veo")
        ]
        has_veo = bool(veo_scenes) or getattr(settings, "DEFAULT_MEDIA_PROVIDER", "") == "veo"

        if has_veo:
            live_veo = getattr(settings, "ENABLE_LIVE_VEO", False)
            model_id = getattr(settings, "VEO_MODEL", "veo-3.1-fast-generate-001")
            is_fast = "fast" in model_id.lower()
            rate_per_sec = float(getattr(settings, "VEO_PRICE_PER_SECOND_FAST", 0.15) if is_fast else getattr(settings, "VEO_PRICE_PER_SECOND_STANDARD", 0.40))

            if veo_scenes:
                veo_seconds = sum(float(s.estimated_duration_seconds or 5) for s in veo_scenes)
            else:
                target_sec = manifest.source_request.target_duration_seconds if manifest.source_request else 60
                veo_seconds = float(target_sec) * 0.3

            est_cost = round(veo_seconds * rate_per_sec, 2) if live_veo else 0.0

            items.append(
                ProviderCostItem(
                    provider="veo",
                    usage_unit="seconds",
                    quantity=veo_seconds if live_veo else 0.0,
                    rate_per_unit=rate_per_sec if live_veo else 0.0,
                    estimated_cost_usd=est_cost,
                    details=(
                        f"Google Veo ({model_id}): {veo_seconds:.0f}s B-roll video generation (${rate_per_sec:.2f}/s)"
                        if live_veo
                        else "Google Veo in offline/mock mode (ENABLE_LIVE_VEO=False); $0.00 cost"
                    ),
                )
            )

        # -------------------------------------------------------------
        # 3. Local / Edge Free Services (TTS, FFmpeg, Mock)
        # -------------------------------------------------------------
        items.append(
            ProviderCostItem(
                provider="edge_tts",
                usage_unit="characters",
                quantity=float(sum(len(s.narration) for s in scenes)) if scenes else 500.0,
                rate_per_unit=0.0,
                estimated_cost_usd=0.0,
                details="Free edge-tts localized speech synthesis; $0.00 cost",
            )
        )

        total_cost = round(sum(i.estimated_cost_usd for i in items), 2)
        requires_approval = (total_cost > 0.0)

        existing_status = manifest.budget_status if manifest.budget_status in ("approved", "rejected") else None
        final_status = existing_status or ("pending_approval" if requires_approval else "not_required")

        return ProjectBudgetEstimate(
            project_id=project_id,
            status=final_status,
            total_estimated_cost_usd=total_cost,
            requires_approval=requires_approval,
            currency="USD",
            items=items,
            calculated_at=datetime.now(timezone.utc).isoformat(),
            approved_at=manifest.budget.approved_at if manifest.budget else None,
            approved_by=manifest.budget.approved_by if manifest.budget else None,
            notes=manifest.budget.notes if manifest.budget else None,
        )

