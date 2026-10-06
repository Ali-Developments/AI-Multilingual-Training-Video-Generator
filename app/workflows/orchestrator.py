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
    ) -> None:
        self.manifest_manager = manifest_manager or ProjectManifestManager()
        self.llm_provider = llm_provider
        self.localization_service = localization_service or LocalizationService(llm_provider=self.llm_provider)
        self.tts_service = tts_service or TTSService()
        self.avatar_service = avatar_service or AvatarService()
        self.visual_service = visual_service or VisualService()
        self.subtitle_service = subtitle_service or SubtitleService()
        self.composition_service = composition_service or CompositionService()

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
                    err_msg = f"Script generation failed: {state.get('error_message', 'No final script produced')}"
                    logger.error("[%s] %s", project_id, err_msg)
                    manifest.script_status = "failed"
                    manifest.status = "failed"
                    manifest.errors.append(err_msg)
                    self.manifest_manager.save_manifest(manifest)
                    return manifest

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
                bundle = self.localization_service.localize_bundle(
                    source_script=manifest.final_script,
                    target_locales=target_locales,
                )
                manifest.localization_bundle = bundle

                if bundle.failed_locales and not bundle.localized_scripts:
                    manifest.localization_status = "failed"
                    manifest.status = "failed"
                    manifest.errors.append(f"Localization failed for all locales: {list(bundle.failed_locales.keys())}")
                    self.manifest_manager.save_manifest(manifest)
                    return manifest
                elif bundle.failed_locales:
                    manifest.localization_status = "partial"
                else:
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
                manifest.audio_status = "completed" if all_audio_ok else ("partial" if any(t.status == "completed" for t in audio_tracks.values()) else "failed")
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

                avatar_tracks = self.avatar_service.generate_bundle_avatars(
                    bundle=manifest.localization_bundle,
                    audio_tracks=manifest.audio_tracks,
                    project_id=project_id,
                    force_regenerate=force_regenerate,
                )
                manifest.avatar_tracks = avatar_tracks
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
                manifest.composition_status = "completed" if all_comp else ("partial" if any(v.status == "completed" for v in final_videos.values()) else "failed")
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
            manifest.errors.append(f"Unexpected error: {str(e)}")
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
