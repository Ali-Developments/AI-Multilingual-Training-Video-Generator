"""Validated script checkpoints with complete generation identity, lineage, and repair persistence."""
from copy import deepcopy
from pathlib import Path
import time
from typing import Any, Callable, Dict, Optional
from uuid import uuid4

from app.core.config import settings
from app.workflows.script_generation.storage import (
    ScriptCancelledError,
    digest,
    load_record,
    save_record,
)


class ScriptCheckpoint:
    VERSION = 2

    @classmethod
    def compute_identity(
        cls,
        request,
        model: str,
        provider: str = "openrouter",
        endpoint: str = "https://openrouter.ai/api/v1",
    ) -> Dict[str, Any]:
        """Compute the complete generation-critical identity dictionary."""
        from app.workflows.script_generation import prompts
        from app.workflows.script_generation.validators import LocaleDurationEstimator
        from app.models.schemas import ContentAnalysis, ScriptOutline, SceneDraft, ScriptDraft

        app_dir = Path(__file__).resolve().parents[2]
        source_files = [
            "workflows/script_generation/prompts.py",
            "workflows/script_generation/nodes.py",
            "workflows/script_generation/staged_generator.py",
            "workflows/script_generation/validators.py",
            "services/llm/schema_utils.py",
            "services/llm/openrouter_provider.py",
            "core/language.py",
            "services/localization/locale_utils.py",
        ]
        critical = {
            key: value
            for key, value in settings.model_dump(mode="json").items()
            if key.startswith("SCRIPT_")
            or key in (
                "OPENROUTER_REASONING_EFFORT",
                "OPENROUTER_REASONING_MIN_OUTPUT_TOKENS",
                "OPENROUTER_FALLBACK_MODELS",
                "OPENROUTER_TIMEOUT_SECONDS",
                "OPENROUTER_ALLOW_PAID_MODELS",
            )
        }
        return {
            "version": cls.VERSION,
            "request": request.model_dump(mode="json"),
            "provider": (provider or "openrouter").strip().lower(),
            "endpoint": (endpoint or "https://openrouter.ai/api/v1").rstrip("/"),
            "model": model,
            "settings": critical,
            "narration_timing": {
                "default_wpm": LocaleDurationEstimator.DEFAULT_WPM,
                "locale_wpm_map": dict(LocaleDurationEstimator.LOCALE_WPM_MAP),
            },
            "sources": {name: digest((app_dir / name).read_text(encoding="utf-8")) for name in source_files},
            "prompts": {
                key: value
                for key, value in vars(prompts).items()
                if key.isupper() and isinstance(value, str)
            },
            "schemas": {
                schema.__name__: schema.model_json_schema()
                for schema in (ContentAnalysis, ScriptOutline, SceneDraft, ScriptDraft)
            },
        }

    @classmethod
    def compute_identity_hash(
        cls,
        request,
        model: str,
        provider: str = "openrouter",
        endpoint: str = "https://openrouter.ai/api/v1",
    ) -> str:
        return digest(cls.compute_identity(request, model, provider=provider, endpoint=endpoint))

    def __init__(
        self,
        directory,
        request,
        model,
        generation="",
        provider="openrouter",
        endpoint="https://openrouter.ai/api/v1",
        required=False,
        run_id: Optional[str] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ):
        identity = self.compute_identity(request, model, provider=provider, endpoint=endpoint)
        self.identity_hash = digest(identity)
        self.run_id = run_id or uuid4().hex
        self._cancel_check = cancel_check
        directory = Path(directory) / "script_checkpoints"
        directory.mkdir(parents=True, exist_ok=True)
        if generation and not all(char in "0123456789abcdef" for char in generation):
            raise ValueError("Invalid checkpoint generation ID.")
        self.path = directory / f"{self.identity_hash}{'-' + generation if generation else ''}.json"
        self.data: Dict[str, Any] = {
            "identity": identity,
            "accepted": {},
            "progress": {},
            "events": [],
            "dependencies": {},
            "history": [],
            "repair_tasks": {},
            "revision_count": 0,
            "final_validated": False,
        }
        if self.path.exists():
            self.data = load_record(self.path)
            if self.data.get("identity") != identity:
                raise ValueError("Script checkpoint identity mismatch.")
            self.validate()
        elif required:
            raise ValueError("Previously referenced script checkpoint is missing. Generation is blocked.")

    def validate(self):
        from app.models.schemas import ContentAnalysis, ScriptOutline, SceneDraft

        data = self.data
        for key in ("accepted", "progress", "dependencies", "repair_tasks"):
            if not isinstance(data.get(key), dict):
                raise ValueError("Invalid checkpoint structure.")
        if not isinstance(data.get("events"), list) or not isinstance(data.get("history"), list):
            raise ValueError("Invalid checkpoint event history.")
        if not isinstance(data.get("revision_count"), int) or data["revision_count"] < 0:
            raise ValueError("Invalid checkpoint revision state.")
        accepted = data["accepted"]
        if "analysis" in accepted:
            ContentAnalysis.model_validate(accepted["analysis"])
        outline = ScriptOutline.model_validate(accepted["outline"]) if "outline" in accepted else None
        for key, value in accepted.items():
            if key in ("analysis", "outline"):
                continue
            scene = SceneDraft.model_validate(value)
            if not outline or key != scene.scene_id or scene.order > len(outline.scene_outlines):
                raise ValueError("Checkpoint scene identity does not match the outline.")
            if outline.scene_outlines[scene.order - 1].scene_id != key:
                raise ValueError("Checkpoint scene order is inconsistent.")
            if data["dependencies"].get(key) != self.dependency(scene.order):
                raise ValueError("Checkpoint scene dependencies are inconsistent.")
            if data["progress"].get(key) != "completed" and key not in data["repair_tasks"]:
                raise ValueError("Checkpoint acceptance and progress disagree.")
            if not any(e.get("key") == key and e.get("status") == "completed" for e in data["events"]):
                raise ValueError("Checkpoint scene has no validation event.")
        for key, status in data["progress"].items():
            if status not in ("pending", "running", "failed", "completed"):
                raise ValueError("Unknown checkpoint progress state.")
            if status == "completed" and key not in accepted:
                raise ValueError("Completed checkpoint stage has no accepted content.")
        for key, task in data["repair_tasks"].items():
            if not isinstance(task, dict) or task.get("scene_item", {}).get("scene_id") != key:
                raise ValueError("Invalid saved repair task.")

    def dependency(self, order):
        accepted = self.data["accepted"]
        return digest({
            "analysis": accepted.get("analysis"),
            "outline": accepted.get("outline"),
            "previous": [accepted.get(f"scene_{i}") for i in range(1, order)],
        })

    def _assert_not_cancelled(self):
        if self._cancel_check is not None and self._cancel_check():
            raise ScriptCancelledError("Script worker was cancelled or exceeded its deadline; state write refused.")

    def _commit(self, candidate_data: Dict[str, Any]) -> None:
        """Persist candidate_data atomically before mutating self.data so failed writes never diverge memory from disk."""
        self._assert_not_cancelled()
        save_record(self.path, candidate_data)
        self.data = candidate_data

    def save(self):
        self._assert_not_cancelled()
        save_record(self.path, self.data)

    def get(self, key, schema):
        if key in self.data["repair_tasks"]:
            return None
        value = self.data["accepted"].get(key)
        return schema.model_validate(value) if value is not None else None

    def put(self, key, value):
        candidate = deepcopy(self.data)
        content = value.model_dump(mode="json")
        old = candidate["accepted"].get(key)
        if old is not None and old != content:
            candidate["history"].append({"key": key, "content": old, "time": time.time(), "run_id": self.run_id})
            if key.startswith("scene_"):
                order = content["order"]
                for later in list(candidate["accepted"]):
                    if later.startswith("scene_") and candidate["accepted"][later]["order"] > order:
                        candidate["history"].append({
                            "key": later,
                            "content": candidate["accepted"].pop(later),
                            "reason": "predecessor_changed",
                            "time": time.time(),
                            "run_id": self.run_id,
                        })
                        candidate["dependencies"].pop(later, None)
                        candidate["progress"][later] = "pending"
        candidate["accepted"][key] = content
        if key.startswith("scene_"):
            candidate["dependencies"][key] = digest({
                "analysis": candidate["accepted"].get("analysis"),
                "outline": candidate["accepted"].get("outline"),
                "previous": [candidate["accepted"].get(f"scene_{i}") for i in range(1, content["order"])],
            })
        candidate["repair_tasks"].pop(key, None)
        stage_label = "scene_validated" if key.startswith("scene_") else "stage_validated"
        candidate["active"] = {"key": key, "attempt": stage_label, "run_id": self.run_id}
        candidate["progress"][key] = "completed"
        candidate["events"].append({
            "time": time.time(),
            "run_id": self.run_id,
            "attempt_id": uuid4().hex[:12],
            "key": key,
            "attempt": stage_label,
            "status": "completed",
            "content_hash": digest(content),
        })
        self._commit(candidate)

    def begin_repair(self, key: str, scene_item, guidance: str) -> None:
        """Persist a pending targeted scene repair task BEFORE calling the LLM so crashes resume repair cleanly."""
        candidate = deepcopy(self.data)
        candidate["repair_tasks"][key] = {
            "scene_item": scene_item.model_dump(mode="json") if hasattr(scene_item, "model_dump") else dict(scene_item),
            "guidance": guidance,
            "time": time.time(),
            "run_id": self.run_id,
        }
        candidate["active"] = {"key": key, "attempt": "targeted_repair", "run_id": self.run_id}
        candidate["progress"][key] = "running"
        candidate["events"].append({
            "time": time.time(),
            "run_id": self.run_id,
            "attempt_id": uuid4().hex[:12],
            "key": key,
            "attempt": "targeted_repair",
            "status": "running",
        })
        self._commit(candidate)

    def pending_repair_tasks(self) -> Dict[str, Any]:
        return deepcopy(self.data.get("repair_tasks", {}))

    def set_revision_count(self, count: int) -> None:
        candidate = deepcopy(self.data)
        candidate["revision_count"] = max(0, int(count))
        self._commit(candidate)

    def event(self, key, attempt, status):
        candidate = deepcopy(self.data)
        candidate["active"] = {"key": key, "attempt": attempt, "run_id": self.run_id}
        candidate["progress"][key] = status
        candidate["events"].append({
            "time": time.time(),
            "run_id": self.run_id,
            "attempt_id": uuid4().hex[:12],
            "key": key,
            "attempt": attempt,
            "status": status,
        })
        self._commit(candidate)

    def pending(self, keys):
        candidate = deepcopy(self.data)
        for key in keys:
            candidate["progress"].setdefault(key, "pending")
        self._commit(candidate)

    def http_event(self, provider):
        candidate = deepcopy(self.data)
        candidate["events"].append({
            "time": time.time(),
            "run_id": self.run_id,
            **candidate.get("active", {}),
            "status": "http_response",
            "reservation_id": getattr(provider, "_reservation_id", None),
            "model": provider.last_routed_model,
            "finish_reason": provider.last_finish_reason,
            "usage": provider.last_usage,
            "category": provider.last_response_classification,
        })
        self._commit(candidate)

    def finish(self, succeeded, reason: Optional[str] = None):
        candidate = deepcopy(self.data)
        attempt_label = reason or "interrupted"
        for key, status in list(candidate["progress"].items()):
            if status == "running":
                candidate["progress"][key] = "failed"
                candidate["events"].append({
                    "time": time.time(),
                    "run_id": self.run_id,
                    "attempt_id": uuid4().hex[:12],
                    "key": key,
                    "attempt": attempt_label,
                    "status": "failed",
                })
        candidate["status"] = "completed" if succeeded else "failed"
        candidate["final_validated"] = bool(succeeded)
        if succeeded:
            candidate["events"].append({
                "time": time.time(),
                "run_id": self.run_id,
                "attempt_id": uuid4().hex[:12],
                "key": "final_script",
                "attempt": "final_validation",
                "status": "completed",
            })
        # Terminal finish is called by the lock-owning run to persist final status cleanly
        # even after a wall-clock timeout or cancellation.
        save_record(self.path, candidate)
        self.data = candidate
