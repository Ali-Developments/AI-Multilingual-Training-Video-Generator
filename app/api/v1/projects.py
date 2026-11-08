import os
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, HTTPException, status, Query, UploadFile, File
from starlette.concurrency import run_in_threadpool

from app.core.config import settings
from app.core.logging import logger
from app.models.schemas import (
    ProjectManifest,
    CreateProjectRequest,
    RunProjectRequest,
    ResumeProjectRequest,
    ProjectOutputsResponse,
    ProjectSummary,
    UpdateProjectRequest,
    UpdateSceneRequest,
    ReorderScenesRequest,
    UploadedMediaItem,
    VideoStyle,
    SceneDraft,
    LocalizedScene,
    ProjectBudgetEstimate,
    ApproveBudgetRequest,
)
from app.services.budget.service import BudgetService
from app.workflows.manifest import ProjectManifestManager
from app.workflows.orchestrator import ProjectOrchestrator
from app.workflows.storyboard_planner import StoryboardPlanner

router = APIRouter()
manifest_manager = ProjectManifestManager()
orchestrator = ProjectOrchestrator(manifest_manager=manifest_manager)


@router.post(
    "/projects",
    response_model=ProjectManifest,
    status_code=status.HTTP_201_CREATED,
    summary="Create Project",
    description="Initialize a new multilingual training video project manifest.",
)
async def create_project(payload: CreateProjectRequest) -> ProjectManifest:
    project_id = payload.project_id or f"proj_{uuid.uuid4().hex[:12]}"

    existing = manifest_manager.load_manifest(project_id)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Project with ID '{project_id}' already exists.",
        )

    try:
        manifest = manifest_manager.create_manifest(project_id, payload.request)
        logger.info("Created new project manifest: '%s'", project_id)
        return manifest
    except Exception as e:
        logger.error("Failed to create project '%s': %s", project_id, e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Could not create project: {str(e)}",
        )


@router.get(
    "/projects",
    response_model=List[ProjectManifest],
    status_code=status.HTTP_200_OK,
    summary="List Projects",
    description="Retrieve all existing video automation project manifests.",
)
async def list_projects() -> List[ProjectManifest]:
    return manifest_manager.list_projects()


@router.get(
    "/projects/summaries",
    response_model=List[ProjectSummary],
    status_code=status.HTTP_200_OK,
    summary="List Project Summaries",
    description="Retrieve lightweight project summaries for dashboard display.",
)
async def list_project_summaries() -> List[ProjectSummary]:
    manifests = manifest_manager.list_projects()
    summaries: List[ProjectSummary] = []
    for m in manifests:
        try:
            pid = getattr(m, "project_id", "unknown")
            src_req = getattr(m, "source_request", None)
            topic = getattr(src_req, "topic", None) or "Untitled Project"
            base_lang = getattr(src_req, "base_language", "en-US") or "en-US"
            target_langs = (
                getattr(src_req, "target_languages", None)
                or [base_lang]
            )
            target_dur = int(getattr(src_req, "target_duration_seconds", 60) or 60)
            v_style = str(getattr(src_req, "video_style", "hybrid_presenter_broll") or "hybrid_presenter_broll")
            av_prov = str(getattr(m, "avatar_provider", None) or getattr(src_req, "avatar_provider", "mock") or "mock")

            thumb = None
            # Check canonical visual_tracks[locale].scene_visuals
            v_tracks = getattr(m, "visual_tracks", None) or {}
            if isinstance(v_tracks, dict):
                for v_trk in v_tracks.values():
                    # Canonical Pydantic field: scene_visuals
                    scene_visuals = getattr(v_trk, "scene_visuals", None)
                    if scene_visuals is None and isinstance(v_trk, dict):
                        scene_visuals = v_trk.get("scene_visuals") or v_trk.get("visual_assets")

                    if scene_visuals and isinstance(scene_visuals, (list, tuple)):
                        for sc_vis in scene_visuals:
                            img = getattr(sc_vis, "image_path", None)
                            if not img and isinstance(sc_vis, dict):
                                img = sc_vis.get("image_path") or sc_vis.get("visual_asset_path")
                            if img:
                                thumb = img
                                break
                    # Legacy fallback if scenes dictionary exists
                    elif hasattr(v_trk, "scenes") or (isinstance(v_trk, dict) and "scenes" in v_trk):
                        scenes_dict = getattr(v_trk, "scenes", None) if hasattr(v_trk, "scenes") else v_trk.get("scenes")
                        if isinstance(scenes_dict, dict):
                            first_sc = next(iter(scenes_dict.values()), None)
                            if first_sc:
                                img = getattr(first_sc, "visual_asset_path", None) or getattr(first_sc, "image_path", None)
                                if not img and isinstance(first_sc, dict):
                                    img = first_sc.get("visual_asset_path") or first_sc.get("image_path")
                                if img:
                                    thumb = img
                    if thumb:
                        break

            # Audio duration check
            total_dur = 0.0
            a_tracks = getattr(m, "audio_tracks", None) or {}
            if isinstance(a_tracks, dict):
                for trk in a_tracks.values():
                    dur = (
                        getattr(trk, "total_audio_duration_seconds", None)
                        or getattr(trk, "total_duration_seconds", None)
                    )
                    if dur is None and isinstance(trk, dict):
                        dur = trk.get("total_audio_duration_seconds") or trk.get("total_duration_seconds")
                    if dur and float(dur) > 0:
                        total_dur = float(dur)
                        break

            if total_dur == 0.0:
                f_videos = getattr(m, "final_videos", None) or {}
                if isinstance(f_videos, dict):
                    for fv in f_videos.values():
                        dur = getattr(fv, "total_duration_seconds", None) or getattr(fv, "duration_seconds", None)
                        if dur is None and isinstance(fv, dict):
                            dur = fv.get("total_duration_seconds") or fv.get("duration_seconds")
                        if dur and float(dur) > 0:
                            total_dur = float(dur)
                            break

            final_dur = total_dur if total_dur > 0 else float(target_dur)

            # Scene count
            scenes_cnt = 0
            if getattr(m, "final_script", None):
                sc_list = getattr(m.final_script, "scenes", None)
                if isinstance(sc_list, (list, tuple)):
                    scenes_cnt = len(sc_list)

            # Completed locales
            completed_locs: List[str] = []
            f_vids = getattr(m, "final_videos", None) or {}
            if isinstance(f_vids, dict):
                for loc, fv in f_vids.items():
                    st = getattr(fv, "status", None) if not isinstance(fv, dict) else fv.get("status")
                    if st == "completed":
                        completed_locs.append(loc)

            is_legacy = bool(not getattr(src_req, "video_style", None) or not getattr(m, "script_status", None))
            migration_req = bool(is_legacy and getattr(m, "status", "") != "completed")

            summaries.append(
                ProjectSummary(
                    project_id=pid,
                    topic=topic,
                    title=topic,
                    base_language=base_lang,
                    source_language=base_lang,
                    target_languages=target_langs,
                    target_duration_seconds=target_dur,
                    duration_seconds=final_dur,
                    status=getattr(m, "status", "pending"),
                    avatar_provider=av_prov,
                    video_style=v_style,
                    created_at=str(getattr(m, "created_at", "") or ""),
                    updated_at=str(getattr(m, "updated_at", "") or ""),
                    scenes_count=scenes_cnt,
                    completed_locales=completed_locs,
                    thumbnail_url=thumb,
                    thumbnail_path=thumb,
                    is_legacy=is_legacy,
                    migration_required=migration_req,
                )
            )
        except Exception as exc:
            logger.warning(
                "Skipping or generating safe fallback for malformed project %s: %s",
                getattr(m, "project_id", "unknown"),
                exc,
            )
            summaries.append(
                ProjectSummary(
                    project_id=getattr(m, "project_id", f"legacy_{uuid.uuid4().hex[:6]}"),
                    topic=getattr(getattr(m, "source_request", None), "topic", "Legacy Project") or "Legacy Project",
                    title=getattr(getattr(m, "source_request", None), "topic", "Legacy Project") or "Legacy Project",
                    base_language="en-US",
                    source_language="en-US",
                    target_languages=["en-US"],
                    target_duration_seconds=60,
                    duration_seconds=60.0,
                    status=getattr(m, "status", "failed"),
                    avatar_provider="mock",
                    video_style="hybrid_presenter_broll",
                    created_at=str(getattr(m, "created_at", "") or ""),
                    updated_at=str(getattr(m, "updated_at", "") or ""),
                    scenes_count=0,
                    completed_locales=[],
                    thumbnail_url=None,
                    thumbnail_path=None,
                    is_legacy=True,
                    migration_required=True,
                )
            )
    return summaries


@router.get(
    "/projects/{project_id}",
    response_model=ProjectManifest,
    status_code=status.HTTP_200_OK,
    summary="Get Project",
    description="Retrieve complete status manifest for a specific project.",
)
async def get_project(project_id: str) -> ProjectManifest:
    manifest = manifest_manager.load_manifest(project_id)
    if not manifest:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project '{project_id}' not found.",
        )
    return manifest


@router.patch(
    "/projects/{project_id}",
    response_model=ProjectManifest,
    status_code=status.HTTP_200_OK,
    summary="Update Project Details",
    description="Update project topic, style, languages, or branding.",
)
async def update_project(
    project_id: str,
    payload: UpdateProjectRequest,
) -> ProjectManifest:
    manifest = manifest_manager.load_manifest(project_id)
    if not manifest:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project '{project_id}' not found.",
        )

    req = manifest.source_request
    if payload.topic is not None:
        req.topic = payload.topic
    if payload.target_duration_seconds is not None:
        req.target_duration_seconds = payload.target_duration_seconds
    if payload.video_style is not None:
        req.video_style = payload.video_style
    if payload.base_language is not None:
        req.base_language = payload.base_language
    if payload.target_languages is not None:
        req.target_languages = payload.target_languages
    if payload.avatar_provider is not None:
        req.avatar_provider = payload.avatar_provider
        manifest.avatar_provider = payload.avatar_provider
    if payload.branding is not None:
        req.branding = payload.branding

    manifest_manager.save_manifest(manifest)
    return manifest


@router.delete(
    "/projects/{project_id}",
    status_code=status.HTTP_200_OK,
    summary="Delete Project",
    description="Delete project files and manifest from storage.",
)
async def delete_project(project_id: str) -> Dict[str, Any]:
    manifest = manifest_manager.load_manifest(project_id)
    if not manifest:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project '{project_id}' not found.",
        )

    p_dir = manifest_manager.get_project_dir(project_id)
    if p_dir.exists():
        shutil.rmtree(p_dir, ignore_errors=True)
    return {"message": f"Project '{project_id}' successfully deleted.", "project_id": project_id}


@router.post(
    "/projects/{project_id}/duplicate",
    response_model=ProjectManifest,
    status_code=status.HTTP_201_CREATED,
    summary="Duplicate Project",
    description="Create a duplicate copy of an existing project.",
)
async def duplicate_project(project_id: str) -> ProjectManifest:
    manifest = manifest_manager.load_manifest(project_id)
    if not manifest:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project '{project_id}' not found.",
        )

    new_id = f"proj_{uuid.uuid4().hex[:12]}"
    new_req = manifest.source_request.model_copy(deep=True)
    new_req.topic = f"{new_req.topic} (Copy)"
    new_manifest = manifest_manager.create_manifest(new_id, new_req)

    # Copy script and storyboard if available
    if manifest.final_script:
        new_manifest.final_script = manifest.final_script.model_copy(deep=True)
        new_manifest.script_status = "completed"
        manifest_manager.save_manifest(new_manifest)

    return new_manifest


@router.get(
    "/projects/{project_id}/scenes",
    status_code=status.HTTP_200_OK,
    summary="Get Project Scenes",
    description="Retrieve scenes for a specific project and optional locale.",
)
async def get_project_scenes(
    project_id: str,
    locale: Optional[str] = Query(None, description="Optional target locale (e.g. ar-SA)"),
) -> List[Any]:
    manifest = manifest_manager.load_manifest(project_id)
    if not manifest:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project '{project_id}' not found.",
        )

    target_loc = locale or (
        manifest.source_request.target_languages[0]
        if manifest.source_request and manifest.source_request.target_languages
        else (manifest.source_request.base_language if manifest.source_request else "en-US")
    )

    raw_scenes = []
    if locale and manifest.localization_bundle and locale in manifest.localization_bundle.localized_scripts:
        raw_scenes = manifest.localization_bundle.localized_scripts[locale].scenes
    elif manifest.final_script:
        raw_scenes = manifest.final_script.scenes

    if not raw_scenes:
        return []

    # Map composition assets for target_loc if available
    scene_comp_map = {}
    if manifest.final_videos and target_loc in manifest.final_videos:
        fv = manifest.final_videos[target_loc]
        for sc_asset in getattr(fv, "scene_videos", []):
            scene_comp_map[sc_asset.scene_id] = sc_asset

    rendered_dir = manifest_manager.get_project_dir(project_id) / "rendered" / target_loc

    enriched_scenes = []
    for sc in raw_scenes:
        sc_copy = sc.model_copy()
        comp_asset = scene_comp_map.get(sc.scene_id)
        mp4_file = rendered_dir / f"{sc.scene_id}.mp4"

        is_completed = (
            (comp_asset and comp_asset.status == "completed" and Path(comp_asset.video_path).exists() and Path(comp_asset.video_path).stat().st_size > 0)
            or (mp4_file.exists() and mp4_file.stat().st_size > 0)
        )

        if is_completed:
            sc_copy.render_status = "completed"
            sc_copy.has_rendered_asset = True
            sc_copy.rendered_video_url = f"/storage/{project_id}/rendered/{target_loc}/{sc.scene_id}.mp4"
        elif manifest.composition_status == "running":
            sc_copy.render_status = "rendering"
            sc_copy.has_rendered_asset = False
            sc_copy.rendered_video_url = None
        elif comp_asset and comp_asset.status == "failed":
            sc_copy.render_status = "failed"
            sc_copy.has_rendered_asset = False
            sc_copy.rendered_video_url = None
        else:
            sc_copy.render_status = "unrendered"
            sc_copy.has_rendered_asset = False
            sc_copy.rendered_video_url = None

        enriched_scenes.append(sc_copy)

    return enriched_scenes


@router.patch(
    "/projects/{project_id}/scenes/{scene_id}",
    status_code=status.HTTP_200_OK,
    summary="Update Scene",
    description="Update scene properties, narration, media, layout, or quiz data with proper cache invalidation.",
)
async def update_scene(
    project_id: str,
    scene_id: str,
    payload: UpdateSceneRequest,
    locale: Optional[str] = Query(None, description="Target locale for narration update"),
) -> Dict[str, Any]:
    target_locale = locale if isinstance(locale, str) and locale.strip() else None

    manifest = manifest_manager.load_manifest(project_id)
    if not manifest:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project '{project_id}' not found.",
        )

    if not manifest.final_script:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot update scene before script generation.",
        )

    # Locate scene in canonical script
    src_scene = next((s for s in manifest.final_script.scenes if s.scene_id == scene_id), None)
    if not src_scene:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Scene '{scene_id}' not found.",
        )

    narration_changed = False
    layout_or_media_changed = False

    # Apply changes to canonical scene
    if payload.scene_type is not None and payload.scene_type != src_scene.scene_type:
        src_scene.scene_type = payload.scene_type
        layout_or_media_changed = True
    if payload.media_type is not None and payload.media_type != src_scene.media_type:
        src_scene.media_type = payload.media_type
        layout_or_media_changed = True
    if payload.layout_type is not None and payload.layout_type != src_scene.layout_type:
        src_scene.layout_type = payload.layout_type
        layout_or_media_changed = True
    if payload.avatar_enabled is not None and payload.avatar_enabled != src_scene.avatar_enabled:
        src_scene.avatar_enabled = payload.avatar_enabled
        layout_or_media_changed = True
    if payload.presenter_position is not None and payload.presenter_position != src_scene.presenter_position:
        src_scene.presenter_position = payload.presenter_position
        layout_or_media_changed = True
    if payload.transition is not None and payload.transition != src_scene.transition:
        src_scene.transition = payload.transition
        layout_or_media_changed = True
    if payload.media_asset_path is not None and payload.media_asset_path != src_scene.media_asset_path:
        src_scene.media_asset_path = payload.media_asset_path
        layout_or_media_changed = True
    if payload.visual_prompt is not None:
        src_scene.visual_prompt = payload.visual_prompt
    if payload.on_screen_text is not None and payload.on_screen_text != src_scene.on_screen_text:
        src_scene.on_screen_text = payload.on_screen_text
        layout_or_media_changed = True
    if payload.target_duration is not None:
        src_scene.target_duration = payload.target_duration
    if payload.quiz_data is not None:
        src_scene.quiz_data = payload.quiz_data
        layout_or_media_changed = True

    # If updating narration without locale, update canonical
    if payload.narration is not None and not target_locale:
        if payload.narration != src_scene.narration:
            src_scene.narration = payload.narration
            narration_changed = True

    # Update in localized scripts as well
    if manifest.localization_bundle and manifest.localization_bundle.localized_scripts:
        for loc_key, loc_sc in manifest.localization_bundle.localized_scripts.items():
            l_scene = next((s for s in loc_sc.scenes if s.scene_id == scene_id), None)
            if l_scene:
                if payload.media_type is not None:
                    l_scene.media_type = payload.media_type
                if payload.layout_type is not None:
                    l_scene.layout_type = payload.layout_type
                if payload.avatar_enabled is not None:
                    l_scene.avatar_enabled = payload.avatar_enabled
                if payload.presenter_position is not None:
                    l_scene.presenter_position = payload.presenter_position
                if payload.transition is not None:
                    l_scene.transition = payload.transition
                if payload.media_asset_path is not None:
                    l_scene.media_asset_path = payload.media_asset_path
                if payload.quiz_data is not None:
                    l_scene.quiz_data = payload.quiz_data

                if target_locale and loc_key == target_locale and payload.narration is not None:
                    if payload.narration != l_scene.narration:
                        l_scene.narration = payload.narration
                        narration_changed = True

    # Cache invalidation (Phase 28)
    if narration_changed:
        manifest.audio_status = "pending"
        manifest.avatar_status = "pending"
        manifest.subtitle_status = "pending"
        manifest.composition_status = "pending"
        # Reset downstream final videos
        manifest.final_videos.clear()
        manifest.status = "script_completed"
    elif layout_or_media_changed:
        manifest.composition_status = "pending"
        manifest.final_videos.clear()
        if manifest.status == "completed":
            manifest.status = "audio_completed"

    manifest_manager.save_manifest(manifest)
    return {"message": f"Scene '{scene_id}' updated successfully.", "scene": src_scene.model_dump()}


@router.post(
    "/projects/{project_id}/scenes/reorder",
    status_code=status.HTTP_200_OK,
    summary="Reorder Scenes",
    description="Update scene sequence in canonical and localized scripts.",
)
async def reorder_scenes(
    project_id: str,
    payload: ReorderScenesRequest,
) -> Dict[str, Any]:
    manifest = manifest_manager.load_manifest(project_id)
    if not manifest or not manifest.final_script:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project '{project_id}' or final script not found.",
        )

    target_ids = payload.scene_ids or payload.scene_order or []

    # Reorder canonical scenes
    scene_map = {s.scene_id: s for s in manifest.final_script.scenes}
    ordered_scenes: List[SceneDraft] = []
    for idx, sid in enumerate(target_ids):
        if sid in scene_map:
            sc = scene_map[sid]
            sc.order = idx + 1
            ordered_scenes.append(sc)

    # Append any remaining scenes not in list
    for sc in manifest.final_script.scenes:
        if sc.scene_id not in target_ids:
            sc.order = len(ordered_scenes) + 1
            ordered_scenes.append(sc)

    manifest.final_script.scenes = ordered_scenes

    # Reorder localized scripts
    if manifest.localization_bundle and manifest.localization_bundle.localized_scripts:
        for loc_sc in manifest.localization_bundle.localized_scripts.values():
            l_map = {s.scene_id: s for s in loc_sc.scenes}
            ordered_l: List[LocalizedScene] = []
            for idx, sid in enumerate(target_ids):
                if sid in l_map:
                    lsc = l_map[sid]
                    lsc.order = idx + 1
                    ordered_l.append(lsc)
            for lsc in loc_sc.scenes:
                if lsc.scene_id not in target_ids:
                    lsc.order = len(ordered_l) + 1
                    ordered_l.append(lsc)
            loc_sc.scenes = ordered_l

    # Invalidate composition
    manifest.composition_status = "pending"
    manifest.final_videos.clear()
    manifest_manager.save_manifest(manifest)
    return {"message": "Scenes reordered successfully.", "scene_ids": [s.scene_id for s in ordered_scenes]}


@router.post(
    "/projects/{project_id}/generate-script",
    response_model=ProjectManifest,
    status_code=status.HTTP_200_OK,
    summary="Generate Canonical Script",
    description="Generate and validate the canonical script for the project without proceeding to media rendering stages.",
)
async def generate_script(
    project_id: str,
    force_regenerate: bool = Query(False, description="Force regeneration of script even if already completed"),
) -> ProjectManifest:
    manifest = manifest_manager.load_manifest(project_id)
    if not manifest:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "PROJECT_NOT_FOUND",
                "message": f"Project '{project_id}' not found.",
            },
        )

    manifest = await run_in_threadpool(
        orchestrator.generate_canonical_script,
        project_id,
        force_regenerate=force_regenerate,
    )
    if manifest.script_status == "failed" or not manifest.final_script:
        err_msg = f"Failed to generate canonical script for project '{project_id}'."
        if manifest.errors:
            err_msg = str(manifest.errors[-1])
        err_list = [e.model_dump() for e in manifest.error_details] if manifest.error_details else manifest.errors
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "SCRIPT_GENERATION_FAILED",
                "message": err_msg,
                "errors": err_list,
            },
        )
    return manifest


@router.post(
    "/projects/{project_id}/prepare-studio",
    response_model=ProjectManifest,
    status_code=status.HTTP_200_OK,
    summary="Prepare Studio Project",
    description="Bootstrap the studio project by generating canonical script and planning initial storyboard.",
)
async def prepare_studio(
    project_id: str,
    video_style: Optional[VideoStyle] = Query(None, description="Optional style override"),
    force_regenerate: bool = Query(False, description="Force regeneration of script and storyboard"),
) -> ProjectManifest:
    manifest = manifest_manager.load_manifest(project_id)
    if not manifest:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "PROJECT_NOT_FOUND",
                "message": f"Project '{project_id}' not found.",
            },
        )

    manifest = await run_in_threadpool(
        orchestrator.prepare_studio_project,
        project_id,
        video_style=video_style,
        force_regenerate_script=force_regenerate,
        force_regenerate_storyboard=force_regenerate,
    )
    if manifest.script_status == "failed" or not manifest.final_script:
        err_msg = f"Failed to bootstrap script during studio preparation for project '{project_id}'."
        if manifest.errors:
            err_msg = str(manifest.errors[-1])
        err_list = [e.model_dump() for e in manifest.error_details] if manifest.error_details else manifest.errors
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "FINAL_SCRIPT_MISSING",
                "message": err_msg,
                "errors": err_list,
            },
        )
    return manifest


@router.post(
    "/projects/{project_id}/plan-storyboard",
    response_model=ProjectManifest,
    status_code=status.HTTP_200_OK,
    summary="Plan Storyboard",
    description="Run the AI Storyboard Planner on the canonical script.",
)
async def plan_storyboard(
    project_id: str,
    video_style: Optional[VideoStyle] = Query(None, description="Optional style override"),
    auto_generate_script: bool = Query(True, description="Auto-generate canonical script if missing"),
) -> ProjectManifest:
    manifest = manifest_manager.load_manifest(project_id)
    if not manifest:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "PROJECT_NOT_FOUND",
                "message": f"Project '{project_id}' not found.",
            },
        )

    if not manifest.final_script:
        if not auto_generate_script:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "FINAL_SCRIPT_MISSING",
                    "message": f"Project '{project_id}' does not have a canonical script. Generate script before planning storyboard.",
                },
            )

        logger.info("[%s] final_script missing during plan_storyboard. Auto-generating canonical script first...", project_id)
        manifest = await run_in_threadpool(orchestrator.generate_canonical_script, project_id)
        if manifest.script_status == "failed" or not manifest.final_script:
            err_msg = f"Failed to generate canonical script for project '{project_id}'."
            if manifest.errors:
                err_msg = str(manifest.errors[-1])
            err_list = [e.model_dump() for e in manifest.error_details] if manifest.error_details else manifest.errors
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "FINAL_SCRIPT_MISSING",
                    "message": err_msg,
                    "errors": err_list,
                },
            )

    if video_style:
        manifest.source_request.video_style = video_style

    StoryboardPlanner.plan_storyboard(manifest.final_script, manifest.source_request)

    # Propagate to localized scripts
    if manifest.localization_bundle and manifest.localization_bundle.localized_scripts:
        src_map = {s.scene_id: s for s in manifest.final_script.scenes}
        for loc_sc in manifest.localization_bundle.localized_scripts.values():
            for lscene in loc_sc.scenes:
                src_s = src_map.get(lscene.scene_id)
                if src_s:
                    lscene.media_type = src_s.media_type
                    lscene.layout_type = src_s.layout_type
                    lscene.avatar_enabled = src_s.avatar_enabled
                    lscene.presenter_position = src_s.presenter_position
                    lscene.transition = src_s.transition
                    lscene.media_asset_path = src_s.media_asset_path
                    lscene.quiz_data = src_s.quiz_data

    manifest.composition_status = "pending"
    manifest.final_videos.clear()
    manifest_manager.save_manifest(manifest)
    return manifest


@router.post(
    "/projects/{project_id}/media",
    response_model=UploadedMediaItem,
    status_code=status.HTTP_201_CREATED,
    summary="Upload Media Item",
    description="Upload a video or image file to the project's media library.",
)
async def upload_project_media(
    project_id: str,
    file: UploadFile = File(...),
) -> UploadedMediaItem:
    manifest = manifest_manager.load_manifest(project_id)
    if not manifest:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project '{project_id}' not found.",
        )

    media_dir = manifest_manager.get_project_dir(project_id) / "media"
    media_dir.mkdir(parents=True, exist_ok=True)

    safe_name = f"{uuid.uuid4().hex[:8]}_{file.filename}"
    file_path = media_dir / safe_name

    with file_path.open("wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    file_size = file_path.stat().st_size
    content_type = file.content_type or "application/octet-stream"
    media_type = "video" if "video" in content_type or file_path.suffix.lower() in (".mp4", ".mov", ".webm") else "image"

    return UploadedMediaItem(
        media_id=uuid.uuid4().hex[:12],
        project_id=project_id,
        filename=file.filename or safe_name,
        file_path=str(file_path.resolve()),
        media_type=media_type,
        file_size_bytes=file_size,
    )


@router.get(
    "/projects/{project_id}/media",
    response_model=List[UploadedMediaItem],
    status_code=status.HTTP_200_OK,
    summary="List Media Items",
    description="List all uploaded media items in the project library.",
)
async def list_project_media(project_id: str) -> List[UploadedMediaItem]:
    manifest = manifest_manager.load_manifest(project_id)
    if not manifest:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project '{project_id}' not found.",
        )

    media_dir = manifest_manager.get_project_dir(project_id) / "media"
    items: List[UploadedMediaItem] = []
    if media_dir.exists():
        for f in media_dir.iterdir():
            if f.is_file():
                ext = f.suffix.lower()
                m_type = "video" if ext in (".mp4", ".mov", ".webm") else "image"
                items.append(
                    UploadedMediaItem(
                        media_id=f.stem,
                        project_id=project_id,
                        filename=f.name,
                        file_path=str(f.resolve()),
                        media_type=m_type,
                        file_size_bytes=f.stat().st_size,
                    )
                )
    return items


@router.get(
    "/providers",
    status_code=status.HTTP_200_OK,
    summary="Get Provider Readiness",
    description="Retrieve safe status of avatar, video, TTS, LLM, and GPU hardware without exposing secrets.",
)
@router.get(
    "/providers/status",
    status_code=status.HTTP_200_OK,
    summary="Get Provider Readiness",
    description="Retrieve safe status of avatar, video, TTS, LLM, and GPU hardware without exposing secrets.",
)
async def get_providers_status() -> Dict[str, Any]:
    # Check GPU availability safely
    gpu_available = False
    gpu_name = "None"
    try:
        import torch
        if torch.cuda.is_available():
            gpu_available = True
            gpu_name = torch.cuda.get_device_name(0)
    except Exception:
        pass

    # Check SadTalker local environment
    sadtalker_ready = False
    try:
        from app.services.avatar.sadtalker_provider import SadTalkerProvider
        prov = SadTalkerProvider()
        res = prov.check_readiness()
        sadtalker_ready = res.get("ready", False)
    except Exception:
        sadtalker_ready = False

    return {
        "sadtalker": {
            "name": "SadTalker Local",
            "available": sadtalker_ready,
            "gpu_available": gpu_available,
            "gpu_name": gpu_name,
            "ready": sadtalker_ready,
        },
        "heygen": {
            "name": "HeyGen (Cloud)",
            "available": bool(settings.HEYGEN_API_KEY),
            "ready": bool(settings.HEYGEN_API_KEY),
        },
        "groq": {
            "name": "Groq LLM",
            "available": bool(settings.GROQ_API_KEY),
            "ready": bool(settings.GROQ_API_KEY),
        },
        "edge_tts": {
            "name": "Edge-TTS",
            "available": True,
            "ready": True,
        },
        "ffmpeg": {
            "name": "FFmpeg Scene Composer",
            "available": True,
            "ready": True,
        },
        "veo": {
            "name": "Google Veo (Vertex AI)",
            "available": bool(getattr(settings, "GOOGLE_CLOUD_PROJECT", None) or getattr(settings, "GCP_PROJECT_ID", None) or getattr(settings, "GOOGLE_APPLICATION_CREDENTIALS", None)),
            "model": getattr(settings, "VEO_MODEL", "veo-3.1-fast-generate-001"),
            "ready": bool(getattr(settings, "GOOGLE_CLOUD_PROJECT", None) or getattr(settings, "GCP_PROJECT_ID", None) or getattr(settings, "GOOGLE_APPLICATION_CREDENTIALS", None)),
        },
    }


@router.post(
    "/projects/{project_id}/render",
    response_model=ProjectManifest,
    status_code=status.HTTP_200_OK,
    summary="Render Project Video",
    description="Execute the complete rendering pipeline (TTS, avatars, visuals, subtitles, composition) for an approved storyboard.",
)
async def render_project(
    project_id: str,
    payload: Optional[RunProjectRequest] = None,
) -> ProjectManifest:
    manifest = manifest_manager.load_manifest(project_id)
    if not manifest:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project '{project_id}' not found.",
        )

    force_regen = payload.force_regenerate if payload else False
    try:
        updated = orchestrator.run_project(
            project_id=project_id,
            request=manifest.source_request,
            force_regenerate=force_regen,
        )
        return updated
    except Exception as e:
        logger.error("Error rendering project '%s': %s", project_id, e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Project rendering error: {str(e)}",
        )


@router.post(
    "/projects/{project_id}/run",
    response_model=ProjectManifest,
    status_code=status.HTTP_200_OK,
    summary="Run Project Pipeline",
    description="Execute the complete end-to-end pipeline for the given project.",
)
async def run_project(
    project_id: str,
    payload: Optional[RunProjectRequest] = None,
) -> ProjectManifest:
    manifest = manifest_manager.load_manifest(project_id)
    if not manifest:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project '{project_id}' not found.",
        )

    force_regen = payload.force_regenerate if payload else False
    try:
        updated = orchestrator.run_project(
            project_id=project_id,
            request=manifest.source_request,
            force_regenerate=force_regen,
        )
        return updated
    except Exception as e:
        logger.error("Error executing project '%s': %s", project_id, e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Project execution error: {str(e)}",
        )


@router.post(
    "/projects/{project_id}/resume",
    response_model=ProjectManifest,
    status_code=status.HTTP_200_OK,
    summary="Resume Project Pipeline",
    description="Resume an interrupted or failed project from its last successful stage.",
)
async def resume_project(
    project_id: str,
    payload: Optional[ResumeProjectRequest] = None,
) -> ProjectManifest:
    manifest = manifest_manager.load_manifest(project_id)
    if not manifest:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project '{project_id}' not found.",
        )

    force_regen = payload.force_regenerate if payload else False
    try:
        updated = orchestrator.resume_project(
            project_id=project_id,
            force_regenerate=force_regen,
        )
        return updated
    except Exception as e:
        logger.error("Error resuming project '%s': %s", project_id, e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Project resume error: {str(e)}",
        )


@router.get(
    "/projects/{project_id}/outputs",
    response_model=ProjectOutputsResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Project Outputs",
    description="Retrieve summary of generated artifacts, audio tracks, and final videos.",
)
async def get_project_outputs(project_id: str) -> ProjectOutputsResponse:
    manifest = manifest_manager.load_manifest(project_id)
    if not manifest:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project '{project_id}' not found.",
        )

    locales = (
        list(manifest.localization_bundle.localized_scripts.keys())
        if manifest.localization_bundle
        else []
    )
    final_vids = {
        loc: v.video_path
        for loc, v in manifest.final_videos.items()
        if v.status == "completed" and v.video_path
    }

    return ProjectOutputsResponse(
        project_id=manifest.project_id,
        status=manifest.status,
        avatar_provider=getattr(manifest, "avatar_provider", "mock"),
        has_final_script=manifest.final_script is not None,
        locales=locales,
        audio_tracks={loc: t.status for loc, t in manifest.audio_tracks.items()},
        avatar_tracks={loc: t.status for loc, t in manifest.avatar_tracks.items()},
        visual_tracks={loc: t.status for loc, t in manifest.visual_tracks.items()},
        subtitle_tracks={loc: t.status for loc, t in manifest.subtitle_tracks.items()},
        final_videos=final_vids,
    )


@router.get(
    "/projects/{project_id}/budget",
    response_model=ProjectBudgetEstimate,
    status_code=status.HTTP_200_OK,
    summary="Get Project Budget Estimate",
    description="Calculate and retrieve granular estimated generation costs across external providers.",
)
async def get_project_budget(project_id: str) -> ProjectBudgetEstimate:
    manifest = manifest_manager.load_manifest(project_id)
    if not manifest:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project '{project_id}' not found.",
        )
    est = BudgetService.calculate_project_budget(manifest)
    manifest.budget = est
    manifest.budget_status = est.status
    manifest_manager.save_manifest(manifest)
    return est


@router.post(
    "/projects/{project_id}/approve-budget",
    response_model=ProjectBudgetEstimate,
    status_code=status.HTTP_200_OK,
    summary="Approve or Reject Project Budget",
    description="Authorize external generation costs, unlocking the budget gate for live API rendering.",
)
async def approve_project_budget(
    project_id: str,
    payload: ApproveBudgetRequest,
) -> ProjectBudgetEstimate:
    manifest = manifest_manager.load_manifest(project_id)
    if not manifest:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project '{project_id}' not found.",
        )

    est = BudgetService.calculate_project_budget(manifest)
    if payload.approved:
        est.status = "approved"
        est.approved_at = datetime.now(timezone.utc).isoformat()
        est.approved_by = payload.user_email or "admin"
        est.notes = payload.notes
        manifest.budget_status = "approved"
        manifest.clear_stage_errors("budget_gate")
        if manifest.status == "pending_approval":
            manifest.status = "pending"
    else:
        est.status = "rejected"
        est.notes = payload.notes
        manifest.budget_status = "rejected"
        manifest.status = "needs_review"
        manifest.record_error(
            stage="budget_gate",
            message=f"Budget authorization rejected by {payload.user_email or 'user'}.",
            code="BUDGET_REJECTED",
        )

    manifest.budget = est
    manifest_manager.save_manifest(manifest)
    return est


@router.get(
    "/projects/{project_id}/status",
    status_code=status.HTTP_200_OK,
    summary="Get Detailed Project Status & Active Jobs",
    description="Track lifecycle progression, active jobs, budget state, and error logs.",
)
async def get_project_status(project_id: str) -> Dict[str, Any]:
    manifest = manifest_manager.load_manifest(project_id)
    if not manifest:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project '{project_id}' not found.",
        )

    stages = {
        "script": manifest.script_status,
        "localization": manifest.localization_status,
        "audio": manifest.audio_status,
        "avatar": manifest.avatar_status,
        "visuals": manifest.visual_status,
        "subtitles": manifest.subtitle_status,
        "composition": manifest.composition_status,
    }
    completed_stages = sum(1 for s in stages.values() if s == "completed")
    progress_percent = round((completed_stages / len(stages)) * 100)

    return {
        "project_id": manifest.project_id,
        "status": manifest.status,
        "progress_percent": progress_percent,
        "stages": stages,
        "budget_status": getattr(manifest, "budget_status", "not_required"),
        "budget": manifest.budget.model_dump() if getattr(manifest, "budget", None) else None,
        "errors": manifest.errors,
        "error_details": [e.model_dump() for e in manifest.error_details],
        "created_at": manifest.created_at,
        "updated_at": manifest.updated_at,
    }


@router.post(
    "/projects/{project_id}/retry",
    response_model=ProjectManifest,
    status_code=status.HTTP_200_OK,
    summary="Retry Project Execution",
    description="Resume pipeline execution, clearing transient errors and resuming uncompleted stages.",
)
async def retry_project_execution(project_id: str) -> ProjectManifest:
    manifest = manifest_manager.load_manifest(project_id)
    if not manifest:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project '{project_id}' not found.",
        )

    try:
        updated = orchestrator.resume_project(project_id=project_id, force_regenerate=False)
        return updated
    except Exception as e:
        logger.error("Error retrying project '%s': %s", project_id, e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Retry error: {str(e)}",
        )
