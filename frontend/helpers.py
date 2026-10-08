"""Frontend helper utilities and client functions for Streamlit Studio."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

try:
    from app.core.config import settings
    from app.models.schemas import TrainingVideoRequest
    from app.workflows.manifest import ProjectManifestManager
    from app.workflows.orchestrator import ProjectOrchestrator
    DIRECT_ENGINE_AVAILABLE = True
except ImportError:
    DIRECT_ENGINE_AVAILABLE = False
    settings = None
    ProjectManifestManager = None
    ProjectOrchestrator = None
    TrainingVideoRequest = None

logger = logging.getLogger(__name__)
DEFAULT_BACKEND_URL = "http://localhost:8000"


def check_backend_health(base_url: str) -> Optional[Dict[str, Any]]:
    """Query FastAPI health endpoint."""
    try:
        resp = httpx.get(f"{base_url.rstrip('/')}/api/v1/health", timeout=3.0)
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return None


def fetch_projects_via_api(base_url: str) -> List[Dict[str, Any]]:
    """Fetch all projects from backend API."""
    try:
        resp = httpx.get(f"{base_url.rstrip('/')}/api/v1/projects", timeout=5.0)
        if resp.status_code == 200:
            return resp.json()
    except Exception as e:
        logger.warning(f"Error fetching projects via API: {e}")
    return []


def fetch_project_manifest_via_api(base_url: str, project_id: str) -> Optional[Dict[str, Any]]:
    """Fetch specific project manifest from backend API."""
    try:
        resp = httpx.get(f"{base_url.rstrip('/')}/api/v1/projects/{project_id}", timeout=5.0)
        if resp.status_code == 200:
            return resp.json()
    except Exception as e:
        logger.warning(f"Error fetching project manifest via API: {e}")
    return None


def run_project_via_api(base_url: str, project_id: str, force_regenerate: bool = False) -> Optional[Dict[str, Any]]:
    """Execute project pipeline via backend API."""
    try:
        resp = httpx.post(
            f"{base_url.rstrip('/')}/api/v1/projects/{project_id}/run",
            json={"force_regenerate": force_regenerate},
            timeout=180.0,
        )
        if resp.status_code == 200:
            return resp.json()
    except Exception as e:
        logger.error(f"Pipeline execution request failed: {e}")
    return None


def resume_project_via_api(base_url: str, project_id: str) -> Optional[Dict[str, Any]]:
    """Resume interrupted project pipeline via backend API."""
    try:
        resp = httpx.post(
            f"{base_url.rstrip('/')}/api/v1/projects/{project_id}/resume",
            timeout=180.0,
        )
        if resp.status_code == 200:
            return resp.json()
    except Exception as e:
        logger.error(f"Pipeline resume request failed: {e}")
    return None


class APIClientError(Exception):
    """Exception raised when backend API returns a non-2xx response or network error."""

    def __init__(self, status_code: int, message: str, detail: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.message = message
        self.detail = detail

    def __str__(self) -> str:
        return f"[HTTP {self.status_code}] {self.message}"


def format_api_error_detail(detail: Any) -> str:
    """Format FastAPI validation detail into clear, human-readable bullet points."""
    if isinstance(detail, list):
        formatted = []
        for item in detail:
            if isinstance(item, dict):
                loc_list = [str(elem) for elem in item.get("loc", []) if elem != "body"]
                loc_str = " -> ".join(loc_list) if loc_list else "root"
                msg = item.get("msg", "Validation error")
                err_type = item.get("type", "")
                type_tag = f" ({err_type})" if err_type else ""
                formatted.append(f"- **Field `{loc_str}`**: {msg}{type_tag}")
            else:
                formatted.append(f"- {str(item)}")
        return "\n".join(formatted)
    elif isinstance(detail, dict):
        return "\n".join(f"- **{k}**: {v}" for k, v in detail.items())
    elif isinstance(detail, str):
        return detail
    return str(detail) if detail is not None else "No additional error details provided."


def serialize_create_project_payload(
    topic: Optional[str] = None,
    source_content: Optional[str] = None,
    audience: str = "General Professional / Adult Learner",
    base_language: str = "en-US",
    target_languages: Optional[List[str]] = None,
    target_duration_seconds: int = 120,
    tone: str = "engaging and professional",
    difficulty_level: Optional[str] = None,
    learning_objectives: Optional[List[str]] = None,
    locale: Optional[str] = None,
    project_id: Optional[str] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Serialize frontend UI inputs into the canonical CreateProjectRequest payload.

    Ensures target_languages (instead of target_locales) and difficulty_level
    (instead of difficulty) are mapped correctly, and wraps fields inside the
    expected {'project_id': ..., 'request': {...}} schema.
    """
    target_langs = target_languages or kwargs.get("target_locales") or ["en-US"]
    diff = difficulty_level or kwargs.get("difficulty") or "intermediate"

    req_body: Dict[str, Any] = {
        "audience": audience,
        "base_language": base_language,
        "target_languages": target_langs,
        "target_duration_seconds": target_duration_seconds,
        "tone": tone,
        "difficulty_level": diff,
    }
    if topic and topic.strip():
        req_body["topic"] = topic.strip()
    else:
        req_body["topic"] = None

    if source_content and source_content.strip():
        req_body["source_content"] = source_content.strip()
    else:
        req_body["source_content"] = None

    if learning_objectives:
        cleaned_objs = [obj.strip() for obj in learning_objectives if obj and obj.strip()]
        req_body["learning_objectives"] = cleaned_objs if cleaned_objs else None
    else:
        req_body["learning_objectives"] = None

    if locale and locale.strip():
        req_body["locale"] = locale.strip()
    else:
        req_body["locale"] = None

    req_body["avatar_provider"] = kwargs.get("avatar_provider", "mock")
    req_body["ack_paid_credits"] = kwargs.get("ack_paid_credits", False)

    return {
        "project_id": project_id,
        "request": req_body,
    }


def create_project_via_api(
    base_url: str,
    payload: Dict[str, Any],
    raise_for_status: bool = True,
) -> Optional[Dict[str, Any]]:
    """Create project via backend API.

    Automatically normalizes payload if flat dictionary is passed.
    Raises APIClientError if raise_for_status=True and backend returns non-2xx.
    """
    # Normalize if not already wrapped in {"request": ...}
    if "request" not in payload or not isinstance(payload.get("request"), dict):
        normalized = serialize_create_project_payload(**payload)
    else:
        # Canonicalize field names inside request if legacy names were passed
        req_inner = dict(payload["request"])
        if "target_locales" in req_inner and "target_languages" not in req_inner:
            req_inner["target_languages"] = req_inner.pop("target_locales")
        if "difficulty" in req_inner and "difficulty_level" not in req_inner:
            req_inner["difficulty_level"] = req_inner.pop("difficulty")
        normalized = {
            "project_id": payload.get("project_id"),
            "request": req_inner,
        }

    try:
        resp = httpx.post(
            f"{base_url.rstrip('/')}/api/v1/projects",
            json=normalized,
            timeout=10.0,
        )
        if resp.status_code in (200, 201):
            return resp.json()

        error_detail = None
        error_msg = f"API returned status {resp.status_code}"
        try:
            err_json = resp.json()
            error_detail = err_json.get("detail", err_json)
            if isinstance(error_detail, str):
                error_msg = error_detail
            elif isinstance(error_detail, list) and len(error_detail) > 0 and isinstance(error_detail[0], dict):
                first_msg = error_detail[0].get("msg")
                loc = " -> ".join(str(p) for p in error_detail[0].get("loc", []) if p != "body")
                error_msg = f"{first_msg} (in {loc})" if loc else (first_msg or error_msg)
        except Exception:
            error_msg = resp.text or error_msg

        logger.error(f"Project creation API failed: HTTP {resp.status_code} - {error_msg}")
        if raise_for_status:
            raise APIClientError(status_code=resp.status_code, message=error_msg, detail=error_detail)

    except APIClientError:
        raise
    except Exception as e:
        logger.error(f"Project creation network/client failed: {e}")
        if raise_for_status:
            raise APIClientError(status_code=0, message=str(e), detail=None)

    return None


def get_direct_manifest_manager() -> Optional[ProjectManifestManager]:
    """Instantiate a ProjectManifestManager pointing to configured storage."""
    if not DIRECT_ENGINE_AVAILABLE or ProjectManifestManager is None:
        return None
    storage_base_dir = Path(settings.STORAGE_PATH) if settings else Path("storage/projects")
    return ProjectManifestManager(storage_base_dir=storage_base_dir)


def fetch_projects_direct() -> List[Dict[str, Any]]:
    """Discover all projects directly from storage without an API server."""
    mgr = get_direct_manifest_manager()
    if not mgr:
        return []
    projects = []
    for m in mgr.list_projects():
        topic = ""
        target_locales = []
        if m.source_request:
            if isinstance(m.source_request, dict):
                topic = m.source_request.get("topic", "")
                target_locales = m.source_request.get("target_locales", [])
            else:
                topic = getattr(m.source_request, "topic", "")
                target_locales = getattr(m.source_request, "target_locales", [])
        projects.append({
            "project_id": m.project_id,
            "status": m.status,
            "created_at": m.created_at,
            "updated_at": m.updated_at,
            "topic": topic,
            "target_locales": target_locales,
        })
    return projects


def load_manifest_direct(project_id: str) -> Optional[Dict[str, Any]]:
    """Load a project manifest directly from local disk."""
    mgr = get_direct_manifest_manager()
    if not mgr:
        return None
    m = mgr.load_manifest(project_id)
    return m.model_dump() if m else None
