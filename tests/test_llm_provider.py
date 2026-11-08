"""Comprehensive unit tests for LLMProvider and GroqProvider.

Verifies:
1. Model configuration is fully dynamic and loaded from settings / env.
2. No model ID is hardcoded inside the provider implementation.
3. Provider honors configured model ID in all API payload requests.
4. All API calls are strictly mocked with zero real network requests.
5. Error handling and retry logic perform accurately.
6. Structured script draft generation parses correctly into Pydantic models.
"""

import inspect
import json
from unittest.mock import MagicMock, patch
import pytest
from groq import RateLimitError, AuthenticationError

from app.core.config import Settings
from app.models.schemas import ScriptDraft, SceneDraft
from app.services.llm.groq_provider import GroqProvider
from app.services.llm.factory import get_llm_provider


def test_no_hardcoded_model_in_groq_provider_source():
    """Verify that no specific model name is hardcoded in GroqProvider source code."""
    source_code = inspect.getsource(GroqProvider)
    # Check that neither gpt-oss nor llama nor mixtral nor any specific model string is hardcoded
    assert "openai/gpt-oss-20b" not in source_code
    assert "openai/gpt-oss-120b" not in source_code
    assert "llama-3.3-70b-versatile" not in source_code
    assert "llama-3.1-8b-instant" not in source_code
    assert "mixtral" not in source_code
    assert "gemma" not in source_code


def test_default_model_is_openai_gpt_oss_20b(monkeypatch):
    """Verify default configured model for GroqProvider is openai/gpt-oss-20b."""
    monkeypatch.delenv("GROQ_MODEL", raising=False)
    with patch("app.services.llm.groq_provider.settings", Settings(_env_file=None)):
        provider = GroqProvider(api_key="mock-key")
        assert provider.model_name == "openai/gpt-oss-20b"


def test_provider_switches_to_alternate_model_via_configuration(monkeypatch):
    """Verify provider can seamlessly switch to another Groq model (e.g. openai/gpt-oss-120b) via configuration."""
    monkeypatch.setenv("GROQ_MODEL", "openai/gpt-oss-120b")
    monkeypatch.setenv("GROQ_API_KEY", "test-key")

    custom_settings = Settings()
    with patch("app.services.llm.groq_provider.settings", custom_settings):
        provider = GroqProvider()
        assert provider.model_name == "openai/gpt-oss-120b"


def test_provider_loads_model_from_configuration(monkeypatch):
    """Verify GroqProvider resolves any custom model from application settings."""
    test_custom_model = "test-custom-model-id"
    monkeypatch.setenv("GROQ_MODEL", test_custom_model)
    monkeypatch.setenv("GROQ_API_KEY", "test-key")

    custom_settings = Settings()
    with patch("app.services.llm.groq_provider.settings", custom_settings):
        provider = GroqProvider()
        assert provider.model_name == test_custom_model


def test_provider_accepts_explicit_model_override():
    """Verify explicit model passed to constructor overrides global settings."""
    explicit_model = "explicitly-passed-model-v1"
    provider = GroqProvider(api_key="mock-key", model=explicit_model)
    assert provider.model_name == explicit_model


def test_provider_passes_configured_model_to_api():
    """Verify that chat completion API call receives the configured model in parameters."""
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=MagicMock(content="Sample response text"))]
    mock_client.chat.completions.create.return_value = mock_response

    configured_model = "enterprise-llama-test"
    provider = GroqProvider(
        api_key="mock-key",
        model=configured_model,
        client=mock_client
    )

    result = provider.generate_text(
        prompt="Explain photosynthesis",
        system_prompt="Be concise",
        temperature=0.5
    )

    assert result == "Sample response text"
    mock_client.chat.completions.create.assert_called_once()
    _, call_kwargs = mock_client.chat.completions.create.call_args
    assert call_kwargs["model"] == configured_model
    assert call_kwargs["temperature"] == 0.5
    assert call_kwargs["messages"][0]["content"] == "Be concise"
    assert call_kwargs["messages"][1]["content"] == "Explain photosynthesis"


def test_provider_structured_output():
    """Verify generate_structured parses JSON mode output into requested Pydantic model."""
    mock_client = MagicMock()
    sample_scene = {
        "scene_number": 1,
        "title": "Introduction to Phishing",
        "narration": "Welcome to cybersecurity basics.",
        "visual_description": "Animated graphic showing an email envelope with a warning sign.",
        "estimated_duration_seconds": 12
    }
    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=MagicMock(content=json.dumps(sample_scene)))]
    mock_client.chat.completions.create.return_value = mock_response

    provider = GroqProvider(
        api_key="mock-key",
        model="test-model-json",
        client=mock_client
    )

    parsed_model = provider.generate_structured(
        prompt="Create a scene on phishing",
        schema=SceneDraft
    )

    assert isinstance(parsed_model, SceneDraft)
    assert parsed_model.scene_number == 1
    assert parsed_model.title == "Introduction to Phishing"
    assert parsed_model.estimated_duration_seconds == 12
    _, call_kwargs = mock_client.chat.completions.create.call_args
    resp_fmt = call_kwargs["response_format"]
    assert resp_fmt["type"] == "json_schema"
    assert resp_fmt["json_schema"]["strict"] is True
    assert resp_fmt["json_schema"]["name"] == "SceneDraft"


def test_provider_generate_script_draft():
    """Verify generate_script_draft formats and validates complete ScriptDraft schema."""
    mock_client = MagicMock()
    full_script_data = {
        "title": "Workplace Phishing Defense",
        "target_audience": "Corporate Employees",
        "language": "en-US",
        "scenes": [
            {
                "scene_number": 1,
                "title": "Welcome",
                "narration": "Today we learn how to spot suspicious emails.",
                "visual_description": "Office workstation overview",
                "estimated_duration_seconds": 15
            },
            {
                "scene_number": 2,
                "title": "Red Flags",
                "narration": "Look closely at the sender domain name.",
                "visual_description": "Magnifying glass zooming on email address",
                "estimated_duration_seconds": 25
            }
        ],
        "total_estimated_duration_seconds": 40
    }
    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=MagicMock(content=json.dumps(full_script_data)))]
    mock_client.chat.completions.create.return_value = mock_response

    provider = GroqProvider(
        api_key="mock-key",
        model="test-script-model",
        client=mock_client
    )

    script = provider.generate_script_draft(
        topic="Phishing Defense",
        target_audience="Corporate Employees",
        duration_minutes=1
    )

    assert isinstance(script, ScriptDraft)
    assert script.title == "Workplace Phishing Defense"
    assert len(script.scenes) == 2
    assert script.scenes[0].scene_number == 1
    assert script.scenes[1].scene_number == 2
    assert script.total_estimated_duration_seconds == 40


def test_retry_on_rate_limit(monkeypatch):
    """Verify provider retries on RateLimitError using backoff and succeeds on subsequent try."""
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=MagicMock(content="Retried successfully"))]

    # Mock time.sleep to run instantly during test
    monkeypatch.setattr("time.sleep", lambda s: None)

    # First call raises RateLimitError, second call succeeds
    mock_request = MagicMock()
    rate_limit_err = RateLimitError(
        message="Rate limit reached",
        response=MagicMock(status_code=429),
        body={}
    )
    mock_client.chat.completions.create.side_effect = [rate_limit_err, mock_response]

    provider = GroqProvider(
        api_key="mock-key",
        model="rate-limit-test-model",
        max_retries=3,
        retry_backoff_factor=1.0,
        client=mock_client
    )

    result = provider.generate_text("Test prompt")
    assert result == "Retried successfully"
    assert mock_client.chat.completions.create.call_count == 2


def test_non_retryable_auth_error():
    """Verify AuthenticationError is not retried and raises immediately."""
    mock_client = MagicMock()
    auth_err = AuthenticationError(
        message="Invalid API Key",
        response=MagicMock(status_code=401),
        body={}
    )
    mock_client.chat.completions.create.side_effect = auth_err

    provider = GroqProvider(
        api_key="invalid-key",
        model="auth-test-model",
        max_retries=3,
        client=mock_client
    )

    with pytest.raises(AuthenticationError):
        provider.generate_text("Test prompt")

    assert mock_client.chat.completions.create.call_count == 1


def test_factory_returns_configured_provider():
    """Verify get_llm_provider instantiates the correct provider using settings."""
    provider = get_llm_provider(api_key="mock-key", model="factory-test-model")
    assert isinstance(provider, GroqProvider)
    assert provider.model_name == "factory-test-model"


def test_factory_raises_for_unsupported_provider():
    """Verify get_llm_provider raises an error for unsupported provider string."""
    with pytest.raises(ValueError, match="Unsupported LLM provider"):
        get_llm_provider("non_existent_provider")
