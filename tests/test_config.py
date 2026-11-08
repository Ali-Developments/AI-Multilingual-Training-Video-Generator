"""Unit tests for configuration management."""

from pathlib import Path
from app.core.config import Settings


def test_default_settings():
    """Verify default configuration parameters."""
    settings = Settings(_env_file=None)
    assert settings.APP_NAME == "AI Training Video Generation Platform"
    assert settings.DEFAULT_LLM_PROVIDER == "groq"
    assert settings.GROQ_MODEL == "openai/gpt-oss-20b"
    assert settings.DEFAULT_TTS_PROVIDER == "edge_tts"
    assert settings.WHISPER_MODEL_SIZE == "base"
    assert isinstance(settings.STORAGE_PATH, Path)


def test_settings_environment_override(monkeypatch):
    """Verify settings pick up environment variable overrides correctly."""
    monkeypatch.setenv("APP_NAME", "Custom Video Engine")
    monkeypatch.setenv("DEFAULT_LLM_PROVIDER", "custom_llm")
    monkeypatch.setenv("DEBUG", "False")

    custom_settings = Settings()
    assert custom_settings.APP_NAME == "Custom Video Engine"
    assert custom_settings.DEFAULT_LLM_PROVIDER == "custom_llm"
    assert custom_settings.DEBUG is False


def test_ensure_directories(tmp_path):
    """Verify ensure_directories creates the required storage path."""
    test_storage = tmp_path / "nested" / "storage"
    settings = Settings(STORAGE_PATH=test_storage)
    assert not test_storage.exists()
    settings.ensure_directories()
    assert test_storage.exists()
    assert test_storage.is_dir()
