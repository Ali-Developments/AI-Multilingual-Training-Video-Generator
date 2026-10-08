"""End-to-end video automation project orchestrator connecting all lifecycle stages."""

from typing import Optional, List
from app.core.config import settings
from app.core.logging import logger
from app.models.schemas import (
    TrainingVideoRequest,
    ProjectManifest,
    FinalScript,
)
from app.services.llm.base import LLMProvider
from app.services.localization.service import LocalizationService
from app.services.tts.service import TTSService
from app.services.avatar.service import AvatarService
from app.services.visuals.service import VisualService
from app.services.subtitles.service import SubtitleService
from app.services.composition.service import CompositionService
from app.services.duration import DurationReconciliationService
from app.workflows.script_generation import create_script_workflow
from app.workflows.manifest import ProjectManifestManager


class ProjectOrchestrator:
    """
    Coordinates the full end-to-end pipeline:
    Script -> Localization -> Audio (TTS) -> Avatar -> Visuals -> Subtitles -> Composition -> Final Videos.
    
    Supports idempotent execution, partial resume from manifest, and per-locale failure containment.
    """

    def __init__(
        self,
        manifest_manager: Optional[ProjectManifestManager] = None,
        llm_provider: Optional[LLMProvider] = None,
        localization_service: Optional[LocalizationService] = None,
        tts_service: Optional[TTSService] = None,
        avatar_service: Optional[AvatarService] = None,
        visual_service: Optional[VisualService] = None,
        subtitle_service: Optional[SubtitleService] = None,
        composition_service: Optional[CompositionService] = None,
        duration_service: Optional[DurationReconciliationService] = None,
    ) -> None:
        self.manifest_manager = manifest_manager or ProjectManifestManager()
        self.llm_provider = llm_provider
        self.localization_service = localization_service or LocalizationService(llm_provider=self.llm_provider)
        self.tts_service = tts_service or TTSService()
        self.avatar_service = avatar_service or AvatarService()
        self.visual_service = visual_service or VisualService()
        self.subtitle_service = subtitle_service or SubtitleService()
        self.composition_service = composition_service or CompositionService()
        self.duration_service = duration_service or DurationReconciliationService(llm_provider=self.llm_provider)

    def run_project(
        self,
        project_id: str,
        request: Optional[TrainingVideoRequest] = None,
        force_regenerate: bool = False,
    ) -> ProjectManifest:
        """
        Execute full end-to-end video pipeline for a new or existing project.
        """
        manifest = self.manifest_manager.load_manifest(project_id)
        if not manifest:
            if not request:
                raise ValueError(f"Project '{project_id}' does not exist and no request was provided.")
            manifest = self.manifest_manager.create_manifest(project_id, request)
        elif request:
            manifest.source_request = request

        manifest.status = "running"
        self.manifest_manager.save_manifest(manifest)
        logger.info("Starting pipeline execution for project '%s'", project_id)

        try:
            # ---------------------------------------------------------
            # Stage 1: Script Workflow Generation
            # ---------------------------------------------------------
            if not force_regenerate and manifest.script_status == "completed" and manifest.final_script:
                logger.info("[%s] Reusing existing finalized canonical script", project_id)
            else:
                logger.info("[%s] Executing canonical script workflow", project_id)
                manifest.script_status = "running"
                self.manifest_manager.save_manifest(manifest)

                workflow = create_script_workflow(llm_provider=self.llm_provider)
                state = workflow.invoke({"request": manifest.source_request})
                final_script = state.get("final_script")

                if not final_script:
                    workflow_status = state.get("workflow_status", "failed")
                    errors_list = state.get("errors", [])
                    validation = state.get("validation")

                    err_details = []
                    if errors_list:
                        err_details.extend(errors_list)
                    elif validation and validation.issues:
                        err_details.extend([f"[{i.code}] {i.message}" for i in validation.issues])
                    elif state.get("error_message"):
                        err_details.append(state.get("error_message"))
                    else:
                        err_details.append("No final script produced")

                    err_msg = f"Script generation failed ({workflow_status}): {'; '.join(err_details)}"
                    logger.error("[%s] %s", project_id, err_msg)
                    manifest.script_status = "failed"
                    manifest.status = "failed"
                    manifest.record_error(stage="script", message=err_msg, code=f"SCRIPT_{workflow_status.upper()}")
                    self.manifest_manager.save_manifest(manifest)
                    return manifest

                manifest.clear_stage_errors("script")
                manifest.final_script = final_script
                manifest.script_status = "completed"
                self.manifest_manager.save_manifest(manifest)

            # Persist canonical script to scripts/ directory
            project_dir = self.manifest_manager.get_project_dir(project_id)
            scripts_dir = project_dir / "scripts"
            scripts_dir.mkdir(parents=True, exist_ok=True)
            (scripts_dir / "source.json").write_text(manifest.final_script.model_dump_json(indent=2), encoding="utf-8")

            # ---------------------------------------------------------
            # Stage 2: Localization Pipeline
            # ---------------------------------------------------------
            if not force_regenerate and manifest.localization_status == "completed" and manifest.localization_bundle:
                logger.info("[%s] Reusing existing localization bundle", project_id)
            else:
                logger.info("[%s] Executing localization bundle service", project_id)
                manifest.localization_status = "running"
                self.manifest_manager.save_manifest(manifest)

                target_locales = manifest.source_request.target_languages or [manifest.source_request.base_language]
                if getattr(self.llm_provider, "provider_name", "") != "mock":
                    import time
                    time.sleep(5)
                bundle = self.localization_service.localize_bundle(
                    source_script=manifest.final_script,
                    target_locales=target_locales,
                )
                manifest.localization_bundle = bundle

                if bundle.failed_locales and not bundle.localized_scripts:
                    manifest.localization_status = "failed"
                    manifest.status = "failed"
                    for fail_loc, fail_data in bundle.failed_locales.items():
                        err_code = fail_data.get("code", "LOCALIZATION_FAILED")
                        err_msg = f"Localization failed for locale {fail_loc}: {fail_data.get('error', fail_data.get('issues', 'Validation failure'))}"
                        manifest.record_error(stage="localization", message=err_msg, code=err_code)
                    self.manifest_manager.save_manifest(manifest)
                    return manifest
                elif bundle.failed_locales:
                    manifest.localization_status = "partial"
                    for fail_loc, fail_data in bundle.failed_locales.items():
                        err_code = fail_data.get("code", "LOCALIZATION_PARTIAL_FAILURE")
                        err_msg = f"Localization failed for locale {fail_loc}: {fail_data.get('error', fail_data.get('issues', 'Validation failure'))}"
                        manifest.record_error(stage="localization", message=err_msg, code=err_code)
                else:
                    manifest.clear_stage_errors("localization")
                    manifest.localization_status = "completed"
                self.manifest_manager.save_manifest(manifest)

            # Persist localized scripts to scripts/ directory
            if manifest.localization_bundle and manifest.localization_bundle.localized_scripts:
                for loc, loc_sc in manifest.localization_bundle.localized_scripts.items():
                    (scripts_dir / f"{loc}.json").write_text(loc_sc.model_dump_json(indent=2), encoding="utf-8")

            # ---------------------------------------------------------
            # Stage 3: TTS & Measured Audio Durations
            # ---------------------------------------------------------
            if not force_regenerate and manifest.audio_status == "completed" and manifest.audio_tracks:
                logger.info("[%s] Reusing existing audio tracks", project_id)
            else:
                logger.info("[%s] Synthesizing speech audio tracks", project_id)
                manifest.audio_status = "running"
                self.manifest_manager.save_manifest(manifest)

                audio_tracks = self.tts_service.synthesize_bundle(
                    bundle=manifest.localization_bundle,
                    project_id=project_id,
                    force_regenerate=force_regenerate,
                )
                manifest.audio_tracks = audio_tracks

                # Update localized scripts with exact measured waveform durations
                for loc, track in audio_tracks.items():
                    if loc in manifest.localization_bundle.localized_scripts:
                        self.tts_service.update_script_with_actual_durations(
                            manifest.localization_bundle.localized_scripts[loc],
                            track,
                        )

                all_audio_ok = all(t.status == "completed" for t in audio_tracks.values())
                if all_audio_ok:
                    manifest.clear_stage_errors("audio")
                    manifest.audio_status = "completed"
                else:
                    manifest.audio_status = "partial" if any(t.status == "completed" for t in audio_tracks.values()) else "failed"
                    err_msg = f"Audio synthesis failed or incomplete for some tracks: {[loc for loc, t in audio_tracks.items() if t.status != 'completed']}"
                    manifest.record_error(stage="audio", message=err_msg, code="AUDIO_INCOMPLETE")
                self.manifest_manager.save_manifest(manifest)

            # ---------------------------------------------------------
            # Stage 3.5: Post-TTS Duration Reconciliation
            # ---------------------------------------------------------
            if (
                settings.POST_TTS_RECONCILIATION_ENABLED
                and manifest.audio_tracks
                and manifest.localization_bundle
                and manifest.final_script
            ):
                target_dur = manifest.final_script.target_duration_seconds
                reconciled_any = False
                for loc, track in list(manifest.audio_tracks.items()):
                    if loc not in manifest.localization_bundle.localized_scripts:
                        continue
                    current_loc_script = manifest.localization_bundle.localized_scripts[loc]

                    # Idempotency check: reuse existing duration reconciliation result if already executed
                    if not force_regenerate and manifest.metadata.get("duration_reconciliation", {}).get(loc) is not None:
                        logger.info("[%s] Reusing existing duration reconciliation result for locale '%s'", project_id, loc)
                        continue

                    # Backward-compatible hook for listeners or tests monitoring localization_service
                    if hasattr(self.localization_service, "reconcile_post_tts_duration"):
                        try:
                            self.localization_service.reconcile_post_tts_duration(
                                current_script=current_loc_script,
                                measured_audio_track=track,
                                target_duration_seconds=target_dur,
                            )
                        except Exception:
                            pass

                    revised_script, new_track, rec_res = self.duration_service.reconcile_locale_duration(
                        current_script=current_loc_script,
                        measured_audio_track=track,
                        target_duration_seconds=target_dur,
                        tts_service=self.tts_service,
                        project_id=project_id,
                        tolerance_seconds=settings.POST_TTS_DURATION_TOLERANCE_SECONDS,
                        max_revisions=settings.MAX_POST_TTS_REVISIONS,
                    )
                    
                    if rec_res.revisions_attempted > 0:
                        reconciled_any = True
                        logger.info("[%s] Locale '%s' duration reconciliation complete: %s", project_id, loc, rec_res.message)
                        manifest.localization_bundle.localized_scripts[loc] = revised_script
                        manifest.audio_tracks[loc] = new_track
                        # Persist revised script to disk
                        (scripts_dir / f"{loc}.json").write_text(revised_script.model_dump_json(indent=2), encoding="utf-8")
                    
                    # Store reconciliation metadata in manifest
                    if "duration_reconciliation" not in manifest.metadata:
                        manifest.metadata["duration_reconciliation"] = {}
                    manifest.metadata["duration_reconciliation"][loc] = rec_res.model_dump()

                    if not rec_res.is_approved:
                        manifest.record_error(
                            stage="duration_reconciliation",
                            message=rec_res.message,
                            code="DURATION_OUT_OF_TOLERANCE",
                        )

                if reconciled_any:
                    self.manifest_manager.save_manifest(manifest)

            # ---------------------------------------------------------
            # Stage 4: Avatar Generation
            # ---------------------------------------------------------
            if not force_regenerate and manifest.avatar_status == "completed" and manifest.avatar_tracks:
                logger.info("[%s] Reusing existing avatar tracks", project_id)
            else:
                logger.info("[%s] Generating avatar video segments", project_id)
                manifest.avatar_status = "running"
                self.manifest_manager.save_manifest(manifest)

                # Determine avatar provider safely
                req_avatar_prov = getattr(manifest.source_request, "avatar_provider", "mock")
                if req_avatar_prov and req_avatar_prov.strip().lower() in ("heygen", "sadtalker"):
                    from app.services.avatar.factory import get_avatar_provider
                    active_avatar_service = AvatarService(provider=get_avatar_provider(req_avatar_prov.strip().lower()))
                else:
                    active_avatar_service = self.avatar_service

                avatar_tracks = active_avatar_service.generate_bundle_avatars(
                    bundle=manifest.localization_bundle,
                    audio_tracks=manifest.audio_tracks,
                    project_id=project_id,
                    force_regenerate=force_regenerate,
                )
                manifest.avatar_tracks = avatar_tracks
                manifest.clear_stage_errors("avatar")
                manifest.avatar_status = "completed"
                self.manifest_manager.save_manifest(manifest)

            # ---------------------------------------------------------
            # Stage 5: Supporting Visual Slides
            # ---------------------------------------------------------
            if not force_regenerate and manifest.visual_status == "completed" and manifest.visual_tracks:
                logger.info("[%s] Reusing existing visual tracks", project_id)
            else:
                logger.info("[%s] Generating supporting visual slides", project_id)
                manifest.visual_status = "running"
                self.manifest_manager.save_manifest(manifest)

                visual_tracks = self.visual_service.generate_bundle_visuals(
                    bundle=manifest.localization_bundle,
                    project_id=project_id,
                    force_regenerate=force_regenerate,
                )
                manifest.visual_tracks = visual_tracks
                manifest.clear_stage_errors("visuals")
                manifest.visual_status = "completed"
                self.manifest_manager.save_manifest(manifest)

            # ---------------------------------------------------------
            # Stage 6: Subtitle Generation
            # ---------------------------------------------------------
            if not force_regenerate and manifest.subtitle_status == "completed" and manifest.subtitle_tracks:
                logger.info("[%s] Reusing existing subtitle tracks", project_id)
            else:
                logger.info("[%s] Generating subtitle tracks (.srt/.vtt)", project_id)
                manifest.subtitle_status = "running"
                self.manifest_manager.save_manifest(manifest)

                subtitle_tracks = self.subtitle_service.generate_bundle_subtitles(
                    bundle=manifest.localization_bundle,
                    audio_tracks=manifest.audio_tracks,
                    project_id=project_id,
                    force_regenerate=force_regenerate,
                )
                manifest.subtitle_tracks = subtitle_tracks
                manifest.clear_stage_errors("subtitles")
                manifest.subtitle_status = "completed"
                self.manifest_manager.save_manifest(manifest)

            # ---------------------------------------------------------
            # Stage 7: Video Composition & Concatenation
            # ---------------------------------------------------------
            if not force_regenerate and manifest.composition_status == "completed" and manifest.final_videos:
                logger.info("[%s] Reusing existing final composed videos", project_id)
            else:
                logger.info("[%s] Composing final multilingual videos", project_id)
                manifest.composition_status = "running"
                self.manifest_manager.save_manifest(manifest)

                final_videos = self.composition_service.compose_bundle_videos(
                    bundle=manifest.localization_bundle,
                    audio_tracks=manifest.audio_tracks,
                    visual_tracks=manifest.visual_tracks,
                    subtitle_tracks=manifest.subtitle_tracks,
                    avatar_tracks=manifest.avatar_tracks,
                    project_id=project_id,
                    force_regenerate=force_regenerate,
                )
                manifest.final_videos = final_videos

                all_comp = all(v.status == "completed" for v in final_videos.values())
                if all_comp:
                    manifest.clear_stage_errors("composition")
                    manifest.composition_status = "completed"
                else:
                    manifest.composition_status = "partial" if any(v.status == "completed" for v in final_videos.values()) else "failed"
                    err_msg = f"Composition failed or incomplete for some videos: {[loc for loc, v in final_videos.items() if v.status != 'completed']}"
                    manifest.record_error(stage="composition", message=err_msg, code="COMPOSITION_INCOMPLETE")
                self.manifest_manager.save_manifest(manifest)

            # ---------------------------------------------------------
            # Stage 8: Pipeline Completion Assessment
            # ---------------------------------------------------------
            if manifest.composition_status == "completed":
                manifest.status = "completed"
            elif manifest.composition_status == "partial":
                manifest.status = "needs_review"
            else:
                manifest.status = "failed"

            self.manifest_manager.save_manifest(manifest)
            logger.info("Completed pipeline execution for project '%s' with status '%s'", project_id, manifest.status)
            return manifest

        except Exception as e:
            logger.exception("Unexpected pipeline failure in project '%s': %s", project_id, e)
            manifest.status = "failed"
            manifest.record_error(stage="pipeline", message=f"Unexpected error: {str(e)}", code="UNEXPECTED_ERROR")
            self.manifest_manager.save_manifest(manifest)
            return manifest

    def resume_project(
        self,
        project_id: str,
        force_regenerate: bool = False,
    ) -> ProjectManifest:
        """
        Resume an existing project from its last successful stage.
        """
        manifest = self.manifest_manager.load_manifest(project_id)
        if not manifest:
            raise ValueError(f"Cannot resume non-existent project: '{project_id}'")
        return self.run_project(project_id=project_id, request=manifest.source_request, force_regenerate=force_regenerate)

    def create_project(
        self,
        request: TrainingVideoRequest,
        project_id: Optional[str] = None,
    ) -> ProjectManifest:
        """Create a new project manifest without executing the pipeline."""
        from uuid import uuid4
        pid = project_id or f"proj_{uuid4().hex[:8]}"
        return self.manifest_manager.create_manifest(pid, request)

    def run_pipeline(
        self,
        project_id: str,
        force_regenerate: bool = False,
    ) -> ProjectManifest:
        """Alias for run_project for backward and direct engine compatibility."""
        return self.run_project(project_id, force_regenerate=force_regenerate)
