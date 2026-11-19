"""Offline reliability regression suite verifying all 7 critical blockers and restart invariants."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from unittest.mock import MagicMock

import httpx
import pytest

from app.core.config import settings
from app.models.schemas import (
    ContentAnalysis,
    FinalScript,
    LearningObjective,
    SceneDraft,
    SceneOutlineItem,
    ScriptOutline,
    TrainingVideoRequest,
)
from app.services.llm.groq_provider import GroqProvider
from app.services.llm.openrouter_provider import (
    OpenRouterConnectionError,
    OpenRouterPaidModelBlockedError,
    OpenRouterProvider,
)
from app.workflows.manifest import ProjectManifestManager
from app.workflows.orchestrator import ProjectOrchestrator
from app.workflows.script_generation.checkpoint import ScriptCheckpoint
from app.workflows.script_generation.storage import RequestLedger, ScriptBusyError


def _make_outline(scene_count: int = 2) -> ScriptOutline:
    return ScriptOutline(
        title="Pasta Guide",
        language="en-US",
        audience="Home cooks",
        opening_hook="Let us cook pasta properly.",
        closing_summary="Serve hot.",
        learning_objectives=[LearningObjective(id="LO1", description="Cook pasta")],
        scene_outlines=[
            SceneOutlineItem(
                scene_id=f"scene_{i}",
                order=i,
                title=f"Step {i}",
                purpose=f"Teach step {i}",
                scene_type="intro" if i == 1 else "outro",
                learning_objective_ids=["LO1"],
                target_duration_seconds=10,
            )
            for i in range(1, scene_count + 1)
        ],
    )


def _make_scene(order: int = 1, title: str = "Accepted") -> SceneDraft:
    return SceneDraft(
        scene_id=f"scene_{order}",
        order=order,
        title=title,
        narration="Prepare pasta carefully in salted boiling water until tender.",
        visual_direction="Show the ingredients and boiling pot",
        learning_objective_ids=["LO1"],
        estimated_duration_seconds=10,
    )


def _make_checkpoint(directory: Path) -> ScriptCheckpoint:
    return ScriptCheckpoint(directory, TrainingVideoRequest(topic="Pasta"), "openrouter/free")


def _make_orchestrator(directory: Path, client) -> ProjectOrchestrator:
    instance = ProjectOrchestrator.__new__(ProjectOrchestrator)
    instance.manifest_manager = ProjectManifestManager(directory)
    instance.llm_provider = OpenRouterProvider(
        api_key="offline",
        model="openrouter/free",
        client=client,
        max_retries=1,
    )
    return instance


# ---------------------------------------------------------------------------
# 1. Two independent processes targeting the same project (Blocker 1)
# ---------------------------------------------------------------------------


def test_two_independent_processes_exclusive_lock_blocks_second_even_with_expired_lease(tmp_path):
    """OS-backed per-project exclusive lock rejects a second process even when script_lease_expires is in the past."""
    manager = ProjectManifestManager(tmp_path)
    manifest = manager.create_manifest("p", TrainingVideoRequest(topic="Pasta"))
    manifest.script_status = "running"
    manifest.metadata["script_lease_expires"] = time.time() - 10
    manager.save_manifest(manifest)

    worker_1_code = """
import sys, time
from pathlib import Path
from unittest.mock import MagicMock
from app.core.config import settings
from app.services.llm.openrouter_provider import OpenRouterProvider
from app.workflows.manifest import ProjectManifestManager
import app.workflows.orchestrator as module

root = Path(sys.argv[1])
settings.OPENROUTER_SCRIPT_PROJECT_REQUEST_LIMIT = 1
instance = module.ProjectOrchestrator.__new__(module.ProjectOrchestrator)
instance.manifest_manager = ProjectManifestManager(root)
instance.llm_provider = OpenRouterProvider(api_key="offline", model="openrouter/free", client=MagicMock())

class Graph:
    def __init__(self, provider): self.provider = provider
    def invoke(self, state):
        (root / "p1.entered").touch()
        deadline = time.monotonic() + 10
        while not (root / "p1.go").exists():
            if time.monotonic() > deadline:
                raise RuntimeError("barrier timeout")
            time.sleep(0.02)
        self.provider._before_request()
        return {"workflow_status": "failed", "errors": ["offline probe"]}

module.create_script_workflow = lambda llm_provider, checkpoint: Graph(llm_provider)
instance.generate_canonical_script("p")
"""

    worker_2_code = """
import sys
from pathlib import Path
from unittest.mock import MagicMock
from app.services.llm.openrouter_provider import OpenRouterProvider
from app.workflows.manifest import ProjectManifestManager
from app.workflows.orchestrator import ProjectOrchestrator
from app.workflows.script_generation.storage import ScriptBusyError

root = Path(sys.argv[1])
instance = ProjectOrchestrator.__new__(ProjectOrchestrator)
instance.manifest_manager = ProjectManifestManager(root)
instance.llm_provider = OpenRouterProvider(api_key="offline", model="openrouter/free", client=MagicMock())
try:
    instance.generate_canonical_script("p")
except ScriptBusyError:
    sys.exit(42)
sys.exit(1)
"""
    p1 = subprocess.Popen(
        [sys.executable, "-c", worker_1_code, str(tmp_path)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    try:
        deadline = time.monotonic() + 10
        while not (tmp_path / "p1.entered").exists():
            if p1.poll() is not None:
                _, err = p1.communicate()
                pytest.fail(err.decode(errors="replace") or "Worker 1 exited early")
            assert time.monotonic() < deadline
            time.sleep(0.02)

        # While Worker 1 holds the OS lock, Worker 2 MUST be refused with ScriptBusyError (exit 42)
        p2 = subprocess.run([sys.executable, "-c", worker_2_code, str(tmp_path)], capture_output=True, timeout=15)
        assert p2.returncode == 42, p2.stderr.decode(errors="replace")

        # Lease expiry projection must NOT mark the project failed while Worker 1 holds the OS lock
        assert manager.load_manifest("p").script_status == "running"

        (tmp_path / "p1.go").touch()
        _, err1 = p1.communicate(timeout=15)
        assert p1.returncode == 0, err1.decode(errors="replace")
        assert manager.load_manifest("p").metadata["script_openrouter_requests"] == 1
    finally:
        if p1.poll() is None:
            p1.kill()
            p1.wait()


# ---------------------------------------------------------------------------
# 2. Concurrent request-budget reservations (Blocker 2)
# ---------------------------------------------------------------------------


def test_concurrent_request_budget_reservations_respect_ceiling_and_record_outcomes(tmp_path):
    """Concurrent reservations serialize via OS lock, enforce ceiling, and distinguish reserved vs completed."""
    ledger = RequestLedger(tmp_path, ceiling=3)

    def _try_reserve(_):
        try:
            return ledger.reserve()
        except ValueError:
            return None

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(_try_reserve, range(8)))

    granted = [r for r in results if r is not None]
    assert len(granted) == 3
    assert len(set(granted)) == 3
    assert ledger.count == 3
    assert ledger.reserved_pending_count == 3
    assert ledger.completed_count == 0

    ledger.record_outcome(granted[0], "completed", http_status=200, routed_model="free/model:free")
    ledger.record_outcome(granted[1], "failed", http_status=502)
    assert ledger.count == 3
    assert ledger.completed_count == 1
    assert ledger.reserved_pending_count == 1

    # Corrupt ledger is rejected rather than silently reset to zero
    ledger.path.write_text('{"checksum":"bad","data":{"ceiling":3,"legacy_count":0,"reservations":[]}}', encoding="utf-8")
    with pytest.raises(ValueError, match="corrupt"):
        RequestLedger(tmp_path, ceiling=3)


# ---------------------------------------------------------------------------
# 3. Stale manifest writes (Blocker 2)
# ---------------------------------------------------------------------------


def test_stale_manifest_write_cannot_reset_durable_request_budget(tmp_path):
    """Saving a stale manifest snapshot must never revert script_openrouter_requests from 12 back to 0."""
    manager = ProjectManifestManager(tmp_path)
    manager.create_manifest("p", TrainingVideoRequest(topic="Pasta"))
    stale = manager.load_manifest("p")
    current = manager.load_manifest("p")

    ledger = RequestLedger(tmp_path / "p", ceiling=48, legacy_count=12)
    current.metadata["script_openrouter_requests"] = ledger.count
    current.metadata["script_request_ledger"] = "script_requests.json"
    manager.save_manifest(current)

    # Now save the stale snapshot loaded before the 12 requests
    manager.save_manifest(stale)
    reloaded = manager.load_manifest("p")
    assert reloaded.metadata["script_openrouter_requests"] == 12


# ---------------------------------------------------------------------------
# 4. Crash before and after checkpoint persistence (Atomicity)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("after", [False, True])
def test_real_process_exit_before_and_after_checkpoint_replace(tmp_path, after):
    cp = _make_checkpoint(tmp_path)
    cp.put("outline", _make_outline(1))
    cp.put("scene_1", _make_scene(1, "Old"))

    program = """
import os, sys
from pathlib import Path
from app.models.schemas import TrainingVideoRequest, SceneDraft
from app.workflows.script_generation.checkpoint import ScriptCheckpoint
cp = ScriptCheckpoint(Path(sys.argv[1]), TrainingVideoRequest(topic="Pasta"), "openrouter/free")
replace = os.replace
def crash(src, dst):
    if sys.argv[2] == "True":
        replace(src, dst)
    os._exit(77)
os.replace = crash
value = cp.get("scene_1", SceneDraft)
value.title = "New"
cp.put("scene_1", value)
"""
    result = subprocess.run([sys.executable, "-c", program, str(tmp_path), str(after)], capture_output=True, timeout=15)
    assert result.returncode == 77, result.stderr.decode(errors="replace")
    loaded = _make_checkpoint(tmp_path)
    assert loaded.get("scene_1", SceneDraft).title == ("New" if after else "Old")
    assert loaded.data["events"][-1]["status"] == "completed"


# ---------------------------------------------------------------------------
# 5. Corrupt checkpoint metadata (Blocker 3)
# ---------------------------------------------------------------------------


def test_corrupt_checkpoint_preserves_file_and_accounting_metadata(tmp_path):
    """Corrupt checkpoint JSON/shape/inconsistent scene is rejected, preserved on disk, and never erases accounting."""
    manager = ProjectManifestManager(tmp_path)
    manifest = manager.create_manifest("p", TrainingVideoRequest(topic="Pasta"))
    RequestLedger(tmp_path / "p", ceiling=48, legacy_count=12)
    manifest.metadata["script_openrouter_requests"] = 12
    manifest.metadata["script_checkpoint"] = "malformed.json"
    bad_file = tmp_path / "p" / "malformed.json"
    bad_file.write_text("[]", encoding="utf-8")
    manager.save_manifest(manifest)

    reloaded = manager.load_manifest("p")
    assert reloaded.metadata["script_openrouter_requests"] == 12
    assert "script_checkpoint_error" in reloaded.metadata
    assert bad_file.read_text(encoding="utf-8") == "[]"

    # Corrupt JSON syntax in ScriptCheckpoint
    cp = _make_checkpoint(tmp_path)
    cp.put("outline", _make_outline(1))
    cp.put("scene_1", _make_scene(1))
    cp.path.write_text("{broken", encoding="utf-8")
    with pytest.raises(ValueError, match="corrupt"):
        _make_checkpoint(tmp_path)
    assert cp.path.read_text(encoding="utf-8") == "{broken"

    # Schema-valid JSON with mismatched scene_id/order or progress disagreement is rejected
    cp.save()
    envelope = json.loads(cp.path.read_text(encoding="utf-8"))
    envelope["data"]["accepted"]["scene_1"]["scene_id"] = "scene_99"
    envelope["data"]["progress"]["scene_1"] = "failed"
    from app.workflows.script_generation.storage import save_record
    save_record(cp.path, envelope["data"])
    with pytest.raises(ValueError, match="scene identity"):
        _make_checkpoint(tmp_path)


# ---------------------------------------------------------------------------
# 6. Missing referenced checkpoints (Blocker 3 + Additional Issue)
# ---------------------------------------------------------------------------


def test_missing_referenced_checkpoint_blocks_silent_regeneration(tmp_path):
    """When a previously referenced checkpoint for the active identity is missing, generation fails explicitly."""
    manager = ProjectManifestManager(tmp_path)
    manifest = manager.create_manifest("p", TrainingVideoRequest(topic="Pasta"))
    cp = ScriptCheckpoint(tmp_path / "p", manifest.source_request, "openrouter/free")
    cp.put("outline", _make_outline(1))
    manifest.metadata["script_checkpoint"] = str(cp.path.relative_to(tmp_path / "p"))
    manager.save_manifest(manifest)

    # Simulate external deletion of the referenced checkpoint file
    cp.path.unlink()
    client = MagicMock()
    res = _make_orchestrator(tmp_path, client).generate_canonical_script("p")
    assert res.script_status == "failed"
    assert "missing" in " ".join(res.errors).lower()
    assert client.post.call_count == 0


# ---------------------------------------------------------------------------
# 7. Changes to prompts, settings, and timing assumptions (Blocker 4)
# ---------------------------------------------------------------------------


def test_prompt_settings_and_timing_changes_invalidate_checkpoint_identity(tmp_path, monkeypatch):
    """Changing prompts, reasoning settings, token budget, or WPM timing invalidates cached checkpoints."""
    from app.workflows.script_generation import prompts
    from app.workflows.script_generation.validators import LocaleDurationEstimator

    cp = _make_checkpoint(tmp_path)
    cp.put("outline", _make_outline(1))
    cp.put("scene_1", _make_scene(1))
    base_hash = cp.identity_hash

    monkeypatch.setattr(settings, "OPENROUTER_REASONING_MIN_OUTPUT_TOKENS", 12000)
    assert _make_checkpoint(tmp_path).identity_hash != base_hash
    monkeypatch.undo()

    monkeypatch.setattr(settings, "OPENROUTER_REASONING_EFFORT", "low")
    assert _make_checkpoint(tmp_path).identity_hash != base_hash
    monkeypatch.undo()

    monkeypatch.setattr(prompts, "SYSTEM_PROMPT_SCRIPT_WRITER", "Changed prompt text")
    changed_cp = _make_checkpoint(tmp_path)
    assert changed_cp.identity_hash != base_hash
    assert changed_cp.get("scene_1", SceneDraft) is None
    monkeypatch.undo()

    monkeypatch.setattr(LocaleDurationEstimator, "DEFAULT_WPM", 160)
    assert _make_checkpoint(tmp_path).identity_hash != base_hash


# ---------------------------------------------------------------------------
# 8. Completed-script cache invalidation (Blocker 5)
# ---------------------------------------------------------------------------


def test_completed_script_fast_path_invalidates_on_model_or_prompt_change(tmp_path, monkeypatch):
    """Completed script is reused ONLY when generation identity matches; changing prompt invalidates cache."""
    from app.workflows.script_generation import prompts
    import app.workflows.orchestrator as orch_mod

    manager = ProjectManifestManager(tmp_path)
    manifest = manager.create_manifest("p", TrainingVideoRequest(topic="Pasta"))
    req = manifest.source_request

    calls = [0]

    class FakeGraph:
        def invoke(self, state):
            calls[0] += 1
            return {
                "workflow_status": "completed",
                "final_script": FinalScript(
                    title=f"Generated v{calls[0]}",
                    language="en-US",
                    audience="Home cooks",
                    target_duration_seconds=60,
                    total_estimated_duration_seconds=10,
                    opening_hook="Hook",
                    closing_summary="Summary",
                    learning_objectives=[LearningObjective(id="LO1", description="Cook")],
                    scenes=[_make_scene(1, f"Title v{calls[0]}")],
                ),
            }

    monkeypatch.setattr(orch_mod, "create_script_workflow", lambda **kwargs: FakeGraph())
    orch = _make_orchestrator(tmp_path, MagicMock())

    first = orch.generate_canonical_script("p")
    assert first.script_status == "completed"
    assert first.final_script.title == "Generated v1"
    assert calls[0] == 1

    # Same identity -> fast-path reuse (no new graph call)
    second = orch.generate_canonical_script("p")
    assert second.final_script.title == "Generated v1"
    assert calls[0] == 1

    # Prompt change -> identity mismatch -> must NOT return stale script!
    monkeypatch.setattr(prompts, "SYSTEM_PROMPT_SCRIPT_WRITER", "Updated prompt version")
    third = orch.generate_canonical_script("p")
    assert third.final_script.title == "Generated v2"
    assert calls[0] == 2


# ---------------------------------------------------------------------------
# 9. Paid-model rejection before transport (Blocker 6)
# ---------------------------------------------------------------------------


def test_paid_model_and_unverified_suffix_and_groq_rejected_before_transport(tmp_path):
    """Fail-closed authorization blocks paid models, unverified ':free' suffixes, unknown endpoints, and Groq."""
    client = MagicMock()
    before_calls = [0]

    # 1. Paid primary model refused before transport and before reservation
    paid = OpenRouterProvider(api_key="offline", model="openai/gpt-4o", client=client)
    paid._before_request = lambda: before_calls.__setitem__(0, before_calls[0] + 1)
    with pytest.raises(OpenRouterPaidModelBlockedError):
        paid.generate_text("offline")
    assert client.post.call_count == 0
    assert before_calls[0] == 0

    # 2. Unverified ':free' suffix refused fail-closed
    unverified_free = OpenRouterProvider(api_key="offline", model="spoofed/model:free", client=client)
    with pytest.raises(OpenRouterPaidModelBlockedError):
        unverified_free.generate_text("offline")
    assert client.post.call_count == 0

    # 3. Unverified custom endpoint refused fail-closed
    bad_endpoint = OpenRouterProvider(
        api_key="offline",
        model="openrouter/free",
        base_url="https://evil.example.com/v1",
        client=client,
    )
    with pytest.raises(OpenRouterPaidModelBlockedError):
        bad_endpoint.generate_text("offline")
    assert client.post.call_count == 0

    # 4. Groq provider refused by orchestrator under default free-only policy
    manager = ProjectManifestManager(tmp_path)
    manager.create_manifest("p", TrainingVideoRequest(topic="Pasta"))
    orch = ProjectOrchestrator.__new__(ProjectOrchestrator)
    orch.manifest_manager = manager
    orch.llm_provider = GroqProvider(api_key="offline", model="openai/gpt-oss-20b", client=MagicMock())
    res = orch.generate_canonical_script("p")
    assert res.script_status == "failed"
    assert "free-only policy" in " ".join(res.errors).lower()


# ---------------------------------------------------------------------------
# 10. Blocked HTTP operations and wall-clock deadline enforcement (Blocker 7)
# ---------------------------------------------------------------------------


def test_blocked_http_transport_enforces_wall_clock_deadline():
    """Blocked HTTP stream is cut off at the wall-clock deadline rather than waiting for the blocked transport."""
    class Blocked(httpx.SyncByteStream):
        def __iter__(self):
            time.sleep(0.35)
            yield b" "

    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=Blocked()))) as client:
        provider = OpenRouterProvider(
            api_key="offline",
            model="openrouter/free",
            client=client,
            timeout_seconds=0.04,
            max_retries=1,
        )
        start = time.monotonic()
        with pytest.raises(OpenRouterConnectionError, match="timed out|deadline"):
            provider._post_chat_completion({"model": "openrouter/free"})
        elapsed = time.monotonic() - start
        assert elapsed < 0.25


# ---------------------------------------------------------------------------
# 11, 12, 14. Fresh Python process restart/resume + 6-scene Arabic ScriptDraft
#             + prevention of duplicate accepted-scene generation
# ---------------------------------------------------------------------------


def test_fresh_python_process_restart_and_resume_reuses_accepted_scenes_six_scene_arabic(tmp_path):
    """
    Process 1 accepts ContentAnalysis, ScriptOutline, scene_1, and scene_2, then exits hard on scene_3.
    Process 2 (fresh Python interpreter) resumes, reuses analysis/outline/scene_1/scene_2 with ZERO
    duplicate generations, generates scene_3..scene_6, and validates the complete 6-scene Arabic ScriptDraft.
    """
    manager = ProjectManifestManager(tmp_path)
    req = TrainingVideoRequest(
        topic="How to Make Egyptian Macaroni Béchamel",
        source_content="Prepare Egyptian macaroni béchamel in 6 steps.",
        base_language="ar-SA",
        target_languages=["ar-SA"],
        target_duration_seconds=60,
    )
    manager.create_manifest("bechamel", req)

    runner_code = """
import json, os, sys
from pathlib import Path
from unittest.mock import MagicMock
import httpx
from app.services.llm.openrouter_provider import OpenRouterProvider
from app.workflows.manifest import ProjectManifestManager
from app.workflows.orchestrator import ProjectOrchestrator

root = Path(sys.argv[1])
mode = sys.argv[2]  # "crash_on_scene_3" or "resume_complete"
log_file = root / "dispatched_stages.log"

analysis = {
    "topic_summary": "شرح تحضير المكرونة بالبشاميل المصرية في ستين ثانية خطوة بخطوة",
    "key_concepts": ["سلق المكرونة", "تعصيج اللحم", "صلصة البشاميل", "الخبز"],
    "learning_objectives": [
        {"id": "LO1", "description": "تجهيز المكونات وسلق المكرونة واللحم"},
        {"id": "LO2", "description": "تحضير البشاميل وترتيب الطبقات وخبزها"},
    ],
    "audience_notes": "المبتدئون",
    "recommended_scene_count": 6,
    "recommended_structure": ["المقدمة", "المكونات", "المكرونة واللحم", "البشاميل", "الطبقات", "الخبز"],
    "important_terms": ["بشاميل"],
    "factual_constraints": ["180 درجة"],
}
outline = {
    "title": "طريقة عمل المكرونة بالبشاميل المصرية",
    "language": "ar-SA",
    "audience": "المبتدئون",
    "opening_hook": "هل تريد تحضير ألذ مكرونة بالبشاميل مصرية في مطبخك؟",
    "closing_summary": "قدمها ساخنة بالهناء والشفاء.",
    "learning_objectives": analysis["learning_objectives"],
    "scene_outlines": [
        {"scene_id": f"scene_{i}", "order": i, "title": f"الخطوة {i}", "purpose": f"شرح الخطوة {i}",
         "scene_type": "intro" if i == 1 else ("outro" if i == 6 else "visual_demo"),
         "learning_objective_ids": ["LO1"] if i <= 3 else ["LO2"], "target_duration_seconds": 10}
        for i in range(1, 7)
    ],
}
narrations = [
    "أهلاً بكم في مطبخنا اليوم لنتعلم معاً طريقة تحضير صينية المكرونة بالبشاميل المصرية الشهية بخطوات بسيطة وسريعة جداً ومضمونة.",
    "نحتاج في هذه الوصفة إلى مكرونة قلم ولحم بقري مفروم وبصل مفروم وحليب طازج ودقيق وزبدة وملح وفلفل أسود.",
    "نسلق المكرونة في ماء مملح حتى تقترب من النضج ثم نشوح البصل ونضيف اللحم المفروم والتوابل حتى ينضج تماماً.",
    "في قدر على النار نذيب الزبدة ونقلب الدقيق جيداً ثم نضيف الحليب تدريجياً مع الخفق المستمر ليتكون قوام كريمي.",
    "نضع طبقة من المكرونة المخلوطة بالبشاميل في صينية الفرن ثم نوزع اللحم المعصج ونغطيه بطبقة ثانية من المكرونة والبشاميل.",
    "ندخل الصينية في فرن ساخن على مئة وثمانين درجة مئوية حتى يحمر الوجه الذهبي ثم نقطعها ونقدمها بالهناء والشفاء.",
]

def fake_post(url, headers=None, json=None, timeout=None):
    import json as _json
    sys_msg = json["messages"][0]["content"]
    user_msg = json["messages"][-1]["content"]
    if "`ContentAnalysis`" in sys_msg:
        stage = "analysis"
        body = _json.dumps(analysis, ensure_ascii=False)
    elif "`ScriptOutline`" in sys_msg:
        stage = "outline"
        body = _json.dumps(outline, ensure_ascii=False)
    else:
        for i in range(1, 7):
            if f"'scene_{i}'" in user_msg:
                stage = f"scene_{i}"
                if mode == "crash_on_scene_3" and i == 3:
                    os._exit(77)
                sc = {
                    "scene_id": f"scene_{i}",
                    "order": i,
                    "title": f"الخطوة {i}",
                    "purpose": f"شرح الخطوة {i}",
                    "scene_type": "intro" if i == 1 else ("outro" if i == 6 else "visual_demo"),
                    "narration": narrations[i - 1],
                    "visual_direction": f"لقطة واضحة توضح الخطوة {i} في المطبخ.",
                    "on_screen_text": f"الخطوة {i}",
                    "learning_objective_ids": ["LO1"] if i <= 3 else ["LO2"],
                    "estimated_duration_seconds": 10,
                }
                body = _json.dumps(sc, ensure_ascii=False)
                break
        else:
            raise AssertionError("Unexpected prompt: " + user_msg[:120])
    with log_file.open("a", encoding="utf-8") as fh:
        fh.write(stage + "\\n")
    return httpx.Response(200, json={"model": "openrouter/free", "choices": [{"finish_reason": "stop", "message": {"content": body}}]})

client = MagicMock()
client.post.side_effect = fake_post
orch = ProjectOrchestrator.__new__(ProjectOrchestrator)
orch.manifest_manager = ProjectManifestManager(root)
orch.llm_provider = OpenRouterProvider(api_key="offline", model="openrouter/free", client=client, max_retries=1)
manifest = orch.generate_canonical_script("bechamel")
assert manifest.script_status == "completed", manifest.errors
assert len(manifest.final_script.scenes) == 6
assert manifest.final_script.language == "ar-SA"
"""

    # Process 1: accepts analysis, outline, scene_1, scene_2 and crashes hard on scene_3
    p1 = subprocess.run([sys.executable, "-c", runner_code, str(tmp_path), "crash_on_scene_3"], capture_output=True, timeout=30)
    assert p1.returncode == 77, p1.stderr.decode(errors="replace")
    dispatched_1 = (tmp_path / "dispatched_stages.log").read_text(encoding="utf-8").splitlines()
    assert dispatched_1 == ["analysis", "outline", "scene_1", "scene_2"]

    # Process 2: fresh Python interpreter resumes and generates ONLY scene_3..scene_6
    p2 = subprocess.run([sys.executable, "-c", runner_code, str(tmp_path), "resume_complete"], capture_output=True, timeout=30)
    assert p2.returncode == 0, p2.stderr.decode(errors="replace")
    dispatched_all = (tmp_path / "dispatched_stages.log").read_text(encoding="utf-8").splitlines()
    assert dispatched_all == ["analysis", "outline", "scene_1", "scene_2", "scene_3", "scene_4", "scene_5", "scene_6"]

    final_manifest = manager.load_manifest("bechamel")
    assert final_manifest.script_status == "completed"
    assert len(final_manifest.final_script.scenes) == 6
    assert final_manifest.final_script.language == "ar-SA"
    assert final_manifest.final_script.total_estimated_duration_seconds == 60
    assert (tmp_path / "bechamel" / "scripts" / "source.json").exists()


# ---------------------------------------------------------------------------
# 13. Repair/revision persistence & predecessor lineage after interruption
# ---------------------------------------------------------------------------


def test_repair_and_revision_state_persists_across_interruption(tmp_path):
    """
    Pending targeted repairs and revision_count survive restart; a scene under repair is NOT returned
    as stale accepted output; replacing scene_1 invalidates dependent scene_2.
    """
    outline = _make_outline(2)
    cp = _make_checkpoint(tmp_path)
    cp.put("outline", outline)
    cp.put("scene_1", _make_scene(1, "Scene 1 v1"))
    cp.put("scene_2", _make_scene(2, "Scene 2 v1"))

    # Persist repair task and revision_count BEFORE simulated crash
    cp.set_revision_count(1)
    cp.begin_repair("scene_2", outline.scene_outlines[1], "Expand narration to 15s.")

    # Reload in a fresh checkpoint instance (simulating restart)
    reloaded = _make_checkpoint(tmp_path)
    assert reloaded.data["revision_count"] == 1
    assert "scene_2" in reloaded.pending_repair_tasks()
    # Stale scene_2 must NOT be returned while repair is pending
    assert reloaded.get("scene_2", SceneDraft) is None
    # Unrelated scene_1 remains reusable
    assert reloaded.get("scene_1", SceneDraft).title == "Scene 1 v1"

    # Replacing predecessor scene_1 invalidates downstream scene_2
    reloaded.put("scene_1", _make_scene(1, "Scene 1 v2"))
    assert reloaded.get("scene_1", SceneDraft).title == "Scene 1 v2"
    assert reloaded.get("scene_2", SceneDraft) is None
    assert any(h.get("reason") == "predecessor_changed" and h.get("key") == "scene_2" for h in reloaded.data["history"])


# ---------------------------------------------------------------------------
# Extra: Crash after budget reservation before dispatch preserves reservation
# ---------------------------------------------------------------------------


def test_crash_after_budget_reservation_before_dispatch_preserves_accounting(tmp_path):
    manager = ProjectManifestManager(tmp_path)
    manager.create_manifest("p", TrainingVideoRequest(topic="Pasta"))
    program = """
import os, sys
from pathlib import Path
from unittest.mock import MagicMock
from app.workflows.manifest import ProjectManifestManager
from app.workflows.orchestrator import ProjectOrchestrator
from app.services.llm.openrouter_provider import OpenRouterProvider
from app.workflows.script_generation.storage import RequestLedger

root = Path(sys.argv[1])
orig_reserve = RequestLedger.reserve
def crash_after_reserve(self):
    res = orig_reserve(self)
    os._exit(77)
RequestLedger.reserve = crash_after_reserve
client = MagicMock()
client.post.side_effect = lambda *a, **k: (root / "unexpected_dispatch").touch()
instance = ProjectOrchestrator.__new__(ProjectOrchestrator)
instance.manifest_manager = ProjectManifestManager(root)
instance.llm_provider = OpenRouterProvider(api_key="offline", model="openrouter/free", client=client)
instance.generate_canonical_script("p")
"""
    result = subprocess.run([sys.executable, "-c", program, str(tmp_path)], capture_output=True, timeout=15)
    assert result.returncode == 77, result.stderr.decode(errors="replace")
    assert not (tmp_path / "unexpected_dispatch").exists()
    ledger = RequestLedger(tmp_path / "p", ceiling=48, required=True)
    assert ledger.count == 1
    assert ledger.reserved_pending_count == 1
    assert ledger.completed_count == 0
    assert manager.load_manifest("p").metadata["script_openrouter_requests"] == 1
