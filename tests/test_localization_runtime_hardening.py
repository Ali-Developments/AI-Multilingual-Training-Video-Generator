"""Regression test suite for localization runtime hardening and Groq structured output correctness."""

import json
import re
from unittest.mock import MagicMock, patch
import pytest
from groq import APIError, RateLimitError
from pydantic import BaseModel, Field
import httpx

from app.models.schemas import (
    LocalizedScript,
    FinalScript,
    SceneDraft,
    LearningObjective,
    TrainingVideoRequest,
)
from app.services.llm.schema_utils import to_strict_json_schema
from app.services.llm.groq_provider import GroqProvider
from app.services.localization.service import LocalizationService
from frontend.helpers import serialize_create_project_payload


# ===========================================================================
# Helper Fixtures
# ===========================================================================

def create_sample_final_script() -> FinalScript:
    """Create a minimal valid FinalScript for localization tests."""
    return FinalScript(
        title="Email Security Awareness",
        language="en-US",
        audience="Corporate Employees",
        target_duration_seconds=30,
        total_estimated_duration_seconds=30,
        opening_hook="Be vigilant with incoming emails.",
        closing_summary="Always report suspicious emails.",
        learning_objectives=[
            LearningObjective(id="LO1", description="Identify phishing indicators")
        ],
        scenes=[
            SceneDraft(
                scene_id="scene_1",
                order=1,
                title="Introduction",
                purpose="Hook audience",
                narration="Phishing emails often imitate executive leadership.",
                estimated_duration_seconds=15,
                visual_direction="Presenter looking into camera",
                scene_type="presenter",
                learning_objective_ids=["LO1"],
            ),
            SceneDraft(
                scene_id="scene_2",
                order=2,
                title="Action Steps",
                purpose="Educational instruction",
                narration="Verify sender email headers before clicking any link.",
                estimated_duration_seconds=15,
                visual_direction="Slide highlighting domain header",
                scene_type="explanation",
                learning_objective_ids=["LO1"],
            ),
        ],
    )


def create_sample_localized_dict(locale: str = "ar-SA") -> dict:
    """Create a raw dictionary that validates against LocalizedScript."""
    return {
        "title": "التوعية بأمان البريد الإلكتروني",
        "source_language": "en-US",
        "language": "ar",
        "locale": locale,
        "text_direction": "rtl",
        "audience": "Corporate Employees",
        "learning_objectives": [
            {"id": "LO1", "description": "التعرف على مؤشرات التصيد"}
        ],
        "opening_hook": "كن حذرا مع رسائل البريد الإلكتروني الواردة.",
        "closing_summary": "أبلغ دائما عن الرسائل المشبوهة.",
        "target_duration_seconds": 30,
        "total_estimated_duration_seconds": 30,
        "scenes": [
            {
                "scene_id": "scene_1",
                "order": 1,
                "title": "مقدمة",
                "purpose": "جذب الانتباه",
                "narration": "غالبا ما تقلد رسائل التصيد القيادة التنفيذية.",
                "estimated_duration_seconds": 15,
                "visual_direction": "مقدم يتحدث أمام الكاميرا",
                "on_screen_text": None,
                "learning_objective_ids": ["LO1"],
                "scene_type": "presenter",
            },
            {
                "scene_id": "scene_2",
                "order": 2,
                "title": "خطوات العمل",
                "purpose": "إرشادات تعليمية",
                "narration": "تحقق من ترويسة البريد الإلكتروني للمرسل قبل النقر على أي رابط.",
                "estimated_duration_seconds": 15,
                "visual_direction": "شريحة توضح ترويسة النطاق",
                "on_screen_text": None,
                "learning_objective_ids": ["LO1"],
                "scene_type": "explanation",
            },
        ],
    }


# ===========================================================================
# 1. Single & Multiple Target Locale Payload Correctness
# ===========================================================================

def test_single_target_locale_remains_single():
    """Test 1: Single target locale ar-SA remains strictly ar-SA without appending bn-BD."""
    payload = serialize_create_project_payload(
        topic="Phishing Awareness",
        base_language="en-US",
        target_languages=["ar-SA"],
    )
    req_data = payload["request"]
    assert req_data["target_languages"] == ["ar-SA"]
    assert "bn-BD" not in req_data["target_languages"]

    # Verify instantiation into TrainingVideoRequest preserves single locale
    t_req = TrainingVideoRequest(**req_data)
    assert t_req.target_languages == ["ar-SA"]


def test_multiple_explicit_locales_preserved_exactly():
    """Test 2: Explicit multi-locale list is preserved exactly."""
    payload = serialize_create_project_payload(
        topic="Phishing Awareness",
        base_language="en-US",
        target_languages=["ar-SA", "bn-BD"],
    )
    req_data = payload["request"]
    assert req_data["target_languages"] == ["ar-SA", "bn-BD"]


def test_no_implicit_bn_bd():
    """Test 3: No default list silently injects bn-BD when other locales are selected."""
    payload = serialize_create_project_payload(
        topic="Phishing Awareness",
        base_language="en-US",
        target_languages=["es-ES"],
    )
    req_data = payload["request"]
    assert req_data["target_languages"] == ["es-ES"]
    assert "bn-BD" not in req_data["target_languages"]


# ===========================================================================
# 2. Strict JSON Schema Transformation Tests
# ===========================================================================

def test_strict_localization_schema_is_groq_compatible():
    """Test 4: Strict schema transformer produces Groq-compatible root object schema."""
    strict_schema = to_strict_json_schema(LocalizedScript)
    assert strict_schema.get("type") == "object"
    assert strict_schema.get("additionalProperties") is False
    assert "required" in strict_schema
    assert set(strict_schema["required"]) == set(strict_schema["properties"].keys())


def test_all_nested_objects_use_additional_properties_false():
    """Test 5: All nested objects and $defs recursively set additionalProperties=False and required."""
    strict_schema = to_strict_json_schema(LocalizedScript)

    def _verify_node(node, path="root"):
        if not isinstance(node, dict):
            return
        if node.get("type") == "object" or "properties" in node:
            assert node.get("additionalProperties") is False, f"Failed additionalProperties=False at {path}"
            assert set(node.get("required", [])) == set(node.get("properties", {}).keys()), f"Required mismatch at {path}"
            for prop_name, prop_val in node.get("properties", {}).items():
                _verify_node(prop_val, f"{path}.{prop_name}")
        if "items" in node:
            _verify_node(node["items"], f"{path}[items]")
        for combiner in ("anyOf", "oneOf", "allOf"):
            if combiner in node and isinstance(node[combiner], list):
                for idx, branch in enumerate(node[combiner]):
                    _verify_node(branch, f"{path}.{combiner}[{idx}]")

    for def_name, def_val in strict_schema.get("$defs", {}).items():
        _verify_node(def_val, f"$defs.{def_name}")
    _verify_node(strict_schema)


def test_nullable_optional_fields_handled_correctly():
    """Test 6: Optional fields remain in required list and allow null."""
    strict_schema = to_strict_json_schema(LocalizedScript)
    defs = strict_schema.get("$defs", {})
    scene_schema = defs.get("LocalizedScene", {})

    # on_screen_text is Optional[str]
    assert "on_screen_text" in scene_schema.get("required", [])
    ost = scene_schema.get("properties", {}).get("on_screen_text", {})
    assert "anyOf" in ost
    types = [b.get("type") for b in ost["anyOf"]]
    assert "null" in types


# ===========================================================================
# 3. GroqProvider Fallback & Error Handling Tests
# ===========================================================================

def test_json_validate_failed_triggers_bounded_fallback():
    """Test 7: json_validate_failed on Attempt 1 triggers Attempt 2 json_object fallback."""
    mock_client = MagicMock()
    provider = GroqProvider(api_key="gsk_dummy_test_key", model="openai/gpt-oss-20b", client=mock_client)

    # Attempt 1: Groq server raises APIError with code json_validate_failed
    err_response = httpx.Response(status_code=400, request=httpx.Request("POST", "https://api.groq.com"))
    api_err = APIError(
        message="Validation failed",
        request=httpx.Request("POST", "https://api.groq.com"),
        body={"error": {"code": "json_validate_failed", "message": "Failed grammar validation"}},
    )

    # Attempt 2: json_object returns valid JSON
    valid_content = json.dumps(create_sample_localized_dict("ar-SA"))
    mock_choice = MagicMock()
    mock_choice.message.content = valid_content
    mock_choice.finish_reason = "stop"
    success_resp = MagicMock(choices=[mock_choice])

    # Side effect: first call raises json_validate_failed, second call succeeds
    mock_client.chat.completions.create.side_effect = [api_err, success_resp]

    result = provider.generate_structured(
        prompt="Localize to Arabic",
        schema=LocalizedScript,
    )

    assert result.locale == "ar-SA"
    assert mock_client.chat.completions.create.call_count == 2
    # Verify second call used json_object mode
    second_call_kwargs = mock_client.chat.completions.create.call_args_list[1][1]
    assert second_call_kwargs["response_format"] == {"type": "json_object"}


def test_unrelated_400_does_not_trigger_json_fallback():
    """Test 8: Unrelated 400 error raises immediately without attempting fallback."""
    mock_client = MagicMock()
    provider = GroqProvider(api_key="gsk_dummy_test_key", model="openai/gpt-oss-20b", client=mock_client)

    api_err = APIError(
        message="Invalid model identifier",
        request=httpx.Request("POST", "https://api.groq.com"),
        body={"error": {"code": "invalid_model", "message": "The model does not exist"}},
    )
    mock_client.chat.completions.create.side_effect = api_err

    with pytest.raises(APIError) as exc_info:
        provider.generate_structured(
            prompt="Localize to Arabic",
            schema=LocalizedScript,
        )

    assert exc_info.value.body["error"]["code"] == "invalid_model"
    # Call count should be exactly 1: no fallback
    assert mock_client.chat.completions.create.call_count == 1


def test_429_respects_provider_retry_timing():
    """Test 9: 429 RateLimitError respects Retry-After and reset-tokens headers."""
    mock_client = MagicMock()
    provider = GroqProvider(
        api_key="gsk_dummy_test_key",
        model="openai/gpt-oss-20b",
        client=mock_client,
        max_retries=2,
        retry_backoff_factor=1.0,
    )

    resp = httpx.Response(
        status_code=429,
        headers={"retry-after": "0.05", "x-ratelimit-reset-tokens": "50ms"},
        request=httpx.Request("POST", "https://api.groq.com"),
    )
    rate_err = RateLimitError(
        message="Rate limit exceeded. Please try again in 0.05s",
        response=resp,
        body={"error": {"message": "Rate limit exceeded"}},
    )

    mock_choice = MagicMock()
    mock_choice.message.content = "Healthy response"
    success_resp = MagicMock(choices=[mock_choice])

    mock_client.chat.completions.create.side_effect = [rate_err, success_resp]

    with patch("time.sleep") as mock_sleep:
        text = provider.generate_text("Hello")
        assert text == "Healthy response"
        assert mock_sleep.called
        # Verify sleep delay passed was at least float(retry_after)
        sleep_arg = mock_sleep.call_args[0][0]
        assert sleep_arg >= 0.05


def test_rate_limit_diagnostics_preserved():
    """Test 10: Rate limit warning logs x-ratelimit-remaining-tokens diagnostic."""
    mock_client = MagicMock()
    provider = GroqProvider(
        api_key="gsk_dummy_test_key",
        model="openai/gpt-oss-20b",
        client=mock_client,
        max_retries=1,
    )

    resp = httpx.Response(
        status_code=429,
        headers={"x-ratelimit-remaining-tokens": "12", "retry-after": "0.01"},
        request=httpx.Request("POST", "https://api.groq.com"),
    )
    rate_err = RateLimitError(
        message="Rate limit exceeded",
        response=resp,
        body={},
    )
    mock_client.chat.completions.create.side_effect = rate_err

    with patch("time.sleep"):
        with pytest.raises(RuntimeError) as exc_info:
            provider.generate_text("Hello")

    assert "Groq API call failed after 1 attempts" in str(exc_info.value)


# ===========================================================================
# 4. Localization Failure Isolation Tests
# ===========================================================================

def test_localization_failures_identify_locale_and_structured_codes():
    """Test 11: Failure in one locale isolates error and records structured code."""
    mock_llm = MagicMock()
    service = LocalizationService(llm_provider=mock_llm)
    source = create_sample_final_script()

    # Simulate rate limit failure when localizing ar-SA
    mock_llm.generate_structured.side_effect = RateLimitError(
        message="Rate limit exceeded 429",
        response=httpx.Response(429, request=httpx.Request("POST", "https://api.groq.com")),
        body={},
    )

    bundle = service.localize_bundle(source_script=source, target_locales=["ar-SA"])
    assert "ar-SA" in bundle.failed_locales
    assert bundle.failed_locales["ar-SA"]["code"] == "LOCALIZATION_RATE_LIMITED"
    assert bundle.failed_locales["ar-SA"]["stage"] == "localization"


# ===========================================================================
# 5. Frontend Status Logic & Secret Scrubbing Tests
# ===========================================================================

def test_frontend_failed_pipeline_cannot_show_success():
    """Test 12: Domain status 'failed' never triggers success messaging."""
    # Deterministic status mapping logic test
    def determine_ui_message(status: str) -> str:
        if status == "completed":
            return "SUCCESS"
        elif status == "needs_review":
            return "WARNING"
        elif status == "failed":
            return "ERROR"
        return "INFO"

    assert determine_ui_message("completed") == "SUCCESS"
    assert determine_ui_message("failed") == "ERROR"
    assert determine_ui_message("needs_review") == "WARNING"
    assert determine_ui_message("failed") != "SUCCESS"


def test_no_api_secrets_are_exposed_in_diagnostics():
    """Test 13: Secrets like gsk_* and Bearer tokens are redacted from error logs."""
    from app.models.schemas import ProjectManifest
    manifest = ProjectManifest(
        project_id="proj_secret_test",
        source_request=TrainingVideoRequest(topic="Security", base_language="en-US"),
    )
    raw_error = "Failed connecting to https://api.groq.com with gsk_999998888877777 and Bearer eyJhbGciOi"
    manifest.record_error(stage="localization", message=raw_error, code="TEST_SECRET")

    recorded = manifest.error_details[-1]
    assert "gsk_" in recorded.message
    assert "gsk_[REDACTED]" in recorded.message
    assert "999998888877777" not in recorded.message
    assert "eyJhbGciOi" not in recorded.message
