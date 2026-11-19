import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List, Dict
from uuid import uuid4

from app.core.config import settings
from app.core.logging import logger
from app.models.schemas import ProjectManifest, TrainingVideoRequest
from app.workflows.script_generation.storage import exclusive, is_locked, load_record


class ProjectManifestManager:
    """
    Manages reading, writing, and listing project.json manifests.

    Concurrency & Atomicity:
    - Per-project OS-backed exclusive lock (.manifest.lock) prevents cross-process
      and cross-thread write collisions on Windows and POSIX.
    - Writes use fsynced temporary file + atomic os.replace.
    - Durable request accounting (script_requests.json) is authoritative and cannot
      be reverted by stale manifest snapshots or corrupt checkpoint files.
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

    def _get_manifest_lock_path(self, project_id: str) -> Path:
        return self.get_project_dir(project_id) / ".manifest.lock"

    @staticmethod
    def _sync_authoritative_request_count(project_dir: Path, manifest: ProjectManifest) -> None:
        """Project authoritative request count from durable RequestLedger (script_requests.json) if present."""
        ledger_path = project_dir / "script_requests.json"
        if ledger_path.exists():
            try:
                ledger_data = load_record(ledger_path)
                records = ledger_data.get("reservations")
                legacy = ledger_data.get("legacy_count", 0)
                if isinstance(records, list) and isinstance(legacy, int) and legacy >= 0:
                    authoritative = legacy + len(records)
                    current = manifest.metadata.get("script_openrouter_requests", 0)
                    current_int = current if isinstance(current, int) and current >= 0 else 0
                    manifest.metadata["script_openrouter_requests"] = max(authoritative, current_int)
                    manifest.metadata["script_request_ledger"] = "script_requests.json"
                    outcomes = ledger_data.get("outcomes", {})
                    if isinstance(outcomes, dict):
                        manifest.metadata["script_completed_responses"] = sum(
                            1 for v in outcomes.values() if isinstance(v, dict) and v.get("status") == "completed"
                        )
                else:
                    manifest.metadata["script_accounting_error"] = "Request accounting file is inconsistent."
            except Exception as exc:
                manifest.metadata["script_accounting_error"] = str(exc)

    def load_manifest(self, project_id: str) -> Optional[ProjectManifest]:
        """Load and parse project.json under per-project OS-backed synchronization."""
        manifest_file = self.storage_base_dir / project_id / "project.json"
        if not manifest_file.exists():
            return None
        with exclusive(self._get_manifest_lock_path(project_id), wait_seconds=5.0):
            if not manifest_file.exists():
                return None
            try:
                raw = manifest_file.read_text(encoding="utf-8")
                data = json.loads(raw)
                manifest = ProjectManifest.model_validate(data)
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
                        preserved_meta = dict(data["metadata"]) if isinstance(data.get("metadata"), dict) else {}

                        recovered = ProjectManifest(
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
                            metadata=preserved_meta,
                            errors=[f"Legacy schema or partial corruption: {str(e)}"],
                        )
                        self._sync_authoritative_request_count(manifest_file.parent, recovered)
                        return recovered
                except Exception:
                    pass
                return None

            # Project authoritative request accounting from durable ledger
            self._sync_authoritative_request_count(manifest_file.parent, manifest)

            # Lease expiry is a read-only projection ONLY when no active OS lock owns the project
            script_lock_path = manifest_file.parent / ".script.lock"
            active_os_lock = script_lock_path.exists() and is_locked(script_lock_path)
            if (
                manifest.script_status == "running"
                and not active_os_lock
                and time.time() >= manifest.metadata.get("script_lease_expires", 0)
            ):
                manifest.script_status = "failed"
                manifest.status = "failed"
                manifest.record_error(
                    "script",
                    "Script worker interrupted or its lease expired. Retry to resume accepted stages.",
                    "SCRIPT_INTERRUPTED",
                )

            # Safely inspect referenced checkpoint without ever triggering legacy fallback or losing metadata
            checkpoint_name = manifest.metadata.get("script_checkpoint")
            if checkpoint_name and isinstance(checkpoint_name, str):
                try:
                    checkpoint_path = (manifest_file.parent / checkpoint_name).resolve()
                    if not checkpoint_path.is_relative_to(manifest_file.parent.resolve()):
                        manifest.metadata["script_checkpoint_error"] = "Referenced checkpoint path escapes project directory."
                    elif not checkpoint_path.exists():
                        manifest.metadata["script_checkpoint_error"] = (
                            f"Referenced checkpoint '{checkpoint_name}' is missing."
                        )
                    else:
                        try:
                            cp_data = load_record(checkpoint_path)
                        except ValueError:
                            # Distinguish corrupt v2/JSON checkpoint from valid legacy v1 dict checkpoint
                            raw_cp = json.loads(checkpoint_path.read_text(encoding="utf-8"))
                            if isinstance(raw_cp, dict) and "checksum" not in raw_cp and isinstance(raw_cp.get("progress"), dict):
                                cp_data = raw_cp
                            else:
                                raise ValueError("Checkpoint envelope is missing checksum or has invalid shape.")
                        raw_progress = cp_data.get("progress")
                        if not isinstance(raw_progress, dict):
                            raise ValueError("Checkpoint 'progress' field is not a dictionary.")
                        progress = dict(raw_progress)
                        if manifest.script_status == "failed":
                            progress = {
                                key: "failed" if value == "running" else value
                                for key, value in progress.items()
                            }
                        manifest.metadata["script_progress"] = progress
                        manifest.metadata.pop("script_checkpoint_error", None)
                except Exception as cp_exc:
                    manifest.metadata["script_checkpoint_error"] = (
                        f"Referenced checkpoint could not be validated (preserved for diagnosis): {cp_exc}"
                    )
            return manifest

    def save_manifest(self, manifest: ProjectManifest) -> Path:
        """
        Persist project manifest to project.json atomically under per-project OS-backed lock.
        Protects durable request accounting against stale manifest snapshot overwrites.
        """
        with exclusive(self._get_manifest_lock_path(manifest.project_id), wait_seconds=5.0):
            manifest_path = self.get_manifest_path(manifest.project_id)

            # Prevent stale manifest snapshots from reverting durable request accounting or ledger references
            if manifest_path.exists():
                try:
                    on_disk = json.loads(manifest_path.read_text(encoding="utf-8"))
                    if isinstance(on_disk, dict) and isinstance(on_disk.get("metadata"), dict):
                        disk_meta = on_disk["metadata"]
                        disk_count = disk_meta.get("script_openrouter_requests")
                        mem_count = manifest.metadata.get("script_openrouter_requests", 0)
                        if isinstance(disk_count, int) and disk_count >= 0:
                            mem_int = mem_count if isinstance(mem_count, int) and mem_count >= 0 else 0
                            manifest.metadata["script_openrouter_requests"] = max(disk_count, mem_int)
                        if disk_meta.get("script_request_ledger") and not manifest.metadata.get("script_request_ledger"):
                            manifest.metadata["script_request_ledger"] = disk_meta["script_request_ledger"]
                except Exception:
                    pass

            self._sync_authoritative_request_count(manifest_path.parent, manifest)

            manifest.updated_at = datetime.now(timezone.utc).isoformat()
            payload = manifest.model_dump_json(indent=2)

            # Write to a unique sibling temporary file in the same directory with fsync + atomic os.replace
            temp_path = manifest_path.parent / f"project.json.{uuid4().hex}.tmp"
            try:
                with temp_path.open("w", encoding="utf-8") as stream:
                    stream.write(payload)
                    stream.flush()
                    os.fsync(stream.fileno())
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
