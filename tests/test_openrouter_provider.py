"""Comprehensive unit and workflow integration tests for OpenRouterProvider.

Verifies:
1. Configuration-driven selection via LLM_PROVIDER='openrouter' or 'groq'.
2. Official base URL https://openrouter.ai/api/v1 and dynamic model configuration.
3. Structured JSON output generation, model capability detection, markdown/<think> extraction, and repair fallback.
4. Safe error handling for HTTP 401, HTTP 402, HTTP 413, HTTP 429, HTTP 5xx, and connection timeouts.
5. Oversized requests (HTTP 413) are never retried unchanged (at most 1 compacted retry).
6. Full compatibility with script generation and multilingual localization workflows.
7. Secret redaction for OpenRouter API keys.
"""

import json
from unittest.mock import MagicMock, patch
import httpx
import pytest

from app.core.config import Settings
from app.models.schemas import (
    ContentAnalysis,
    LearningObjective,
    ProjectManifest,
    SceneDraft,
    ScriptDraft,
    ScriptOutline,
    TrainingVideoRequest,
)
from app.services.llm.factory import get_llm_provider
from app.services.llm.groq_provider import GroqProvider
from app.services.llm.openrouter_provider import (
    OpenRouterAuthenticationError,
    OpenRouterConnectionError,
    OpenRouterInsufficientCreditsError,
    OpenRouterModelCompatibilityError,
    OpenRouterPayloadTooLargeError,
    OpenRouterProvider,
    OpenRouterRateLimitError,
    OpenRouterServerError,
    supports_json_object_mode,
    supports_strict_json_schema,
)
from app.workflows.script_generation.graph import create_script_workflow
from app.workflows.script_generation.state import VideoScriptState


def _make_httpx_json_response(status_code: int, payload: dict, headers: dict | None = None) -> httpx.Response:
    return httpx.Response(
        status_code=status_code,
        json=payload,
        headers=headers or {},
        request=httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions"),
    )


def _make_chat_success_response(content: str, finish_reason: str = "stop") -> httpx.Response:
    return _make_httpx_json_response(
        200,
        {
            "id": "gen-openrouter-test-123",
            "choices": [
                {
                    "index": 0,
                    "finish_reason": finish_reason,
                    "message": {"role": "assistant", "content": content},
                }
            ],
        },
    )


# ===========================================================================
# 1. Configuration & Factory Provider Selection Tests
# ===========================================================================


def test_factory_selects_openrouter_or_groq_from_env(monkeypatch):
    """Verify LLM_PROVIDER switches cleanly between 'openrouter' and 'groq' without code changes."""
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-mockkey1234567890")
    monkeypatch.setenv("OPENROUTER_MODEL", "google/gemini-2.0-flash-001")

    or_settings = Settings(_env_file=None)
    assert or_settings.LLM_PROVIDER == "openrouter"
    assert or_settings.DEFAULT_LLM_PROVIDER == "openrouter"
    assert or_settings.OPENROUTER_BASE_URL == "https://openrouter.ai/api/v1"

    with patch("app.services.llm.factory.settings", or_settings), patch(
        "app.services.llm.openrouter_provider.settings", or_settings
    ):
        provider = get_llm_provider()
        assert isinstance(provider, OpenRouterProvider)
        assert provider.model_name == "google/gemini-2.0-flash-001"
        assert provider._base_url == "https://openrouter.ai/api/v1"

    # Switch back to groq via LLM_PROVIDER
    monkeypatch.setenv("LLM_PROVIDER", "groq")
    monkeypatch.setenv("GROQ_API_KEY", "gsk_mockkey1234567890")
    monkeypatch.setenv("GROQ_MODEL", "llama-3.3-70b-versatile")

    groq_settings = Settings(_env_file=None)
    with patch("app.services.llm.factory.settings", groq_settings), patch(
        "app.services.llm.groq_provider.settings", groq_settings
    ):
        provider_groq = get_llm_provider()
        assert isinstance(provider_groq, GroqProvider)
        assert provider_groq.model_name == "llama-3.3-70b-versatile"


def test_openrouter_missing_api_key_raises_clear_error(monkeypatch):
    """Verify missing OPENROUTER_API_KEY raises a clear ValueError before making any network call."""
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    empty_settings = Settings(_env_file=None, OPENROUTER_API_KEY=None)
    with patch("app.services.llm.openrouter_provider.settings", empty_settings):
        provider = OpenRouterProvider(api_key=None)
        with pytest.raises(ValueError, match="OPENROUTER_API_KEY"):
            provider.generate_text("Hello")


# ===========================================================================
# 2. Model Capability Inspection & Structured Output Fallbacks
# ===========================================================================


def test_model_capability_detection():
    """Verify capability helper distinguishes strict json_schema models from prompt-schema models."""
    assert supports_strict_json_schema("openai/gpt-4o-mini") is True
    assert supports_strict_json_schema("google/gemini-2.0-flash-001") is True
    assert supports_strict_json_schema("meta-llama/llama-3.3-70b-instruct:free") is False
    assert supports_strict_json_schema("anthropic/claude-3.5-sonnet") is False
    assert supports_strict_json_schema("deepseek/deepseek-r1") is False

    assert supports_json_object_mode("anthropic/claude-3.5-sonnet") is True
    assert supports_json_object_mode("deepseek/deepseek-r1") is False


@pytest.mark.parametrize("schema", [ScriptOutline, SceneDraft])
@pytest.mark.parametrize(("message", "finish", "category"), [
    ({"reasoning": "PRIVATE", "content": None}, "length", "reasoning_budget_exhausted"),
    ({"reasoning_details": [{"type": "reasoning.encrypted"}]}, "stop", "reasoning_only"),
    ({"content": "<think>PRIVATE"}, "stop", "reasoning_only"),
    ({"content": "PRIVATE planning text"}, "stop", "non_json_final_content"),
    ({"content": []}, "stop", "empty_content"),
])
def test_truncated_initial_then_incompatible_repair(schema, message, finish, category, caplog):
    http = MagicMock()
    def response(model, finish, message):
        return _make_httpx_json_response(200, {
            "model": model, "choices": [{"finish_reason": finish, "message": message}],
            "usage": {"completion_tokens": 2048},
        })
    http.post.side_effect = [
        response("vendor/first:free", "length", {"content": '{"title":"PRIVATE'}),
        response("vendor/second:free", finish, message),
    ]
    provider = OpenRouterProvider(model="openrouter/free", api_key="test", client=http)
    with pytest.raises(OpenRouterModelCompatibilityError) as error:
        provider.generate_structured("Make an instructional video script", schema, max_tokens=1536)
    assert error.value.classification == category
    assert provider.last_routed_model == "vendor/second:free"
    assert provider.last_finish_reason == finish
    assert provider.last_usage == {"completion_tokens": 2048}
    assert "PRIVATE" not in str(error.value) + caplog.text
    first, repair = [call.kwargs["json"] for call in http.post.call_args_list]
    assert repair["max_tokens"] == first["max_tokens"]
    assert "PRIVATE" not in str(repair)
    assert repair["provider"] == first["provider"] == {"require_parameters": True}


def test_free_model_unavailable_only_uses_configured_free_candidates(monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "OPENROUTER_FALLBACK_MODELS", "vendor/paid,vendor/second:free")
    http = MagicMock()
    http.post.side_effect = [
        _make_httpx_json_response(404, {"error": {"message": "Unavailable for free", "metadata": {"raw": "PRIVATE"}}}),
        _make_chat_success_response(json.dumps(_build_valid_arabic_script_draft_dict())),
    ]
    provider = OpenRouterProvider(model="vendor/first:free", api_key="test", client=http, allow_paid_models=True)
    with pytest.raises(OpenRouterModelCompatibilityError):
        provider.generate_structured("Write script", ScriptDraft)
    assert [c.kwargs["json"]["model"] for c in http.post.call_args_list] == ["vendor/first:free"]


def test_free_router_never_drops_json_requirement_or_replays_http_body(caplog):
    http = MagicMock()
    http.post.return_value = _make_httpx_json_response(400, {"error": {
        "message": "unsupported parameter response_format PRIVATE", "metadata": {"raw": "PRIVATE"}}})
    provider = OpenRouterProvider(model="openrouter/free", api_key="test", client=http)
    with pytest.raises(OpenRouterModelCompatibilityError, match="model_unavailable") as error:
        provider.generate_structured("Write script", ScriptDraft)
    assert http.post.call_count == 1
    assert "PRIVATE" not in str(error.value) + caplog.text


def test_typed_content_parts_and_literal_punctuation_are_preserved():
    data = _build_valid_arabic_script_draft_dict()
    data["scenes"][0]["narration"] += ' Use "{...}" or "$defs" to explain the notation.'
    http = MagicMock()
    parts = [{"type": "reasoning", "text": "PRIVATE"}, {"type": "text", "text": json.dumps(data)}]
    http.post.return_value = _make_httpx_json_response(200, {"choices": [{"message": {"content": parts}}]})
    provider = OpenRouterProvider(model="openrouter/free", api_key="test", client=http)
    assert provider.generate_structured("Write script", ScriptDraft).scenes[0].narration == data["scenes"][0]["narration"]


def test_retry_after_outside_window_never_sleeps(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda _: pytest.fail("must surface the rate limit immediately"))
    http = MagicMock()
    http.post.return_value = _make_httpx_json_response(429, {}, headers={"Retry-After": "3600"})
    provider = OpenRouterProvider(model="openrouter/free", api_key="test", client=http)
    with pytest.raises(OpenRouterRateLimitError):
        provider.generate_structured("Write script", ScriptOutline)
    assert http.post.call_count == 1


def test_413_never_reposts_an_already_compact_request():
    http = MagicMock()
    http.post.return_value = _make_httpx_json_response(413, {})
    provider = OpenRouterProvider(model="openrouter/free", api_key="test", client=http)
    with pytest.raises(OpenRouterPayloadTooLargeError):
        provider.generate_text("Short task", max_tokens=128)
    assert http.post.call_count == 1


def test_acceptance_worker_in_cold_interpreter_without_network(tmp_path):
    import subprocess
    import sys
    # A fresh interpreter exposes import cycles hidden by pytest collection order.
    program = """
import os, sys
from pathlib import Path
import httpx
from scripts.verify_openrouter_script import worker
def reply(request):
    return httpx.Response(200, json={
        "model": "fixture/offline:free", "choices": [
            {"finish_reason": "length", "message": {"content": "", "reasoning": "PRIVATE"}}
        ], "usage": {"completion_tokens": 100, "completion_tokens_details": {"reasoning_tokens": 100}}
    })
os.environ["OPENROUTER_API_KEY"] = "offline-test-only"
sys.exit(worker(Path(sys.argv[1]), transport=httpx.MockTransport(reply)))
"""
    result = subprocess.run([sys.executable, "-c", program, str(tmp_path)], capture_output=True, timeout=20)
    assert result.returncode == 1
    log = (tmp_path / "requests.jsonl").read_text()
    entries = [json.loads(line) for line in log.splitlines()]
    assert [e["event"] for e in entries] == ["dispatch", "response", "error", "failed"]
    assert entries[1]["stage"] == "ContentAnalysis"
    assert entries[2]["category"] == "reasoning_budget_exhausted"
    assert "PRIVATE" not in log


def test_endpoint_retry_charges_same_project_and_stops_at_limit(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from app.api.v1.projects import manifest_manager, orchestrator
    from app.core.config import settings
    from app.main import create_app
    monkeypatch.setattr(settings, "STORAGE_PATH", tmp_path)
    monkeypatch.setattr(manifest_manager, "storage_base_dir", tmp_path)
    monkeypatch.setattr(settings, "OPENROUTER_SCRIPT_PROJECT_REQUEST_LIMIT", 1)
    http = MagicMock()
    http.post.return_value = _make_chat_success_response("PRIVATE planning text without JSON")
    monkeypatch.setattr(orchestrator, "llm_provider", OpenRouterProvider(model="openrouter/free", api_key="test", client=http))
    with TestClient(create_app()) as client:
        created = client.post("/api/v1/projects", json={"request": {"topic": "Cook pasta", "base_language": "ar-SA"}})
        assert created.status_code == 201
        pid = created.json()["project_id"]
        url = f"/api/v1/projects/{pid}/generate-script"
        first = client.post(url)
        assert first.status_code == 400 and "ContentAnalysis" in first.text
        second = client.post(url)
        assert second.status_code == 400 and "request limit" in second.text
        assert "PRIVATE" not in first.text + second.text
        assert http.post.call_count == 1
        assert list(tmp_path.glob("*/project.json")) == [tmp_path / pid / "project.json"]
        assert manifest_manager.load_manifest(pid).metadata["script_openrouter_requests"] == 1


def test_structured_output_strict_schema_and_fallback_on_unsupported_model():
    """
    Verify:
    - OpenAI model attempts strict json_schema first.
    - If upstream returns HTTP 400 unsupported response_format, it falls back to json_object mode automatically.
    """
    mock_http = MagicMock()
    unsupported_resp = _make_httpx_json_response(
        400,
        {"error": {"code": 400, "message": "No endpoints found that support the provided response_format json_schema"}},
    )
    valid_scene = {
        "scene_id": "scene_1",
        "order": 1,
        "title": "Introduction",
        "narration": "Welcome to our training video.",
        "visual_direction": "Presenter in studio",
        "estimated_duration_seconds": 10,
    }
    success_resp = _make_chat_success_response(json.dumps(valid_scene))
    mock_http.post.side_effect = [unsupported_resp, success_resp]

    provider = OpenRouterProvider(
        api_key="sk-or-v1-test",
        model="openai/gpt-4o-mini",
        client=mock_http,
        allow_paid_models=True,
    )
    scene = provider.generate_structured("Create scene 1", schema=SceneDraft)
    assert isinstance(scene, SceneDraft)
    assert scene.title == "Introduction"
    assert mock_http.post.call_count == 2

    # First call used json_schema; second call used json_object
    first_payload = mock_http.post.call_args_list[0].kwargs["json"]
    second_payload = mock_http.post.call_args_list[1].kwargs["json"]
    assert first_payload["response_format"]["type"] == "json_schema"
    assert second_payload["response_format"]["type"] == "json_object"


def test_structured_output_handles_reasoning_tags_and_markdown_fences():
    """Verify models like DeepSeek R1 or free models returning <think> tags and ```json fences parse cleanly."""
    mock_http = MagicMock()
    fenced_output = (
        "<think>\nLet me structure the pedagogical scene carefully.\n</think>\n"
        "Here is the JSON output:\n"
        "```json\n"
        '{"scene_id": "scene_1", "order": 1, "title": "تفاصيل البشاميل", '
        '"narration": "مرحباً بكم في طريقة تحضير المكرونة بالبشاميل.", '
        '"visual_direction": "عرض المطبخ", "estimated_duration_seconds": 15}\n'
        "```"
    )
    mock_http.post.return_value = _make_chat_success_response(fenced_output)

    provider = OpenRouterProvider(
        api_key="sk-or-v1-test",
        model="deepseek/deepseek-r1:free",
        client=mock_http,
        allow_paid_models=True,
    )
    scene = provider.generate_structured("Create Arabic scene", schema=SceneDraft)
    assert isinstance(scene, SceneDraft)
    assert scene.title == "تفاصيل البشاميل"
    # Verify only 1 API call was needed because strict json_schema was skipped for :free / deepseek-r1
    assert mock_http.post.call_count == 1
    sent_payload = mock_http.post.call_args.kwargs["json"]
    assert sent_payload["response_format"] == {"type": "json_object"}


def test_structured_output_bounded_repair_on_validation_failure():
    """Verify invalid JSON triggers exactly 1 bounded repair call."""
    mock_http = MagicMock()
    broken_json = '{"scene_id": "scene_1", "order": "not_an_int"}'
    fixed_json = json.dumps(
        {
            "scene_id": "scene_1",
            "order": 1,
            "title": "Repaired Scene",
            "narration": "Valid narration after repair.",
            "visual_direction": "Clean slide",
            "estimated_duration_seconds": 12,
        }
    )
    mock_http.post.side_effect = [
        _make_chat_success_response(broken_json),
        _make_chat_success_response(fixed_json),
    ]

    provider = OpenRouterProvider(
        api_key="sk-or-v1-test",
        model="anthropic/claude-3.5-haiku",
        client=mock_http,
        allow_paid_models=True,
    )
    scene = provider.generate_structured("Draft scene", schema=SceneDraft)
    assert scene.title == "Repaired Scene"
    assert mock_http.post.call_count == 2


# ===========================================================================
# 3. Error Handling: HTTP 401, 402, 413, 429, 5xx, and Timeouts
# ===========================================================================


def test_http_401_authentication_error_never_retries():
    """Verify HTTP 401 raises OpenRouterAuthenticationError immediately on Attempt 1."""
    mock_http = MagicMock()
    mock_http.post.return_value = _make_httpx_json_response(
        401,
        {"error": {"code": 401, "message": "No auth credentials found"}},
    )
    provider = OpenRouterProvider(api_key="sk-or-v1-invalid", model="openai/gpt-4o-mini", client=mock_http, allow_paid_models=True)

    with pytest.raises(OpenRouterAuthenticationError, match="HTTP 401"):
        provider.generate_text("Test")
    assert mock_http.post.call_count == 1


def test_http_402_insufficient_credits_never_retries():
    """Verify HTTP 402 raises OpenRouterInsufficientCreditsError immediately on Attempt 1."""
    mock_http = MagicMock()
    mock_http.post.return_value = _make_httpx_json_response(
        402,
        {"error": {"code": 402, "message": "Insufficient credits. Please add credits to your OpenRouter account."}},
    )
    provider = OpenRouterProvider(api_key="sk-or-v1-nocredits", model="openai/gpt-4o", client=mock_http, allow_paid_models=True)

    with pytest.raises(OpenRouterInsufficientCreditsError, match="HTTP 402"):
        provider.generate_text("Test")
    assert mock_http.post.call_count == 1


def test_http_413_oversized_request_never_retried_unchanged():
    """
    Verify HTTP 413 never retries the identical oversized request in a loop:
    - Performs at most 1 compacted retry with shortened messages and reduced max_tokens.
    - If compacted retry also returns 413, raises OpenRouterPayloadTooLargeError immediately (2 calls total, not max_retries).
    """
    mock_http = MagicMock()
    resp_413 = _make_httpx_json_response(
        413,
        {"error": {"code": 413, "message": "Request too large for model: Limit 8000, Requested 8373"}},
    )
    mock_http.post.side_effect = [resp_413, resp_413]

    provider = OpenRouterProvider(
        api_key="sk-or-v1-test",
        model="meta-llama/llama-3.3-70b-instruct",
        max_retries=5,
        client=mock_http,
        allow_paid_models=True,
    )
    long_prompt = "Detailed instructional paragraph. " * 400

    with pytest.raises(OpenRouterPayloadTooLargeError, match="8373"):
        provider.generate_text(long_prompt, max_tokens=4096)

    # Strictly 2 calls (initial + 1 compacted retry), NEVER 5 unchanged retries
    assert mock_http.post.call_count == 2
    call_1_payload = mock_http.post.call_args_list[0].kwargs["json"]
    call_2_payload = mock_http.post.call_args_list[1].kwargs["json"]
    assert len(call_2_payload["messages"][0]["content"]) < len(call_1_payload["messages"][0]["content"])
    assert call_2_payload["max_tokens"] == 2048


def test_http_413_compacted_retry_succeeds_when_within_limit():
    """Verify that if the single compacted retry fits within the model's token budget, the call succeeds."""
    mock_http = MagicMock()
    resp_413 = _make_httpx_json_response(
        413,
        {"error": {"code": 413, "message": "Request too large for model: Limit 8000, Requested 8373"}},
    )
    resp_200 = _make_chat_success_response("Compacted request succeeded")
    mock_http.post.side_effect = [resp_413, resp_200]

    provider = OpenRouterProvider(
        api_key="sk-or-v1-test",
        model="meta-llama/llama-3.3-70b-instruct",
        client=mock_http,
        allow_paid_models=True,
    )
    res = provider.generate_text("Paragraph " * 600, max_tokens=4096)
    assert res == "Compacted request succeeded"
    assert mock_http.post.call_count == 2


def test_groq_http_413_never_retries_unchanged():
    """Verify GroqProvider also aborts immediately on HTTP 413 oversized request instead of retrying 5 times."""
    from groq import RateLimitError

    mock_groq_client = MagicMock()
    resp_413 = httpx.Response(
        status_code=413,
        request=httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions"),
    )
    err_413 = RateLimitError(
        message="Error code: 413 - {'error': {'message': 'Request too large for model openai/gpt-oss-120b. Limit 8000, Requested 8373'}}",
        response=resp_413,
        body={"error": {"message": "Request too large", "code": "rate_limit_exceeded"}},
    )
    mock_groq_client.chat.completions.create.side_effect = err_413

    provider = GroqProvider(api_key="gsk_test", model="openai/gpt-oss-120b", max_retries=5, client=mock_groq_client)
    with pytest.raises(RateLimitError):
        provider.generate_text("Oversized prompt")
    assert mock_groq_client.chat.completions.create.call_count == 1


def test_http_429_rate_limit_retries_with_backoff(monkeypatch):
    """Verify HTTP 429 retries honoring Retry-After and succeeds."""
    monkeypatch.setattr("time.sleep", lambda s: None)
    mock_http = MagicMock()
    resp_429 = _make_httpx_json_response(
        429,
        {"error": {"code": 429, "message": "Rate limit exceeded"}},
        headers={"retry-after": "1.0"},
    )
    resp_200 = _make_chat_success_response("Recovered after 429")
    mock_http.post.side_effect = [resp_429, resp_200]

    provider = OpenRouterProvider(api_key="sk-or-v1-test", model="openai/gpt-4o-mini", max_retries=3, client=mock_http, allow_paid_models=True)
    assert provider.generate_text("Hello") == "Recovered after 429"
    assert mock_http.post.call_count == 2


def test_http_5xx_and_timeout_retry_and_preserve_cause(monkeypatch):
    """Verify 5xx and timeout errors retry up to max_retries and include the real cause in RuntimeError."""
    monkeypatch.setattr("time.sleep", lambda s: None)
    mock_http = MagicMock()
    mock_http.post.side_effect = httpx.ReadTimeout("Read timed out waiting for upstream model")

    provider = OpenRouterProvider(api_key="sk-or-v1-test", model="openai/gpt-4o-mini", max_retries=2, client=mock_http, allow_paid_models=True)
    with pytest.raises(RuntimeError) as exc_info:
        provider.generate_text("Hello")

    assert mock_http.post.call_count == 2
    assert "OpenRouter API call failed after 2 attempts" in str(exc_info.value)
    assert "timed out" in str(exc_info.value).lower()


# ===========================================================================
# 4. End-to-End Script Workflow Integration with OpenRouterProvider
# ===========================================================================


def test_script_workflow_with_openrouter_provider_english_to_arabic():
    """Verify LangGraph script workflow executes end-to-end using OpenRouterProvider."""
    mock_http = MagicMock()

    analysis_json = json.dumps(
        {
            "topic_summary": "تحضير المكرونة بالبشاميل المصرية",
            "key_concepts": ["سلق المكرونة", "صلصة البشاميل"],
            "learning_objectives": [
                {"id": "LO1", "description": "تحضير صلصة البشاميل الكريمية وخبز الصينية"}
            ],
            "audience_notes": "الطهاة المبتدئون",
            "recommended_scene_count": 1,
            "recommended_structure": ["التحضير والخبز"],
            "important_terms": ["Béchamel"],
            "factual_constraints": ["ضبط قوام الصلصة"],
        },
        ensure_ascii=False,
    )

    ar_narration_58_words = (
        "مرحباً بكم في درس تحضير المكرونة بالبشاميل المصرية الأصيلة في مطبخكم خطوة بخطوة. "
        "نبدأ أولاً بسلق المكرونة القلم في ماء مغلي مملح حتى تنضج بشكل مثالي ومتماسك. "
        "بعد ذلك نقوم بتعصيج اللحم المفروم مع البصل المفروم والثوم والملح والفلفل الأسود والقرفة. "
        "ثم نحضر صلصة البشاميل الكريمية بمزج الزبدة والدقيق والحليب الدافئ ونرتب الطبقات ونخبزها بالفرن."
    )

    script_json = json.dumps(
        {
            "title": "طريقة عمل المكرونة بالبشاميل",
            "language": "ar-SA",
            "audience": "الطهاة",
            "learning_objectives": [
                {"id": "LO1", "description": "تحضير صلصة البشاميل الكريمية وخبز الصينية"}
            ],
            "opening_hook": "هل تريد إعداد أشهى مكرونة بالبشاميل؟",
            "closing_summary": "قدمها ساخنة بالهناء والشفاء.",
            "scenes": [
                {
                    "scene_id": "scene_1",
                    "order": 1,
                    "title": "تحضير البشاميل والطبقات",
                    "purpose": "شرح الخطوات",
                    "scene_type": "demonstration",
                    "narration": ar_narration_58_words,
                    "visual_direction": "عرض خطوات خفق الزبدة والدقيق والحليب.",
                    "on_screen_text": "تحضير البشاميل",
                    "learning_objective_ids": ["LO1"],
                    "estimated_duration_seconds": 30,
                }
            ],
            "total_estimated_duration_seconds": 30,
        },
        ensure_ascii=False,
    )

    mock_http.post.side_effect = [
        _make_chat_success_response(analysis_json),
        _make_chat_success_response(script_json),
    ]

    or_provider = OpenRouterProvider(
        api_key="sk-or-v1-test",
        model="google/gemini-2.0-flash-001",
        client=mock_http,
        allow_paid_models=True,
    )

    workflow = create_script_workflow(llm_provider=or_provider)
    req = TrainingVideoRequest(
        topic="Egyptian Macaroni Béchamel",
        source_content="Boil penne pasta, brown minced meat with onions, make béchamel sauce, layer and bake.",
        base_language="ar-SA",
        target_languages=["ar-SA"],
        target_duration_seconds=30,
    )
    state = workflow.invoke(VideoScriptState(request=req))

    assert state["workflow_status"] == "completed"
    assert state["final_script"] is not None
    assert state["final_script"].language == "ar-SA"
    assert state["final_script"].metadata["llm_model"] == "google/gemini-2.0-flash-001"


def test_openrouter_key_redacted_in_manifest_errors():
    """Verify sk-or-v1-... keys are automatically redacted from manifest diagnostics."""
    manifest = ProjectManifest(
        project_id="test_or_redaction",
        source_request=TrainingVideoRequest(topic="Security", base_language="en-US"),
    )
    fake_or_key = "sk-or-v1-9876543210abcdef9876543210abcdef"
    manifest.record_error(
        stage="script",
        message=f"OpenRouter failed with key {fake_or_key}",
        code="OR_ERR",
    )
    assert fake_or_key not in manifest.errors[0]
    assert "sk-or-[REDACTED]" in manifest.errors[0]


def test_openrouter_free_model_rejects_json_in_reasoning():
    """
    Regression test for nvidia/nemotron-3-super-120b-a12b:free:
    Reasoning may contain a perfectly formed instance. It is never the final answer.
    """
    assert supports_strict_json_schema("nvidia/nemotron-3-super-120b-a12b:free") is False
    assert supports_json_object_mode("nvidia/nemotron-3-super-120b-a12b:free") is True

    mock_http = MagicMock()
    reasoning_resp = _make_httpx_json_response(
        200,
        {
            "id": "gen-nemotron-1",
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "stop",
                    "message": {
                        "role": "assistant",
                        "content": "",
                        "reasoning": (
                            "Thinking step...\n```json\n"
                            '{"scene_id": "scene_1", "order": 1, "title": "المكونات", '
                            '"narration": "نبدأ بتحضير المكرونة واللحم المفروم.", '
                            '"visual_direction": "عرض المكونات", "estimated_duration_seconds": 10}\n```'
                        ),
                    },
                }
            ],
        },
    )
    mock_http.post.return_value = reasoning_resp

    provider = OpenRouterProvider(
        api_key="sk-or-v1-test",
        model="nvidia/nemotron-3-super-120b-a12b:free",
        client=mock_http,
        allow_paid_models=True,
    )
    with pytest.raises(OpenRouterModelCompatibilityError, match="reasoning_only"):
        provider.generate_structured("Generate Arabic scene", schema=SceneDraft)
    assert mock_http.post.call_count == 1
    sent_payload = mock_http.post.call_args.kwargs["json"]
    assert sent_payload["response_format"] == {"type": "json_object"}
    assert sent_payload["provider"]["require_parameters"] is True


def test_groq_fallback_json_object_recovers_from_json_validate_failed():
    """
    Regression test for proj_6c4e40013063 failure:
    When Groq returns 400 json_validate_failed on BOTH strict json_schema AND json_object mode,
    GroqProvider retries once without response_format and extracts the JSON payload cleanly.
    """
    from groq import APIError

    mock_groq_client = MagicMock()
    api_err = APIError(
        message="Failed to validate JSON",
        request=httpx.Request("POST", "https://api.groq.com"),
        body={"error": {"code": "json_validate_failed", "message": "Failed to validate JSON", "failed_generation": ""}},
    )
    valid_scene_fenced = (
        "```json\n"
        '{"scene_id": "scene_1", "order": 1, "title": "البشاميل", '
        '"narration": "نخلط الدقيق مع الزبدة والحليب.", '
        '"visual_direction": "تحضير الصلصة", "estimated_duration_seconds": 12}\n```'
    )
    mock_choice = MagicMock()
    mock_choice.message.content = valid_scene_fenced
    mock_choice.finish_reason = "stop"
    success_resp = MagicMock(choices=[mock_choice])

    # Call 1 (strict json_schema) -> 400 json_validate_failed
    # Call 2 (json_object) -> 400 json_validate_failed
    # Call 3 (prompt-enforced without response_format) -> succeeds!
    mock_groq_client.chat.completions.create.side_effect = [api_err, api_err, success_resp]

    provider = GroqProvider(api_key="gsk_test", model="openai/gpt-oss-120b", client=mock_groq_client)
    scene = provider.generate_structured("Revise scene", schema=SceneDraft)
    assert scene.title == "البشاميل"
    assert mock_groq_client.chat.completions.create.call_count == 3
    third_call_kwargs = mock_groq_client.chat.completions.create.call_args_list[2].kwargs
    assert "response_format" not in third_call_kwargs


def test_generate_script_endpoint_returns_sanitized_400_instead_of_unhandled_500(tmp_path, monkeypatch):
    """
    Regression test verifying that if workflow creation or execution raises an unhandled error,
    POST /api/v1/projects/{id}/generate-script catches it, records a sanitized error on the manifest,
    and returns a structured HTTP 400 JSON response instead of a raw HTTP 500 Internal Server Error.
    """
    from fastapi.testclient import TestClient
    from app.core.config import settings
    from app.main import create_app
    from app.api.v1.projects import manifest_manager, orchestrator

    test_storage = tmp_path / "storage"
    test_storage.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "STORAGE_PATH", test_storage)
    monkeypatch.setattr(manifest_manager, "storage_base_dir", test_storage)

    def _boom_workflow(*args, **kwargs):
        raise ValueError("Missing OPENROUTER_API_KEY (attempted key sk-or-v1-secret999999999999999999)")

    monkeypatch.setattr("app.workflows.orchestrator.create_script_workflow", _boom_workflow)

    app = create_app()
    with TestClient(app) as client:
        c_res = client.post(
            "/api/v1/projects",
            json={
                "project_id": "proj_reg_500_test",
                "request": {
                    "topic": "Egyptian Macaroni Béchamel",
                    "base_language": "ar-SA",
                    "target_languages": ["ar-SA"],
                    "target_duration_seconds": 30,
                },
            },
        )
        assert c_res.status_code == 201

        g_res = client.post("/api/v1/projects/proj_reg_500_test/generate-script")
        assert g_res.status_code == 400
        detail = g_res.json()["detail"]
        assert detail["code"] == "SCRIPT_GENERATION_FAILED"
        assert "sk-or-[REDACTED]" in detail["message"]
        assert "secret999999999999999999" not in detail["message"]


# ===========================================================================
# 5. Regression Tests: ScriptDraft Schema Echo, Placeholders, Truncation & Repair
# ===========================================================================


def _build_valid_arabic_script_draft_dict() -> dict:
    return {
        "title": "طريقة عمل المكرونة بالبشاميل المصرية",
        "language": "ar-SA",
        "audience": "المبتدئون في الطبخ",
        "learning_objectives": [
            {"id": "LO1", "description": "تحضير صلصة البشاميل الكريمية وترتيب طبقات الصينية"}
        ],
        "opening_hook": "هل ترغب في تحضير مكرونة بالبشاميل ذهبية ومثالية؟",
        "closing_summary": "اترك الصينية تهدأ قليلاً قبل التقطيع والتقديم.",
        "scenes": [
            {
                "scene_id": "scene_1",
                "order": 1,
                "title": "تحضير المكونات والبشاميل",
                "purpose": "شرح المقادير الأساسية وخطوات الصلصة",
                "scene_type": "demonstration",
                "narration": "نبدأ بسلق المكرونة القلم ثم نحمص الدقيق مع الزبدة ونضيف الحليب تدريجياً مع الخفق المستمر.",
                "visual_direction": "لقطة قريبة لخفق صلصة البشاميل في القدر.",
                "on_screen_text": "تحضير صلصة البشاميل",
                "learning_objective_ids": ["LO1"],
                "estimated_duration_seconds": 30,
            }
        ],
        "total_estimated_duration_seconds": 30,
    }


def test_script_draft_schema_echo_detected_and_repaired():
    """
    Regression test for proj_7d62abd57990:
    1. Verifies system prompt uses a concrete JSON instance example (no '$defs' or 'additionalProperties').
    2. When the initial response returns a JSON Schema echo with placeholder ellipses:
       `{"$defs":{...},"properties":{"language":{...},"audience":{...},"scenes":{...}},"required":[...],"type":"object","additionalProperties":false}`
       it is detected as a JSON Schema definition, triggers 1 bounded repair call including both the invalid
       output and the schema-echo validation error, and succeeds when the repair returns a valid ScriptDraft.
    """
    mock_http = MagicMock()
    schema_echo_output = (
        '{"$defs":{...},"properties":{"language":{...},"audience":{...},"scenes":{...}},'
        '"required":[...],"type":"object","additionalProperties":false}'
    )
    valid_script_json = json.dumps(_build_valid_arabic_script_draft_dict(), ensure_ascii=False)

    mock_http.post.side_effect = [
        _make_chat_success_response(schema_echo_output),
        _make_chat_success_response(valid_script_json),
    ]

    provider = OpenRouterProvider(
        api_key="sk-or-v1-test",
        model="openrouter/free",
        client=mock_http,
    )
    draft = provider.generate_structured("Generate Arabic ScriptDraft", schema=ScriptDraft)
    assert isinstance(draft, ScriptDraft)
    assert draft.language == "ar-SA"
    assert len(draft.scenes) == 1
    assert mock_http.post.call_count == 2

    # 1. Verify initial system prompt did NOT inject raw '$defs' JSON Schema
    initial_payload = mock_http.post.call_args_list[0].kwargs["json"]
    initial_sys_msg = initial_payload["messages"][0]["content"]
    assert '"$defs"' not in initial_sys_msg
    assert "Do NOT output a JSON Schema definition" in initial_sys_msg

    # 2. Verify repair prompt includes both the invalid previous output and the schema-echo validation error
    repair_payload = mock_http.post.call_args_list[1].kwargs["json"]
    repair_user_msg = repair_payload["messages"][-1]["content"]
    assert "JSON Schema definition" in repair_user_msg
    assert all(schema_echo_output not in msg["content"] for msg in repair_payload["messages"])


def test_script_draft_repeated_schema_echo_or_placeholders_raises_model_compatibility_error():
    """
    Verify that if a free model routed by `openrouter/free` returns a schema echo on Attempt 1
    and placeholder ellipses `{"scenes": [{...}]}` on the repair attempt, `OpenRouterModelCompatibilityError`
    is raised after 1 bounded repair attempt (2 HTTP calls total) and names the routed model.
    """
    mock_http = MagicMock()
    initial_resp = _make_httpx_json_response(
        200,
        {
            "id": "gen-free-1",
            "model": "liquid/lfm-40b:free",
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "stop",
                    "message": {
                        "role": "assistant",
                        "content": '{"$defs":{...},"properties":{"language":{...},"scenes":{...}},"type":"object"}',
                    },
                }
            ],
        },
    )
    repair_resp = _make_httpx_json_response(
        200,
        {
            "id": "gen-free-2",
            "model": "liquid/lfm-40b:free",
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "stop",
                    "message": {
                        "role": "assistant",
                        "content": '{"title": "طريقة عمل المكرونة", "language": "ar-SA", "scenes": [{...}]}',
                    },
                }
            ],
        },
    )
    mock_http.post.side_effect = [initial_resp, repair_resp]

    provider = OpenRouterProvider(
        api_key="sk-or-v1-test",
        model="openrouter/free",
        client=mock_http,
    )
    with pytest.raises(OpenRouterModelCompatibilityError) as exc_info:
        provider.generate_structured("Generate Arabic ScriptDraft", schema=ScriptDraft)

    err_text = str(exc_info.value)
    assert "OpenRouter output validation failed for ScriptDraft after repair attempt" in err_text
    assert "openrouter/free" in err_text
    assert "liquid/lfm-40b:free" in err_text
    assert "placeholder" in err_text.lower()
    # Strictly 1 initial + 1 repair attempt = 2 calls
    assert mock_http.post.call_count == 2


def test_script_draft_truncated_json_triggers_repair_and_recovers():
    """Verify truncated JSON output (unclosed braces) is reported clearly in the repair prompt and recovers."""
    mock_http = MagicMock()
    truncated_json = '{"title": "طريقة عمل المكرونة بالبشاميل", "language": "ar-SA", "audience": "المبتدئون", "scenes": [{"scene_id": "scene_1"'
    valid_script_json = json.dumps(_build_valid_arabic_script_draft_dict(), ensure_ascii=False)

    mock_http.post.side_effect = [
        _make_chat_success_response(truncated_json, finish_reason="length"),
        _make_chat_success_response(valid_script_json),
    ]

    provider = OpenRouterProvider(
        api_key="sk-or-v1-test",
        model="openrouter/free",
        client=mock_http,
    )
    draft = provider.generate_structured("Generate Arabic ScriptDraft", schema=ScriptDraft)
    assert isinstance(draft, ScriptDraft)
    assert draft.title == "طريقة عمل المكرونة بالبشاميل المصرية"
    assert mock_http.post.call_count == 2

    repair_user_msg = mock_http.post.call_args_list[1].kwargs["json"]["messages"][-1]["content"]
    assert "Truncated JSON output" in repair_user_msg


def test_script_draft_missing_fields_and_ellipsis_narration_triggers_repair():
    """Verify missing required fields or placeholder '...' narration are rejected and repaired."""
    mock_http = MagicMock()
    missing_fields_json = json.dumps(
        {
            "title": "طريقة عمل المكرونة بالبشاميل",
            "language": "ar-SA",
            # missing audience, learning_objectives, opening_hook, closing_summary, scenes, total_estimated_duration_seconds
        },
        ensure_ascii=False,
    )
    valid_script_json = json.dumps(_build_valid_arabic_script_draft_dict(), ensure_ascii=False)

    mock_http.post.side_effect = [
        _make_chat_success_response(missing_fields_json),
        _make_chat_success_response(valid_script_json),
    ]

    provider = OpenRouterProvider(
        api_key="sk-or-v1-test",
        model="openrouter/free",
        client=mock_http,
    )
    draft = provider.generate_structured("Generate Arabic ScriptDraft", schema=ScriptDraft)
    assert isinstance(draft, ScriptDraft)
    assert len(draft.scenes) == 1
    assert mock_http.post.call_count == 2


def test_reasoning_text_ignored_when_message_content_has_valid_json():
    """
    Verify that when `message.content` contains a valid structured JSON response,
    `message.reasoning` (even if it contains schema notes like `{"$defs":{...}}`) is never used.
    """
    mock_http = MagicMock()
    valid_script_json = json.dumps(_build_valid_arabic_script_draft_dict(), ensure_ascii=False)
    resp_with_reasoning_and_content = _make_httpx_json_response(
        200,
        {
            "id": "gen-reasoning-and-content",
            "model": "deepseek/deepseek-r1:free",
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "stop",
                    "message": {
                        "role": "assistant",
                        "content": valid_script_json,
                        "reasoning": (
                            'The user wants a ScriptDraft instead of {"$defs":{...},"properties":{"scenes":{...}}}. '
                            "I will place the real JSON object in content."
                        ),
                    },
                }
            ],
        },
    )
    mock_http.post.return_value = resp_with_reasoning_and_content

    provider = OpenRouterProvider(
        api_key="sk-or-v1-test",
        model="openrouter/free",
        client=mock_http,
    )
    draft = provider.generate_structured("Generate Arabic ScriptDraft", schema=ScriptDraft)
    assert isinstance(draft, ScriptDraft)
    assert draft.title == "طريقة عمل المكرونة بالبشاميل المصرية"
    assert mock_http.post.call_count == 1


# ===========================================================================
# 6. Staged Structured Script Generation & Targeted Scene Repair Tests
# ===========================================================================


def test_openrouter_tracks_routed_model_finish_reason_and_token_usage():
    """Verify OpenRouterProvider records routed model, finish_reason, and token usage metadata."""
    mock_http = MagicMock()
    mock_http.post.return_value = _make_httpx_json_response(
        200,
        {
            "id": "gen-meta-123",
            "model": "nvidia/nemotron-3.5-super-vl:free",
            "usage": {
                "prompt_tokens": 820,
                "completion_tokens": 410,
                "total_tokens": 1230,
                "completion_tokens_details": {"reasoning_tokens": 250},
            },
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "stop",
                    "message": {"role": "assistant", "content": "مرحباً بكم"},
                }
            ],
        },
    )
    provider = OpenRouterProvider(api_key="sk-or-v1-test", model="openrouter/free", client=mock_http)
    assert provider.prefers_staged_script_generation is True
    out = provider.generate_text("Hello")
    assert out == "مرحباً بكم"
    assert provider.last_routed_model == "nvidia/nemotron-3.5-super-vl:free"
    assert provider.last_finish_reason == "stop"
    assert provider.last_usage["total_tokens"] == 1230
    assert provider.last_usage["completion_tokens_details"]["reasoning_tokens"] == 250


@pytest.mark.parametrize("interrupt", [False, True])
def test_staged_script_generation_with_openrouter_free_6_scenes_arabic(tmp_path, interrupt):
    """
    End-to-end regression test for `proj_8de2e8e1a455` (6-scene Egyptian Macaroni Béchamel in Arabic)
    using `openrouter/free` with Staged Structured Generation:
    - Call 1: ContentAnalysis
    - Call 2: Stage 1 ScriptOutline (6 scene_outlines)
    - Calls 3..8: Stage 2 SceneDraft (6 individual scenes, each ~19-20 Arabic words = ~10s at 115 WPM -> 60s total)
    - Stage 3 Assembly & Stage 4 Validation: produces a valid 6-scene FinalScript in `ar-SA` with all V2 media plans.
    """
    mock_http = MagicMock()

    analysis_payload = {
        "topic_summary": "شرح تحضير المكرونة بالبشاميل المصرية في ستين ثانية خطوة بخطوة",
        "key_concepts": ["سلق المكرونة", "تعصيج اللحم", "صلصة البشاميل", "تجميع الطبقات والخبز"],
        "learning_objectives": [
            {"id": "LO1", "description": "تجهيز المكونات الأساسية وسلق المكرونة وتحضير اللحم المفروم"},
            {"id": "LO2", "description": "إعداد صلصة البشاميل الكريمية وتجميع الصينية وخبزها في الفرن"},
        ],
        "audience_notes": "المبتدئون ومحبو الطبخ المنزلي",
        "recommended_scene_count": 6,
        "recommended_structure": [
            "المقدمة",
            "المكونات",
            "المكرونة واللحم",
            "صلصة البشاميل",
            "ترتيب الطبقات",
            "الخبز والتقديم",
        ],
        "important_terms": ["بشاميل", "180°C"],
        "factual_constraints": ["الخبز على درجة حرارة 180 مئوية"],
    }

    outline_payload = {
        "title": "طريقة عمل المكرونة بالبشاميل المصرية خطوة بخطوة",
        "language": "ar-SA",
        "audience": "المبتدئون ومحبو الطبخ المصري",
        "opening_hook": "هل تريد تحضير ألذ صينية مكرونة بالبشاميل مصرية ذهبية في مطبخك بسهولة؟",
        "closing_summary": "قدم المكرونة بالبشاميل ساخنة بعد أن تهدأ قليلاً واستمتع بطعمها الرائع.",
        "learning_objectives": analysis_payload["learning_objectives"],
        "scene_outlines": [
            {
                "scene_id": "scene_1",
                "order": 1,
                "title": "مقدمة الطبق المصري الأصيل",
                "purpose": "التعريف بطبق المكرونة بالبشاميل",
                "scene_type": "intro",
                "learning_objective_ids": ["LO1"],
                "target_duration_seconds": 10,
            },
            {
                "scene_id": "scene_2",
                "order": 2,
                "title": "المكونات الأساسية للوصفة",
                "purpose": "عرض المقادير المطلوبة",
                "scene_type": "explanation",
                "learning_objective_ids": ["LO1"],
                "target_duration_seconds": 10,
            },
            {
                "scene_id": "scene_3",
                "order": 3,
                "title": "سلق المكرونة وتعصيج اللحم",
                "purpose": "شرح خطوات السلق وطهي اللحم",
                "scene_type": "visual_demo",
                "learning_objective_ids": ["LO1"],
                "target_duration_seconds": 10,
            },
            {
                "scene_id": "scene_4",
                "order": 4,
                "title": "تحضير صلصة البشاميل الكريمية",
                "purpose": "شرح مزج الزبدة والدقيق والحليب",
                "scene_type": "visual_demo",
                "learning_objective_ids": ["LO2"],
                "target_duration_seconds": 10,
            },
            {
                "scene_id": "scene_5",
                "order": 5,
                "title": "ترتيب الطبقات في الصينية",
                "purpose": "تجميع المكرونة واللحم والبشاميل",
                "scene_type": "visual_demo",
                "learning_objective_ids": ["LO2"],
                "target_duration_seconds": 10,
            },
            {
                "scene_id": "scene_6",
                "order": 6,
                "title": "الخبز في الفرن والتقديم",
                "purpose": "خبز الصينية حتى تصبح ذهبية وتقديمها",
                "scene_type": "outro",
                "learning_objective_ids": ["LO2"],
                "target_duration_seconds": 10,
            },
        ],
    }

    # Each scene has 19 Arabic words -> round((19 / 115) * 60) = 10s -> 6 scenes * 10s = 60s exact!
    narrations_19_words = [
        "أهلاً بكم في مطبخنا اليوم لنتعلم معاً طريقة تحضير صينية المكرونة بالبشاميل المصرية الشهية بخطوات بسيطة وسريعة جداً ومضمونة.",
        "نحتاج في هذه الوصفة إلى مكرونة قلم ولحم بقري مفروم وبصل مفروم وحليب طازج ودقيق وزبدة وملح وفلفل أسود.",
        "نسلق المكرونة في ماء مملح حتى تقترب من النضج ثم نشوح البصل ونضيف اللحم المفروم والتوابل حتى ينضج تماماً.",
        "في قدر على النار نذيب الزبدة ونقلب الدقيق جيداً ثم نضيف الحليب تدريجياً مع الخفق المستمر ليتكون قوام كريمي.",
        "نضع طبقة من المكرونة المخلوطة بالبشاميل في صينية الفرن ثم نوزع اللحم المعصج ونغطيه بطبقة ثانية من المكرونة والبشاميل.",
        "ندخل الصينية في فرن ساخن على مئة وثمانين درجة مئوية حتى يحمر الوجه الذهبي ثم نقطعها ونقدمها بالهناء والشفاء.",
    ]

    scene_responses = []
    for idx, item in enumerate(outline_payload["scene_outlines"]):
        sc_payload = {
            "scene_id": item["scene_id"],
            "order": item["order"],
            "title": item["title"],
            "purpose": item["purpose"],
            "scene_type": item["scene_type"],
            "narration": narrations_19_words[idx],
            "visual_direction": f"لقطة واضحة توضح {item['title']} داخل المطبخ.",
            "motion_description": "حركة كاميرا بطيئة نحو الطبق",
            "camera_movement": "slow zoom-in",
            "on_screen_text": item["title"],
            "learning_objective_ids": item["learning_objective_ids"],
            "estimated_duration_seconds": 10,
        }
        scene_responses.append(_make_chat_success_response(json.dumps(sc_payload, ensure_ascii=False)))

    mock_http.post.side_effect = [
        _make_chat_success_response(json.dumps(analysis_payload, ensure_ascii=False)),
        _make_chat_success_response(json.dumps(outline_payload, ensure_ascii=False)),
        *scene_responses,
    ]

    or_provider = OpenRouterProvider(
        api_key="sk-or-v1-test",
        model="openrouter/free",
        client=mock_http,
    )
    workflow = create_script_workflow(llm_provider=or_provider)
    req = TrainingVideoRequest(
        topic="How to Make Egyptian Macaroni Béchamel – Step-by-Step Cooking Tutorial",
        source_content="Create a 60-second Egyptian Arabic cooking tutorial explaining how to prepare macaroni béchamel.",
        base_language="ar-SA",
        target_languages=["ar-SA"],
        target_duration_seconds=60,
        video_style="demonstration_tutorial",
    )

    from app.workflows.script_generation.checkpoint import ScriptCheckpoint
    checkpoint = ScriptCheckpoint(tmp_path, req, or_provider.model_name)
    workflow = create_script_workflow(or_provider, checkpoint=checkpoint)
    if interrupt:
        initial_responses = list(mock_http.post.side_effect)
        mock_http.post.side_effect = initial_responses[:4] + [RuntimeError("simulated interruption")]
        failed = workflow.invoke(VideoScriptState(request=req))
        assert failed["workflow_status"] == "failed"
        checkpoint.finish(False)
        assert checkpoint.data["progress"]["scene_1"] == "completed"
        assert checkpoint.data["progress"]["scene_2"] == "completed"
        assert checkpoint.data["progress"]["scene_3"] == "failed"
        mock_http.reset_mock()
        mock_http.post.side_effect = initial_responses[4:]
        # Recreate checkpoint and graph, as after a process restart.
        checkpoint = ScriptCheckpoint(tmp_path, req, or_provider.model_name)
        workflow = create_script_workflow(or_provider, checkpoint=checkpoint)
    state = workflow.invoke(VideoScriptState(request=req))
    assert state["workflow_status"] == "completed"
    final_script = state["final_script"]
    assert final_script is not None
    assert final_script.language == "ar-SA"
    assert len(final_script.scenes) == 6
    assert final_script.total_estimated_duration_seconds == 60
    # Verify every scene has full V2 SceneMediaPlan and layout fields preserved
    for idx, sc in enumerate(final_script.scenes, start=1):
        assert sc.scene_id == f"scene_{idx}"
        assert sc.order == idx
        assert sc.media_plan is not None
        assert sc.media_plan.scene_id == f"scene_{idx}"
        assert sc.visual_direction != ""
    # Total calls: 1 ContentAnalysis + 1 ScriptOutline + 6 SceneDrafts = 8 bounded calls (0 full-script retries!)
    assert mock_http.post.call_count == (4 if interrupt else 8)


def test_staged_generation_targeted_scene_repair_regenerates_only_invalid_scene():
    """
    Verify Stage 5 Targeted Scene Repair:
    When Scene 2 initially has English narration instead of Arabic, only Scene 2 is regenerated
    (not Scene 1 or the entire script).
    """
    from app.workflows.script_generation.staged_generator import StagedScriptGenerator

    mock_http = MagicMock()
    analysis = ContentAnalysis(
        topic_summary="تحضير البشاميل",
        key_concepts=["الدقيق", "الحليب"],
        learning_objectives=[
            LearningObjective(id="LO1", description="تحضير صلصة البشاميل"),
            LearningObjective(id="LO2", description="خبز الصينية في الفرن"),
        ],
        audience_notes="المبتدئون",
        recommended_scene_count=2,
        recommended_structure=["البشاميل", "الخبز"],
        important_terms=["Béchamel"],
        factual_constraints=["180 درجة"],
    )
    req = TrainingVideoRequest(
        topic="Macaroni Béchamel",
        base_language="ar-SA",
        target_languages=["ar-SA"],
        target_duration_seconds=30,
    )

    outline_payload = {
        "title": "تحضير المكرونة بالبشاميل",
        "language": "ar-SA",
        "audience": "المبتدئون",
        "opening_hook": "تعرف على سر البشاميل الكريمي.",
        "closing_summary": "قدمها ساخنة.",
        "learning_objectives": [
            {"id": "LO1", "description": "تحضير صلصة البشاميل"},
            {"id": "LO2", "description": "خبز الصينية في الفرن"},
        ],
        "scene_outlines": [
            {
                "scene_id": "scene_1",
                "order": 1,
                "title": "تحضير الصلصة",
                "purpose": "مزج الزبدة والدقيق",
                "scene_type": "intro",
                "learning_objective_ids": ["LO1"],
                "target_duration_seconds": 15,
            },
            {
                "scene_id": "scene_2",
                "order": 2,
                "title": "الخبز والتقديم",
                "purpose": "خبز الصينية",
                "scene_type": "outro",
                "learning_objective_ids": ["LO2"],
                "target_duration_seconds": 15,
            },
        ],
    }

    # 29 Arabic words -> ~15s at 115 WPM
    ar_29_words_sc1 = (
        "نبدأ في المشهد الأول بإذابة الزبدة الصفراء في قدر عميق على نار متوسطة ثم نضيف الدقيق الأبيض "
        "ونقلبه باستمرار لمدة دقيقتين حتى يكتسب لوناً ذهبياً فاتحاً ورائحة شهية ومميزة."
    )
    # Scene 2 initial attempt is mistakenly in English!
    bad_en_sc2 = {
        "scene_id": "scene_2",
        "order": 2,
        "title": "Baking the Dish",
        "purpose": "Bake in oven",
        "scene_type": "outro",
        "narration": "Place the baking dish into a preheated oven at 180 degrees Celsius until the top is golden brown.",
        "visual_direction": "Close up of the oven.",
        "estimated_duration_seconds": 15,
    }
    # Scene 2 repaired in Arabic (29 words -> ~15s)
    ar_29_words_sc2 = (
        "نضع صينية المكرونة بالبشاميل داخل الفرن الساخن مسبقاً على درجة حرارة مئة وثمانين مئوية لمدة خمس وعشرين "
        "دقيقة حتى ينضج الخليط تماماً ويتحمر السطح العلوي ويصبح ذهبياً ومقرمشاً ولذيذاً."
    )

    sc1_good = {
        "scene_id": "scene_1",
        "order": 1,
        "title": "تحضير الصلصة",
        "purpose": "مزج الزبدة والدقيق",
        "scene_type": "intro",
        "narration": ar_29_words_sc1,
        "visual_direction": "لقطة للقدر على النار",
        "learning_objective_ids": ["LO1"],
        "estimated_duration_seconds": 15,
    }
    sc2_repaired = {
        "scene_id": "scene_2",
        "order": 2,
        "title": "الخبز والتقديم",
        "purpose": "خبز الصينية",
        "scene_type": "outro",
        "narration": ar_29_words_sc2,
        "visual_direction": "لقطة لإخراج الصينية من الفرن",
        "learning_objective_ids": ["LO2"],
        "estimated_duration_seconds": 15,
    }

    mock_http.post.side_effect = [
        _make_chat_success_response(json.dumps(outline_payload, ensure_ascii=False)),
        _make_chat_success_response(json.dumps(sc1_good, ensure_ascii=False)),
        _make_chat_success_response(json.dumps(bad_en_sc2, ensure_ascii=False)),
        _make_chat_success_response(json.dumps(sc2_repaired, ensure_ascii=False)),
    ]

    provider = OpenRouterProvider(api_key="sk-or-v1-test", model="openrouter/free", client=mock_http)
    staged = StagedScriptGenerator(provider)
    draft = staged.generate_script_draft(req, analysis)

    assert len(draft.scenes) == 2
    assert draft.scenes[0].narration == ar_29_words_sc1
    assert draft.scenes[1].narration == ar_29_words_sc2
    # 1 Outline + 1 Scene 1 + 1 Scene 2 (bad) + 1 Scene 2 (targeted repair) = 4 calls total
    assert mock_http.post.call_count == 4




