import json
import time
from unittest.mock import MagicMock

import httpx
import pytest

from app.models.schemas import ContentAnalysis, TrainingVideoRequest
from app.services.llm.openrouter_provider import OpenRouterProvider, OpenRouterConnectionError, OpenRouterError
from app.workflows.manifest import ProjectManifestManager
from app.workflows.script_generation.checkpoint import ScriptCheckpoint


def test_checkpoint_identity_and_generation_preserve_previous_files(tmp_path):
    request = TrainingVideoRequest(topic="Pasta")
    checkpoint = ScriptCheckpoint(tmp_path, request, "openrouter/free")
    analysis = ContentAnalysis(topic_summary="Learn to cook pasta", key_concepts=["pasta"],
                               learning_objectives=[], recommended_scene_count=2,
                               audience_notes="Home cooks", recommended_structure=["Introduction", "Steps"])
    checkpoint.put("analysis", analysis)
    original = checkpoint.path.read_bytes()
    assert ScriptCheckpoint(tmp_path, request, "openrouter/free").get("analysis", ContentAnalysis) == analysis
    assert ScriptCheckpoint(tmp_path, request, "other:free").get("analysis", ContentAnalysis) is None
    changed = request.model_copy(update={"base_language": "ar-SA"})
    assert ScriptCheckpoint(tmp_path, changed, "openrouter/free").get("analysis", ContentAnalysis) is None
    fresh = ScriptCheckpoint(tmp_path, request, "openrouter/free", generation="abc123")
    fresh.put("analysis", analysis)
    assert ScriptCheckpoint(tmp_path, request, "openrouter/free", generation="abc123").path == fresh.path
    assert checkpoint.path.read_bytes() == original


def test_expired_lease_projects_interrupted_progress_without_rewriting_data(tmp_path):
    manager = ProjectManifestManager(tmp_path)
    manifest = manager.create_manifest("new_test", TrainingVideoRequest(topic="Pasta"))
    checkpoint = ScriptCheckpoint(tmp_path / "new_test", manifest.source_request, "openrouter/free")
    checkpoint.pending(["scene_1", "scene_2", "scene_3"])
    checkpoint.event("scene_1", "validated", "completed")
    checkpoint.event("scene_2", "json_repair", "running")
    manifest.script_status = "running"
    manifest.metadata.update(script_lease_expires=time.time() - 1,
                             script_checkpoint=str(checkpoint.path.relative_to(tmp_path / "new_test")))
    manager.save_manifest(manifest)
    path = manager.get_manifest_path("new_test")
    before = path.read_bytes()
    loaded = manager.load_manifest("new_test")
    assert loaded.script_status == "failed"
    assert loaded.metadata["script_progress"] == {"scene_1": "completed", "scene_2": "failed", "scene_3": "pending"}
    assert path.read_bytes() == before
    manifest.metadata["script_lease_expires"] = time.time() + 100
    manager.save_manifest(manifest)
    assert manager.load_manifest("new_test").script_status == "running"


def test_total_deadline_blocks_dispatch():
    client = MagicMock()
    provider = OpenRouterProvider(api_key="offline", model="openrouter/free", client=client)
    provider._deadline = time.monotonic() - 1
    with pytest.raises(OpenRouterError, match="time limit"):
        provider.generate_text("Task")
    client.post.assert_not_called()


def test_streaming_keepalive_cannot_reset_request_budget(monkeypatch):
    now = [0.0]
    monkeypatch.setattr("app.services.llm.openrouter_provider.time.monotonic", lambda: now[0])

    class SlowStream(httpx.SyncByteStream):
        def __iter__(self):
            now[0] = 1
            yield b" "
            now[0] = 3
            yield b" "

    with httpx.Client(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, stream=SlowStream())
    )) as client:
        provider = OpenRouterProvider(api_key="offline", model="openrouter/free",
                                      client=client, timeout_seconds=2, max_retries=1)
        with pytest.raises(OpenRouterConnectionError):
            provider._post_chat_completion({"model": "openrouter/free"})
