import os
import shutil
import uuid
from pathlib import Path
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, HTTPException, status, Query, UploadFile, File

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
)
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
        target_langs = m.source_request.target_languages or [m.source_request.base_language]
        thumb = None
        # Check if first scene has visual asset
        if m.visual_tracks:
            for v_trk in m.visual_tracks.values():
                if v_trk.scenes:
                    first_sc = next(iter(v_trk.scenes.values()), None)
                    if first_sc and first_sc.visual_asset_path:
                        thumb = first_sc.visual_asset_path
                        break

        total_dur = 0.0
        if m.audio_tracks:
            for trk in m.audio_tracks.values():
                if trk.total_duration_seconds > 0:
                    total_dur = trk.total_duration_seconds
                    break

        summaries.append(
            ProjectSummary(
                project_id=m.project_id,
                title=m.source_request.topic or "Untitled Project",
                source_language=m.source_request.base_language,
                target_languages=target_langs,
                duration_seconds=total_dur or float(m.source_request.target_duration_seconds),
                status=m.status,
                avatar_provider=m.avatar_provider,
                thumbnail_path=thumb,
                created_at=m.created_at,
                updated_at=m.updated_at,
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

    if locale and manifest.localization_bundle and locale in manifest.localization_bundle.localized_scripts:
        return manifest.localization_bundle.localized_scripts[locale].scenes

    if manifest.final_script:
        return manifest.final_script.scenes

    return []


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
    "/projects/{project_id}/plan-storyboard",
    response_model=ProjectManifest,
    status_code=status.HTTP_200_OK,
    summary="Plan Storyboard",
    description="Run the AI Storyboard Planner on the canonical script.",
)
async def plan_storyboard(
    project_id: str,
    video_style: Optional[VideoStyle] = Query(None, description="Optional style override"),
) -> ProjectManifest:
    manifest = manifest_manager.load_manifest(project_id)
    if not manifest or not manifest.final_script:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project '{project_id}' or final script not found.",
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
    "/providers/status",
    status_code=status.HTTP_200_OK,
    summary="Get Provider Readiness",
    description="Retrieve safe status of avatar, TTS, LLM, and GPU hardware without exposing secrets.",
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
    }


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
