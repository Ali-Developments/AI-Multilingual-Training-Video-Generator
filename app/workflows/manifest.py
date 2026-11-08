import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List, Dict
from uuid import uuid4

from app.core.config import settings
from app.core.logging import logger
from app.models.schemas import ProjectManifest, TrainingVideoRequest


class ProjectManifestManager:
    """
    Manages reading, writing, and listing project.json manifests.
    
    Concurrency & Atomicity (ISSUE-008):
    - Per-project threading locks prevent in-process write collisions.
    - Writes use atomic replace (os.replace from local temporary file) to ensure
      readers never observe partially written or corrupt JSON on Windows or POSIX.
    - Multi-node distributed deployments in future production should migrate persistence
      to PostgreSQL / SQLite with transactional isolation.
    """

    _locks: Dict[str, threading.Lock] = {}
    _global_lock: threading.Lock = threading.Lock()

    def __init__(self, storage_base_dir: Optional[Path] = None) -> None:
        self.storage_base_dir = storage_base_dir or settings.STORAGE_PATH

    @classmethod
    def _get_project_lock(cls, project_id: str) -> threading.Lock:
        """Retrieve or create a synchronized per-project Lock."""
        with cls._global_lock:
            if project_id not in cls._locks:
                cls._locks[project_id] = threading.Lock()
            return cls._locks[project_id]

    def get_project_dir(self, project_id: str) -> Path:
        """Return root directory for a specific project."""
        p_dir = self.storage_base_dir / project_id
        p_dir.mkdir(parents=True, exist_ok=True)
        return p_dir

    def get_manifest_path(self, project_id: str) -> Path:
        """Return filesystem path to project.json."""
        return self.get_project_dir(project_id) / "project.json"

    def load_manifest(self, project_id: str) -> Optional[ProjectManifest]:
        """Load and parse project.json under per-project synchronization."""
        lock = self._get_project_lock(project_id)
        with lock:
            manifest_file = self.get_manifest_path(project_id)
            if not manifest_file.exists():
                return None
            try:
                raw = manifest_file.read_text(encoding="utf-8")
                data = json.loads(raw)
                return ProjectManifest.model_validate(data)
            except Exception as e:
                logger.error("Failed to load project manifest '%s': %s", project_id, e)
                try:
                    raw = manifest_file.read_text(encoding="utf-8")
                    data = json.loads(raw) if raw.strip() else {}
                    if isinstance(data, dict):
                        src_dict = data.get("source_request") if isinstance(data.get("source_request"), dict) else {}
                        topic = data.get("topic") or src_dict.get("topic") or "Legacy Project"
                        base_lang = data.get("base_language") or src_dict.get("base_language") or "en-US"
                        target_langs = data.get("target_languages") or src_dict.get("target_languages") or [base_lang]
                        dur = data.get("target_duration_seconds") or src_dict.get("target_duration_seconds") or 60

                        return ProjectManifest(
                            project_id=project_id,
                            created_at=data.get("created_at") or "",
                            updated_at=data.get("updated_at") or "",
                            status=data.get("status", "needs_review"),
                            avatar_provider=data.get("avatar_provider", "mock"),
                            source_request=TrainingVideoRequest(
                                topic=str(topic),
                                base_language=str(base_lang),
                                target_languages=list(target_langs) if isinstance(target_langs, list) else [str(base_lang)],
                                target_duration_seconds=int(dur) if str(dur).isdigit() else 60,
                            ),
                            errors=[f"Legacy schema or partial corruption: {str(e)}"],
                        )
                except Exception:
                    pass
                return None

    def save_manifest(self, manifest: ProjectManifest) -> Path:
        """
        Persist project manifest to project.json atomically.
        
        Uses per-project lock and temporary file atomic replace (os.replace).
        """
        lock = self._get_project_lock(manifest.project_id)
        with lock:
            manifest.updated_at = datetime.now(timezone.utc).isoformat()
            manifest_path = self.get_manifest_path(manifest.project_id)
            payload = manifest.model_dump_json(indent=2)

            # Write to a unique sibling temporary file in the same directory
            temp_path = manifest_path.parent / f"project.json.{uuid4().hex}.tmp"
            try:
                temp_path.write_text(payload, encoding="utf-8")
                # os.replace provides atomic file replacement on POSIX and Windows (Python 3.3+)
                os.replace(temp_path, manifest_path)
            except Exception:
                if temp_path.exists():
                    try:
                        temp_path.unlink(missing_ok=True)
                    except OSError:
                        pass
                raise

            logger.info("Persisted project manifest for '%s' atomically to %s", manifest.project_id, manifest_path)
            return manifest_path

    def create_manifest(
        self,
        project_id: str,
        request: TrainingVideoRequest,
    ) -> ProjectManifest:
        """Initialize and persist a new pending project manifest."""
        now = datetime.now(timezone.utc).isoformat()
        avatar_prov = str(getattr(request, "avatar_provider", "mock") or "mock").strip().lower()
        manifest = ProjectManifest(
            project_id=project_id,
            created_at=now,
            updated_at=now,
            status="pending",
            avatar_provider=avatar_prov,
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
