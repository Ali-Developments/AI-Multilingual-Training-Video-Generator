"""Offline regression tests for per-run cancellation, timeout separation, and watchdog isolation."""
import json
import threading
import time
from unittest.mock import MagicMock

import httpx
import pytest

from app.core.config import settings
from app.models.schemas import (
    ContentAnalysis,
    LearningObjective,
    SceneDraft,
    SceneOutlineItem,
    ScriptOutline,
    TrainingVideoRequest,
)
from app.services.llm.openrouter_provider import (
    OpenRouterCancelledError,
    OpenRouterProvider,
    OpenRouterTimeoutError,
)
from app.workflows.manifest import ProjectManifestManager
from app.workflows.orchestrator import ProjectOrchestrator
from app.workflows.script_generation.checkpoint import ScriptCheckpoint
from app.workflows.script_generation.storage import RunControl, ScriptBusyError, ScriptCancelledError


def _chat_ok(content: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "model": "openrouter/free",
            "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": content}}],
        },
    )


def _sample_analysis_dict() -> dict:
    return {
        "topic_summary": "شرح سلق المكرونة",
        "key_concepts": ["سلق المكرونة"],
        "learning_objectives": [{"id": "LO1", "description": "سلق المكرونة بشكل صحيح"}],
        "audience_notes": "المبتدئون",
        "recommended_scene_count": 1,
        "recommended_structure": ["السلق"],
        "important_terms": ["مكرونة"],
        "factual_constraints": ["ماء مغلي"],
    }


def _sample_outline_dict() -> dict:
    return {
        "title": "طريقة سلق المكرونة",
        "language": "ar-SA",
        "audience": "المبتدئون",
        "opening_hook": "هل تريد سلق المكرونة بطريقة مثالية؟",
        "closing_summary": "صفها وقدمها ساخنة.",
        "learning_objectives": [{"id": "LO1", "description": "سلق المكرونة بشكل صحيح"}],
        "scene_outlines": [
            {
                "scene_id": "scene_1",
                "order": 1,
                "title": "سلق المكرونة",
                "purpose": "شرح السلق",
                "scene_type": "intro",
                "learning_objective_ids": ["LO1"],
                "target_duration_seconds": 30,
            }
        ],
    }


def _sample_scene_dict() -> dict:
    return {
        "scene_id": "scene_1",
        "order": 1,
        "title": "سلق المكرونة",
        "purpose": "شرح السلق",
        "scene_type": "intro",
        "narration": (
            "أهلاً بكم في درس اليوم حيث سنتعلم معاً طريقة سلق المكرونة القلم في ماء مغلي ومملح "
            "على نار متوسطة مع التقليب المستمر حتى تنضج تماماً وتصبح جاهزة للتقديم اللذيذ "
            "مع الصلصة المفضلة لديكم في المنزل بخطوات سهلة وسريعة جداً ومضمونة النتيجة دائماً لكل أفراد الأسرة."
        ),
        "visual_direction": "لقطة قريبة لقدر الماء المغلي والمكرونة.",
        "on_screen_text": "سلق المكرونة",
        "learning_objective_ids": ["LO1"],
        "estimated_duration_seconds": 30,
    }


# ---------------------------------------------------------------------------
# 1. Normal successful completion + late timer cannot convert completion to failure
# ---------------------------------------------------------------------------


def test_normal_completion_disarms_watchdog_and_late_timer_is_noop():
    rc = RunControl(run_id="run_a", timeout_seconds=10.0)
    rc.mark_completed()
    # Even if a timer callback fires late after completion, it MUST NOT mark timeout or cancel
    rc.mark_timeout("run_a")
    rc.cancel("run_a")
    assert rc.is_timed_out() is False
    assert rc.is_cancelled() is False


# ---------------------------------------------------------------------------
# 2. Explicit cancellation during an active HTTP request
# ---------------------------------------------------------------------------


def test_explicit_cancellation_during_active_http_request_raises_cancelled_not_timeout():
    rc = RunControl(run_id="run_cancel_mid", timeout_seconds=30.0)
    entered = threading.Event()

    class BlockingStream(httpx.SyncByteStream):
        def __iter__(self):
            entered.set()
            time.sleep(0.5)
            yield b"{}"

    def cancel_soon():
        entered.wait(timeout=2.0)
        rc.cancel("run_cancel_mid")

    with httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(200, stream=BlockingStream(), request=req))) as client:
        provider = OpenRouterProvider(api_key="offline", model="openrouter/free", client=client, timeout_seconds=5.0, max_retries=1)
        t = threading.Thread(target=cancel_soon, daemon=True)
        t.start()
        with provider.script_session(before_request=lambda: "res_1", run_control=rc) as run_provider:
            start = time.monotonic()
            with pytest.raises(OpenRouterCancelledError, match="explicitly cancelled"):
                run_provider.generate_text("hello")
            assert time.monotonic() - start < 0.4


# ---------------------------------------------------------------------------
# 3. Deadline immediately after successful response preserves response; explicit cancel rejects
# ---------------------------------------------------------------------------


def test_timeout_immediately_after_successful_response_does_not_discard_response():
    """If the wall-clock deadline expires milliseconds after HTTP 200 arrives, keep the valid response."""
    rc = RunControl(run_id="run_edge", timeout_seconds=5.0)
    client = MagicMock()

    def respond_then_expire(*args, **kwargs):
        resp = _chat_ok("Valid completed reply")
        rc.mark_timeout("run_edge")
        return resp

    client.post.side_effect = respond_then_expire
    provider = OpenRouterProvider(api_key="offline", model="openrouter/free", client=client, max_retries=1)
    with provider.script_session(before_request=lambda: "res_1", run_control=rc) as run_provider:
        assert run_provider.generate_text("hello") == "Valid completed reply"


def test_explicit_cancel_immediately_after_response_still_cancels():
    rc = RunControl(run_id="run_cancel_after", timeout_seconds=5.0)
    client = MagicMock()

    def respond_then_cancel(*args, **kwargs):
        resp = _chat_ok("Reply")
        rc.cancel("run_cancel_after")
        return resp

    client.post.side_effect = respond_then_cancel
    provider = OpenRouterProvider(api_key="offline", model="openrouter/free", client=client, max_retries=1)
    with provider.script_session(before_request=lambda: "res_1", run_control=rc) as run_provider:
        with pytest.raises(OpenRouterCancelledError):
            run_provider.generate_text("hello")


# ---------------------------------------------------------------------------
# 4. Timeout reported as SCRIPT_TIMEOUT (not cancelled), checkpoint finished cleanly,
#    and resume reuses accepted analysis + outline
# ---------------------------------------------------------------------------


def test_timeout_reports_script_timeout_not_cancelled_and_resumes_cleanly(tmp_path, monkeypatch):
    """
    Reproduces proj_5349ccdf48f0:
    - Run 1 accepts ContentAnalysis & ScriptOutline, then reaches OPENROUTER_SCRIPT_TIMEOUT_SECONDS during scene_1.
    - Error MUST report SCRIPT_TIMEOUT / 'Script time limit reached' (NEVER 'Script run was cancelled').
    - Checkpoint MUST finish cleanly (status='failed', scene_1='failed') while keeping analysis & outline completed.
    - Run 2 resumes and generates ONLY scene_1 without regenerating analysis or outline.
    """
    manager = ProjectManifestManager(tmp_path)
    req = TrainingVideoRequest(
        topic="Pasta",
        source_content="Boil pasta.",
        base_language="ar-SA",
        target_languages=["ar-SA"],
        target_duration_seconds=30,
    )
    manager.create_manifest("p_timeout", req)

    dispatched = []
    run_number = [1]

    def fake_post(url, headers=None, json=None, timeout=None):
        sys_msg = json["messages"][0]["content"]
        if "`ContentAnalysis`" in sys_msg:
            dispatched.append("analysis")
            return _chat_ok(__import__("json").dumps(_sample_analysis_dict(), ensure_ascii=False))
        if "`ScriptOutline`" in sys_msg:
            dispatched.append("outline")
            return _chat_ok(__import__("json").dumps(_sample_outline_dict(), ensure_ascii=False))
        dispatched.append("scene_1")
        if run_number[0] == 1:
            # Sleep past the short run deadline during scene_1
            time.sleep(0.25)
            raise httpx.ReadTimeout("Simulated slow upstream")
        return _chat_ok(__import__("json").dumps(_sample_scene_dict(), ensure_ascii=False))

    client = MagicMock()
    client.post.side_effect = fake_post

    monkeypatch.setattr(settings, "OPENROUTER_SCRIPT_TIMEOUT_SECONDS", 0.15)
    orch = ProjectOrchestrator.__new__(ProjectOrchestrator)
    orch.manifest_manager = manager
    orch.llm_provider = OpenRouterProvider(api_key="offline", model="openrouter/free", client=client, timeout_seconds=0.1, max_retries=2)

    m1 = orch.generate_canonical_script("p_timeout")
    assert m1.script_status == "failed"
    assert m1.error_details[-1].code == "SCRIPT_TIMEOUT"
    assert "time limit" in m1.errors[-1].lower()
    assert "cancelled" not in m1.errors[-1].lower()

    # Checkpoint finished cleanly with analysis & outline preserved and scene_1 marked failed (not stuck running!)
    cp = ScriptCheckpoint(tmp_path / "p_timeout", req, "openrouter/free", required=True)
    assert cp.data["status"] == "failed"
    assert cp.data["progress"]["analysis"] == "completed"
    assert cp.data["progress"]["outline"] == "completed"
    assert cp.data["progress"]["scene_1"] == "failed"

    # Run 2: fresh timeout window -> resumes ONLY scene_1 without regenerating analysis or outline
    run_number[0] = 2
    monkeypatch.setattr(settings, "OPENROUTER_SCRIPT_TIMEOUT_SECONDS", 30.0)
    orch.llm_provider = OpenRouterProvider(api_key="offline", model="openrouter/free", client=client, timeout_seconds=5.0, max_retries=1)
    m2 = orch.generate_canonical_script("p_timeout")
    assert m2.script_status == "completed"
    assert dispatched == ["analysis", "outline", "scene_1", "scene_1"]


# ---------------------------------------------------------------------------
# 5. Previous run's watchdog firing after a new run starts cannot affect new run
# ---------------------------------------------------------------------------


def test_previous_watchdog_firing_after_new_run_starts_cannot_affect_new_run():
    old_rc = RunControl(run_id="run_old", timeout_seconds=0.05)
    new_rc = RunControl(run_id="run_new", timeout_seconds=30.0)

    old_rc.start_deadline_timer()
    time.sleep(0.1)

    # Old run's timer expired, AND even misdirected calls carrying old run_id cannot touch new_rc
    assert old_rc.is_timed_out() is True
    new_rc.mark_timeout("run_old")
    new_rc.cancel("run_old")
    assert new_rc.is_timed_out() is False
    assert new_rc.is_cancelled() is False
    old_rc.stop_timer()


# ---------------------------------------------------------------------------
# 6. Concurrent runs targeting the same project fail with ScriptBusyError
# ---------------------------------------------------------------------------


def test_concurrent_run_raises_script_busy_without_cancelling_active_run(tmp_path, monkeypatch):
    import app.workflows.orchestrator as orch_mod

    manager = ProjectManifestManager(tmp_path)
    manager.create_manifest("p_busy", TrainingVideoRequest(topic="Pasta"))
    entered = threading.Event()
    release = threading.Event()

    class SlowGraph:
        def invoke(self, state):
            entered.set()
            release.wait(timeout=5.0)
            return {"workflow_status": "failed", "errors": ["done"]}

    monkeypatch.setattr(orch_mod, "create_script_workflow", lambda **kwargs: SlowGraph())
    orch = ProjectOrchestrator.__new__(ProjectOrchestrator)
    orch.manifest_manager = manager
    orch.llm_provider = OpenRouterProvider(api_key="offline", model="openrouter/free", client=MagicMock())

    t1 = threading.Thread(target=lambda: orch.generate_canonical_script("p_busy"), daemon=True)
    t1.start()
    assert entered.wait(timeout=3.0)

    with pytest.raises(ScriptBusyError):
        orch.generate_canonical_script("p_busy")

    release.set()
    t1.join(timeout=5.0)


# ---------------------------------------------------------------------------
# 7 & 8. Checkpoint persistence before cancellation + clean fresh retry
# ---------------------------------------------------------------------------


def test_checkpoint_persists_before_cancellation_and_fresh_retry_succeeds(tmp_path):
    req = TrainingVideoRequest(topic="Pasta", base_language="ar-SA", target_languages=["ar-SA"], target_duration_seconds=30)
    rc1 = RunControl(run_id="run_1", timeout_seconds=30.0)
    cp1 = ScriptCheckpoint(tmp_path, req, "openrouter/free", run_id="run_1", cancel_check=rc1.is_cancelled)

    analysis = ContentAnalysis.model_validate(_sample_analysis_dict())
    cp1.put("analysis", analysis)
    cp1.event("outline", "generation", "running")

    # Explicit cancellation blocks further stage writes, while finish(False) still records failed terminal state
    rc1.cancel("run_1")
    with pytest.raises(ScriptCancelledError):
        cp1.put("outline", ScriptOutline.model_validate(_sample_outline_dict()))
    cp1.finish(False, reason="cancelled")

    # Fresh retry with a new RunControl & run_id reuses analysis cleanly and completes outline
    rc2 = RunControl(run_id="run_2", timeout_seconds=30.0)
    cp2 = ScriptCheckpoint(tmp_path, req, "openrouter/free", required=True, run_id="run_2", cancel_check=rc2.is_cancelled)
    assert cp2.data["status"] == "failed"
    assert cp2.data["progress"]["outline"] == "failed"
    assert cp2.get("analysis", ContentAnalysis) == analysis

    cp2.put("outline", ScriptOutline.model_validate(_sample_outline_dict()))
    assert cp2.get("outline", ScriptOutline) is not None
    cp2.finish(True)
    assert cp2.data["status"] == "completed"

