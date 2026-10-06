"""Application configuration settings using Pydantic Settings."""

from pathlib import Path
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    """Global application settings and environment variables."""

    # Application Information
    APP_NAME: str = "AI Training Video Generation Platform"
    APP_VERSION: str = "0.1.0"
    ENVIRONMENT: str = Field(default="development", description="Environment: development, staging, production")
    DEBUG: bool = Field(default=True, description="Debug mode flag")
    APP_HOST: str = Field(default="0.0.0.0", description="FastAPI host")
    APP_PORT: int = Field(default=8000, description="FastAPI port")
    LOG_LEVEL: str = Field(default="INFO", description="Logging level: DEBUG, INFO, WARNING, ERROR, CRITICAL")

    # Local Storage Directory
    STORAGE_PATH: Path = Field(default=Path("./storage/projects"), description="Base directory for project assets")

    # LLM Settings (Groq is default, extensible to others)
    DEFAULT_LLM_PROVIDER: str = Field(default="groq", description="Default LLM provider")
    GROQ_API_KEY: Optional[str] = Field(default=None, description="Groq API Key")
    GROQ_MODEL: str = Field(default="openai/gpt-oss-20b", description="Active Groq LLM model ID")

    # TTS Settings (Edge-TTS is default free tier)
    DEFAULT_TTS_PROVIDER: str = Field(default="edge_tts", description="Default TTS provider (edge_tts, azure, mock)")
    TTS_TIMEOUT_SECONDS: int = Field(default=60, description="Timeout in seconds for TTS generation")
    TTS_DEFAULT_VOICES: dict = Field(
        default={
            "en-US": "en-US-ChristopherNeural",
            "en": "en-US-ChristopherNeural",
            "ar-SA": "ar-SA-HamedNeural",
            "ar": "ar-SA-HamedNeural",
            "bn-BD": "bn-BD-PradeepNeural",
            "bn": "bn-BD-PradeepNeural",
            "es-ES": "es-ES-AlvaroNeural",
            "es": "es-ES-AlvaroNeural",
            "fr-FR": "fr-FR-HenriNeural",
            "fr": "fr-FR-HenriNeural",
            "de-DE": "de-DE-ConradNeural",
            "de": "de-DE-ConradNeural",
            "zh-CN": "zh-CN-YunxiNeural",
            "zh": "zh-CN-YunxiNeural",
        },
        description="Default locale-to-voice mapping for TTS providers"
    )
    AZURE_SPEECH_KEY: Optional[str] = Field(default=None, description="Azure Speech API Key")
    AZURE_SPEECH_REGION: str = Field(default="eastus", description="Azure Speech Region")

    # Avatar Settings (HeyGen)
    DEFAULT_AVATAR_PROVIDER: str = Field(default="mock", description="Default avatar provider: heygen, mock")
    HEYGEN_API_KEY: Optional[str] = Field(default=None, description="HeyGen API Key")
    HEYGEN_DEFAULT_AVATAR_ID: str = Field(default="default_avatar_wayne", description="Default HeyGen avatar ID")
    HEYGEN_POLL_INTERVAL_SECONDS: float = Field(default=2.0, description="Polling interval in seconds for HeyGen video rendering")
    HEYGEN_JOB_TIMEOUT_SECONDS: int = Field(default=300, description="Timeout in seconds for HeyGen video generation")
    ENABLE_LIVE_API_TESTS: bool = Field(default=False, description="Guard ensuring zero live paid API calls during testing")

    # Subtitle Settings (Whisper / Faster-Whisper)
    WHISPER_MODEL_SIZE: str = Field(default="base", description="Whisper model size (tiny, base, small, medium, large)")
    WHISPER_DEVICE: str = Field(default="cpu", description="Device for Whisper inference (cpu, cuda)")

    # Supporting Visuals Settings (Step 8)
    DEFAULT_VISUAL_PROVIDER: str = Field(default="local", description="Default visual asset provider: local, mock")
    VISUAL_WIDTH: int = Field(default=1920, description="Default visual image width in pixels")
    VISUAL_HEIGHT: int = Field(default=1080, description="Default visual image height in pixels")

    # Video Composition Settings (Step 9)
    DEFAULT_COMPOSITION_PROVIDER: str = Field(default="ffmpeg", description="Default composition provider: ffmpeg, mock")
    FFMPEG_BINARY_PATH: str = Field(default="ffmpeg", description="Path to ffmpeg binary")
    FFPROBE_BINARY_PATH: str = Field(default="ffprobe", description="Path to ffprobe binary")
    VIDEO_FPS: int = Field(default=30, description="Target video framerate")
    VIDEO_CODEC: str = Field(default="libx264", description="Video codec for FFmpeg rendering")
    AUDIO_CODEC: str = Field(default="aac", description="Audio codec for FFmpeg rendering")
    BURN_SUBTITLES: bool = Field(default=True, description="Whether to burn subtitles into final video render")

    # Script Generation & Validation Settings
    SCRIPT_WORDS_PER_MINUTE: int = Field(default=140, description="Estimated spoken words per minute for narration timing")
    SCRIPT_DURATION_TOLERANCE_PERCENT: int = Field(default=20, description="Allowed deviation percentage from target duration")
    SCRIPT_DEFAULT_MAX_REVISIONS: int = Field(default=1, description="Maximum revision iterations in LangGraph workflow")

    # Localization Settings (Step 4)
    LOCALIZATION_MAX_REVISIONS: int = Field(default=1, description="Maximum revision attempts for invalid localized scripts")
    LOCALIZATION_DEFAULT_ADAPTATION_LEVEL: str = Field(default="cultural_adaptation", description="Default adaptation level: translation, natural_localization, cultural_adaptation")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    def ensure_directories(self) -> None:
        """Ensure necessary storage directories exist."""
        self.STORAGE_PATH.mkdir(parents=True, exist_ok=True)


# Singleton settings instance
settings = Settings()
settings.ensure_directories()
