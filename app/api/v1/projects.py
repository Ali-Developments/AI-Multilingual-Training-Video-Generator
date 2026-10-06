"""FastAPI route handlers for project management and pipeline execution."""

import uuid
from typing import List, Optional
from fastapi import APIRouter, HTTPException, status

from app.core.logging import logger
from app.models.schemas import (
    ProjectManifest,
    CreateProjectRequest,
    RunProjectRequest,
    ResumeProjectRequest,
    ProjectOutputsResponse,
)
from app.workflows.manifest import ProjectManifestManager
from app.workflows.orchestrator import ProjectOrchestrator

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
        has_final_script=manifest.final_script is not None,
        locales=locales,
        audio_tracks={loc: t.status for loc, t in manifest.audio_tracks.items()},
        avatar_tracks={loc: t.status for loc, t in manifest.avatar_tracks.items()},
        visual_tracks={loc: t.status for loc, t in manifest.visual_tracks.items()},
        subtitle_tracks={loc: t.status for loc, t in manifest.subtitle_tracks.items()},
        final_videos=final_vids,
    )
