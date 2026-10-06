"""Persistent project manifest manager for project lifecycle and artifacts."""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List

from app.core.config import settings
from app.core.logging import logger
from app.models.schemas import ProjectManifest, TrainingVideoRequest


class ProjectManifestManager:
    """Manages reading, writing, and listing project.json manifests."""

    def __init__(self, storage_base_dir: Optional[Path] = None) -> None:
        self.storage_base_dir = storage_base_dir or settings.STORAGE_PATH

    def get_project_dir(self, project_id: str) -> Path:
        """Return root directory for a specific project."""
        p_dir = self.storage_base_dir / project_id
        p_dir.mkdir(parents=True, exist_ok=True)
        return p_dir

    def get_manifest_path(self, project_id: str) -> Path:
        """Return filesystem path to project.json."""
        return self.get_project_dir(project_id) / "project.json"

    def load_manifest(self, project_id: str) -> Optional[ProjectManifest]:
        """Load and parse project.json if it exists."""
        manifest_file = self.get_manifest_path(project_id)
        if not manifest_file.exists():
            return None
        try:
            raw = manifest_file.read_text(encoding="utf-8")
            data = json.loads(raw)
            return ProjectManifest.model_validate(data)
        except Exception as e:
            logger.error("Failed to load project manifest '%s': %s", project_id, e)
            return None

    def save_manifest(self, manifest: ProjectManifest) -> Path:
        """Persist project manifest to project.json atomically."""
        manifest.updated_at = datetime.now(timezone.utc).isoformat()
        manifest_path = self.get_manifest_path(manifest.project_id)
        payload = manifest.model_dump_json(indent=2)
        manifest_path.write_text(payload, encoding="utf-8")
        logger.info("Persisted project manifest for '%s' to %s", manifest.project_id, manifest_path)
        return manifest_path

    def create_manifest(
        self,
        project_id: str,
        request: TrainingVideoRequest,
    ) -> ProjectManifest:
        """Initialize and persist a new pending project manifest."""
        now = datetime.now(timezone.utc).isoformat()
        manifest = ProjectManifest(
            project_id=project_id,
            created_at=now,
            updated_at=now,
            status="pending",
            source_request=request,
            script_status="pending",
            localization_status="pending",
            audio_status="pending",
            avatar_status="pending",
            visual_status="pending",
            subtitle_status="pending",
            composition_status="pending",
        )
        self.save_manifest(manifest)
        return manifest

    def list_projects(self) -> List[ProjectManifest]:
        """Discover and load all project manifests in storage directory."""
        projects: List[ProjectManifest] = []
        if not self.storage_base_dir.exists():
            return projects

        for item in self.storage_base_dir.iterdir():
            if item.is_dir():
                m_file = item / "project.json"
                if m_file.exists():
                    manifest = self.load_manifest(item.name)
                    if manifest:
                        projects.append(manifest)

        # Sort by updated_at descending
        projects.sort(key=lambda p: p.updated_at, reverse=True)
        return projects
