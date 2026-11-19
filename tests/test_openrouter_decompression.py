"""Offline HTTP decompression & streaming transport regression tests for OpenRouterProvider."""
import gzip
import json
import time
import zlib

import httpx
import pytest

from app.models.schemas import ContentAnalysis, LearningObjective, SceneOutlineItem, ScriptOutline, TrainingVideoRequest
from app.services.llm.openrouter_provider import (
    OpenRouterAuthenticationError,
    OpenRouterConnectionError,
    OpenRouterDecodingError,
    OpenRouterModelCompatibilityError,
    OpenRouterProvider,
    OpenRouterRateLimitError,
    OpenRouterServerError,
)
from app.workflows.manifest import ProjectManifestManager
from app.workflows.orchestrator import ProjectOrchestrator
from app.workflows.script_generation.checkpoint import ScriptCheckpoint
from app.workflows.script_generation.storage import RequestLedger


def _chat_json_bytes(content: str, model: str = "openrouter/free") -> bytes:
    payload = {
        "id": "gen-decomp-test",
        "model": model,
        "choices": [
            {
                "index": 0,
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": content},
            }
        ],
    }
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


# ---------------------------------------------------------------------------
# 1. Valid gzip responses
# ---------------------------------------------------------------------------


def test_valid_gzip_response_decodes_without_double_decompression():
    """HTTPX's built-in GZipDecoder decodes once; synthetic Response must not re-decompress."""
    raw_json = _chat_json_bytes("مرحباً بكم في درس المكرونة بالبشاميل")
    gz_body = gzip.compress(raw_json)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Content-Encoding": "gzip",
                "Content-Length": str(len(gz_body)),
            },
            stream=httpx.ByteStream(gz_body),
            request=request,
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        provider = OpenRouterProvider(api_key="offline", model="openrouter/free", client=client, max_retries=1)
        result = provider.generate_text("Test gzip")
        assert result == "مرحباً بكم في درس المكرونة بالبشاميل"


# ---------------------------------------------------------------------------
# 2. Valid deflate responses
# ---------------------------------------------------------------------------


def test_valid_deflate_response_decodes_without_double_decompression():
    """HTTPX's built-in DeflateDecoder decodes once without triggering double decompression."""
    raw_json = _chat_json_bytes("Deflate response OK")
    deflate_body = zlib.compress(raw_json)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={
                "Content-Type": "application/json",
                "Content-Encoding": "deflate",
                "Content-Length": str(len(deflate_body)),
            },
            stream=httpx.ByteStream(deflate_body),
            request=request,
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        provider = OpenRouterProvider(api_key="offline", model="openrouter/free", client=client, max_retries=1)
        assert provider.generate_text("Test deflate") == "Deflate response OK"


# ---------------------------------------------------------------------------
# 3. Uncompressed JSON responses
# ---------------------------------------------------------------------------


def test_uncompressed_json_response_succeeds():
    raw_json = _chat_json_bytes("Uncompressed JSON OK")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Type": "application/json", "Content-Length": str(len(raw_json))},
            stream=httpx.ByteStream(raw_json),
            request=request,
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        provider = OpenRouterProvider(api_key="offline", model="openrouter/free", client=client, max_retries=1)
        assert provider.generate_text("Test plain") == "Uncompressed JSON OK"


# ---------------------------------------------------------------------------
# 4. Invalid compression headers (corrupt gzip header)
# ---------------------------------------------------------------------------


def test_invalid_compression_header_raises_openrouter_decoding_error():
    """Corrupt gzip payload raises OpenRouterDecodingError (distinct from connection/auth/rate-limit/model errors)."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Type": "application/json", "Content-Encoding": "gzip"},
            stream=httpx.ByteStream(b'{"not": "gzipped"}'),
            request=request,
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        provider = OpenRouterProvider(api_key="offline", model="openrouter/free", client=client, max_retries=1)
        with pytest.raises(OpenRouterDecodingError) as exc_info:
            provider.generate_text("Test invalid gzip")

    err = exc_info.value
    assert err.error_code == "decoding_error"
    assert "Content-Encoding=gzip" in str(err)
    assert not isinstance(err, (OpenRouterConnectionError, OpenRouterAuthenticationError, OpenRouterRateLimitError, OpenRouterModelCompatibilityError))


# ---------------------------------------------------------------------------
# 5. Truncated compressed responses
# ---------------------------------------------------------------------------


def test_truncated_gzip_response_fails_cleanly(monkeypatch):
    """Truncated gzip stream yields malformed JSON / decoding error and fails cleanly."""
    monkeypatch.setattr("app.services.llm.openrouter_provider.time.sleep", lambda _: None)
    raw_json = _chat_json_bytes("A" * 500)
    truncated_gz = gzip.compress(raw_json)[:18]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Type": "application/json", "Content-Encoding": "gzip"},
            stream=httpx.ByteStream(truncated_gz),
            request=request,
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        provider = OpenRouterProvider(api_key="offline", model="openrouter/free", client=client, max_retries=1)
        with pytest.raises((OpenRouterDecodingError, OpenRouterServerError, RuntimeError)):
            provider.generate_text("Test truncated gzip")


# ---------------------------------------------------------------------------
# 6. Explicit decompression exceptions
# ---------------------------------------------------------------------------


def test_explicit_httpx_decoding_error_classified_as_decoding_error():
    class FailingCompressedStream(httpx.SyncByteStream):
        def __iter__(self):
            raise httpx.DecodingError("Simulated zlib stream failure")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Encoding": "gzip"},
            stream=FailingCompressedStream(),
            request=request,
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        provider = OpenRouterProvider(api_key="offline", model="openrouter/free", client=client, max_retries=1)
        with pytest.raises(OpenRouterDecodingError, match="Simulated zlib stream failure"):
            provider.generate_text("Test decoding exception")


# ---------------------------------------------------------------------------
# 7. Bounded retry behavior after a decoding failure
# ---------------------------------------------------------------------------


def test_bounded_retry_recovers_after_single_decoding_failure_and_stops_at_two(monkeypatch):
    monkeypatch.setattr("app.services.llm.openrouter_provider.time.sleep", lambda _: None)
    calls = [0]
    good_gz = gzip.compress(_chat_json_bytes("Recovered after corrupt gzip"))

    def recover_handler(request: httpx.Request) -> httpx.Response:
        calls[0] += 1
        if calls[0] == 1:
            return httpx.Response(200, headers={"Content-Encoding": "gzip"}, stream=httpx.ByteStream(b"bad"), request=request)
        return httpx.Response(200, headers={"Content-Encoding": "gzip"}, stream=httpx.ByteStream(good_gz), request=request)

    with httpx.Client(transport=httpx.MockTransport(recover_handler)) as client:
        provider = OpenRouterProvider(api_key="offline", model="openrouter/free", client=client, max_retries=4)
        assert provider.generate_text("Retry test") == "Recovered after corrupt gzip"
        assert calls[0] == 2

    # Persistent decoding failure MUST stop after strictly 2 attempts even when max_retries=4
    fail_calls = [0]

    def persistent_bad_handler(request: httpx.Request) -> httpx.Response:
        fail_calls[0] += 1
        return httpx.Response(200, headers={"Content-Encoding": "gzip"}, stream=httpx.ByteStream(b"bad"), request=request)

    with httpx.Client(transport=httpx.MockTransport(persistent_bad_handler)) as client:
        provider = OpenRouterProvider(api_key="offline", model="openrouter/free", client=client, max_retries=4)
        with pytest.raises(OpenRouterDecodingError):
            provider.generate_text("Persistent bad gzip")
        assert fail_calls[0] == 2


# ---------------------------------------------------------------------------
# 8. Stream closure & connection reuse after a failed response
# ---------------------------------------------------------------------------


def test_stream_closed_and_client_reusable_after_failed_decompression():
    closed = [False]
    calls = [0]
    good_gz = gzip.compress(_chat_json_bytes("Clean reuse after error"))

    class TrackedBadStream(httpx.SyncByteStream):
        def __iter__(self):
            yield b"not-valid-gzip"

        def close(self):
            closed[0] = True

    def handler(request: httpx.Request) -> httpx.Response:
        calls[0] += 1
        if calls[0] == 1:
            return httpx.Response(200, headers={"Content-Encoding": "gzip"}, stream=TrackedBadStream(), request=request)
        return httpx.Response(200, headers={"Content-Encoding": "gzip"}, stream=httpx.ByteStream(good_gz), request=request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        provider = OpenRouterProvider(api_key="offline", model="openrouter/free", client=client, max_retries=1)
        with pytest.raises(OpenRouterDecodingError):
            provider.generate_text("Call 1")
        assert closed[0] is True
        # Subsequent call on the same httpx.Client succeeds cleanly
        assert provider.generate_text("Call 2") == "Clean reuse after error"


# ---------------------------------------------------------------------------
# 9. Deadline enforcement during compressed streaming
# ---------------------------------------------------------------------------


def test_deadline_enforcement_during_compressed_streaming():
    class SlowGzipStream(httpx.SyncByteStream):
        def __iter__(self):
            time.sleep(0.35)
            yield gzip.compress(_chat_json_bytes("too late"))

    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, headers={"Content-Encoding": "gzip"}, stream=SlowGzipStream(), request=request)
        )
    ) as client:
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
        assert time.monotonic() - start < 0.25


# ---------------------------------------------------------------------------
# 10. Preservation of checkpoint & request accounting across decoding failures
# ---------------------------------------------------------------------------


def test_decoding_failure_preserves_checkpoint_and_request_accounting(tmp_path, monkeypatch):
    """
    A decoding failure during scene_1 must:
    - Preserve durable RequestLedger accounting (never reset to 0)
    - Preserve already-accepted ContentAnalysis and ScriptOutline in ScriptCheckpoint
    - Reuse accepted stages on retry without regenerating them.
    """
    monkeypatch.setattr("app.services.llm.openrouter_provider.time.sleep", lambda _: None)
    manager = ProjectManifestManager(tmp_path)
    req = TrainingVideoRequest(
        topic="Pasta Tutorial",
        source_content="Teach how to boil pasta.",
        base_language="ar-SA",
        target_languages=["ar-SA"],
        target_duration_seconds=30,
    )
    manager.create_manifest("p_decomp", req)

    # Pre-seed accepted ContentAnalysis & ScriptOutline in the project's checkpoint
    cp = ScriptCheckpoint(tmp_path / "p_decomp", req, "openrouter/free")
    analysis = ContentAnalysis(
        topic_summary="شرح سلق المكرونة",
        key_concepts=["سلق المكرونة"],
        learning_objectives=[LearningObjective(id="LO1", description="سلق المكرونة بشكل صحيح")],
        audience_notes="المبتدئون",
        recommended_scene_count=1,
        recommended_structure=["السلق"],
        important_terms=["مكرونة"],
        factual_constraints=["ماء مغلي"],
    )
    outline = ScriptOutline(
        title="طريقة سلق المكرونة",
        language="ar-SA",
        audience="المبتدئون",
        opening_hook="هل تريد سلق المكرونة بطريقة مثالية؟",
        closing_summary="صفها وقدمها ساخنة.",
        learning_objectives=analysis.learning_objectives,
        scene_outlines=[
            SceneOutlineItem(
                scene_id="scene_1",
                order=1,
                title="سلق المكرونة",
                purpose="شرح السلق",
                scene_type="intro",
                learning_objective_ids=["LO1"],
                target_duration_seconds=30,
            )
        ],
    )
    cp.put("analysis", analysis)
    cp.put("outline", outline)

    dispatched = []
    good_scene_json = json.dumps(
        {
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
        },
        ensure_ascii=False,
    )

    fail_first_run = [True]

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        sys_msg = body["messages"][0]["content"]
        if "`ContentAnalysis`" in sys_msg:
            dispatched.append("analysis")
        elif "`ScriptOutline`" in sys_msg:
            dispatched.append("outline")
        else:
            dispatched.append("scene_1")
        if fail_first_run[0]:
            return httpx.Response(200, headers={"Content-Encoding": "gzip"}, stream=httpx.ByteStream(b"corrupt"), request=request)
        gz = gzip.compress(_chat_json_bytes(good_scene_json))
        return httpx.Response(200, headers={"Content-Encoding": "gzip"}, stream=httpx.ByteStream(gz), request=request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        orch = ProjectOrchestrator.__new__(ProjectOrchestrator)
        orch.manifest_manager = manager
        orch.llm_provider = OpenRouterProvider(api_key="offline", model="openrouter/free", client=client, max_retries=4)

        # Run 1: fails on scene_1 with OpenRouterDecodingError (bounded to 2 attempts, never regenerates analysis/outline)
        m1 = orch.generate_canonical_script("p_decomp")
        assert m1.script_status == "failed"
        assert dispatched == ["scene_1", "scene_1"]
        assert RequestLedger(tmp_path / "p_decomp", ceiling=48, required=True).count == 2
        # Accepted analysis & outline remain intact in checkpoint
        reloaded_cp = ScriptCheckpoint(tmp_path / "p_decomp", req, "openrouter/free", required=True)
        assert reloaded_cp.get("analysis", ContentAnalysis) == analysis
        assert reloaded_cp.get("outline", ScriptOutline) == outline

        # Run 2: upstream now returns valid gzip -> resumes scene_1 directly without regenerating analysis/outline
        fail_first_run[0] = False
        m2 = orch.generate_canonical_script("p_decomp")
        assert m2.script_status == "completed"
        assert dispatched == ["scene_1", "scene_1", "scene_1"]
        # Cumulative request accounting preserved across both runs (2 failed + 1 succeeded = 3)
        assert RequestLedger(tmp_path / "p_decomp", ceiling=48, required=True).count == 3
        assert m2.metadata["script_openrouter_requests"] == 3

